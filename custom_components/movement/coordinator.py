"""The Movement coordinator."""

from dataclasses import fields, is_dataclass, replace
import datetime as dt
from functools import partial
import logging
import re
import time
from typing import Any, Final, NoReturn, TypedDict

from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er, event as evt
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util, slugify

from .calculations import (
    calculate_distance,
    calculate_distance_adjustments,
    calculate_speed,
    get_updates_for_typed_movement_sensor,
    mode_of_transit_from_speed,
    update_or_maintain_mode,
)
from .const import (
    CONF_DEPENDENT_ENTITIES,
    CONF_TRACKED_ENTITY,
    DOMAIN,
    UPDATES_STALLED_DELTA,
)
from .history import HistoryRegistry
from .statistics import (
    STAT_AVERAGE_LINEAR,
    STAT_CHANGE_SECOND,
    STAT_VALUE_MAX,
    Statistic,
)
from .transition import TransitionRegistry
from .types import (
    EntityMissingError,
    HistoryEntry,
    MisconfigurationError,
    ModeOfTransit,
    MovementConfigEntry,
    MovementData,
    ResetRequest,
    ServiceAdjustment,
    SkipUpdateCondition,
    SpeedStaleIndicator,
    StateChangedData,
    StatisticGroup,
    TransitionEntry,
    TransitionRequiredCondition,
    TypedMovementData,
    UpdatesStalledIndicator,
)

UPDATE_RATE_STATISTIC_MAX_AGE = UPDATES_STALLED_DELTA
SPEED_AVERAGE_STATISTIC_MAX_AGE = dt.timedelta(minutes=8)
SPEED_MAXIMUM_STATISTIC_MAX_AGE = dt.timedelta(minutes=3)


DEFAULT_TYPED_MOVEMENT_DATA: Final = TypedMovementData(
    distance=0,
    trip_start=None,
    trip_distance=None,
    trip_adjustments=None,
)


_LOGGER = logging.getLogger(__name__)
_TRACE = 5


class MovementUpdateCoordinator(DataUpdateCoordinator[MovementData]):
    """Class to manage movement calculations and updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MovementConfigEntry,
    ) -> None:
        """Initialize."""
        self.tracked_entity: str = config_entry.data[CONF_TRACKED_ENTITY]
        self.dependent_entities: list[str] = config_entry.data.get(
            CONF_DEPENDENT_ENTITIES,
            [],
        )
        self.history = HistoryRegistry()
        self.transition = TransitionRegistry(config_entry)
        self.change: (
            ResetRequest
            | ServiceAdjustment
            | SpeedStaleIndicator
            | StateChangedData
            | UpdatesStalledIndicator
            | None
        ) = None
        self.walking_movement_data = replace(DEFAULT_TYPED_MOVEMENT_DATA)
        self.biking_movement_data = replace(DEFAULT_TYPED_MOVEMENT_DATA)
        self.driving_movement_data = replace(DEFAULT_TYPED_MOVEMENT_DATA)
        self.statistics = StatisticGroup(
            update_rate=Statistic(
                state_characteristic=STAT_CHANGE_SECOND,
                samples_max_buffer_size=None,
                samples_max_age=UPDATE_RATE_STATISTIC_MAX_AGE,
            ),
            speed_recent_avg=Statistic(
                state_characteristic=STAT_AVERAGE_LINEAR,
                samples_max_buffer_size=None,
                samples_max_age=SPEED_AVERAGE_STATISTIC_MAX_AGE,
            ),
            speed_recent_max=Statistic(
                state_characteristic=STAT_VALUE_MAX,
                samples_max_buffer_size=None,
                samples_max_age=SPEED_MAXIMUM_STATISTIC_MAX_AGE,
            ),
        )

        self._reset_listener: CALLBACK_TYPE | None = None
        self._statistics_update_listener: CALLBACK_TYPE | None = None
        self._updates_stalled_listener: CALLBACK_TYPE | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=config_entry.title,
            update_interval=None,
        )

    def inject_data(
        self,
        data: MovementData,
        *,
        history: list[HistoryEntry],
        transition: list[TransitionEntry] | None,
    ) -> None:
        """Inject new data.

        This sets new data & history without:

        - Canceling any scheduled refreshes.
        - Scheduling a new refresh.
        - Notifying listeners.

        Make an additional call to `async_set_updated_data` if that
        functionality is required.
        """
        self.data: MovementData = data
        self.history.reset(history)
        self.transition.reset(transition)

    def inject_typed_movement_data(
        self,
        movement_type: ModeOfTransit,
        data: TypedMovementData,
    ) -> None:
        """Inject typed movement data.

        Like `inject_data`, but for the typed data stored for specific movement
        types.
        """
        setattr(self, f"{movement_type!s}_movement_data", data)

        # ensure sensor availability now that restore is complete. this covers
        # the case where the main distance traveled sensor is disabled and
        # other sensors are being restored. they should be available as soon as
        # they've been restored (and not after another update).
        self.data.change_count = max(self.data.change_count, 0)

    async def async_perform_service_adjustment(
        self,
        adjustment: ServiceAdjustment,
    ) -> None:
        assert self.change is None, (
            "only one change handler should be invoked before refresh"
        )

        self.change = adjustment

        await self.async_refresh()

    async def async_handle_entity_state_change(
        self,
        event: Event[EventStateChangedData],
    ) -> None:
        """Fetch and process state change event."""
        data = event.data
        old_state = data["old_state"]
        new_state = data["new_state"]

        _LOGGER.debug(
            "%s (%s) state changed on %s, %s -> %s",
            self.config_entry.title,
            self.config_entry.entry_id,
            self.tracked_entity,
            old_state,
            new_state,
        )

        assert self.change is None, (
            "only one change handler should be invoked before refresh"
        )

        if old_state and new_state:
            _LOGGER.debug(
                "%s (%s) state changed between valid states "
                "-> refresh:state-changed-data",
                self.config_entry.title,
                self.config_entry.entry_id,
            )

            self.change = StateChangedData(
                old_state=old_state,
                new_state=new_state,
            )

            await self.async_refresh()

    async def async_handle_tracked_entity_change(
        self,
        event: Event[er.EventEntityRegistryUpdatedData],
    ) -> None:
        """Fetch and process tracked entity change event."""
        data = event.data
        if data["action"] == "remove":
            self._create_removed_tracked_entity_issue(data["entity_id"])

        if data["action"] == "update" and "entity_id" in data["changes"]:
            old_tracked_entity_id = data["old_entity_id"]
            new_tracked_entity_id = data["entity_id"]

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_TRACKED_ENTITY: new_tracked_entity_id
                    if self.tracked_entity == old_tracked_entity_id
                    else self.tracked_entity,
                    CONF_DEPENDENT_ENTITIES: [
                        new_tracked_entity_id
                        if tracked_entity == old_tracked_entity_id
                        else tracked_entity
                        for tracked_entity in self.dependent_entities
                    ],
                },
            )

    def cancel_all_listeners(self) -> None:
        """Cancel all scheduled listeners."""
        self._async_cancel_reset_listener()
        self._async_cancel_statistics_update_listener()
        self._async_cancel_updates_stalled_listener()

    def _async_cancel_reset_listener(self) -> None:
        """Cancel the reset event listener."""
        if self._reset_listener:
            self._reset_listener()
            self._reset_listener = None

    def _async_cancel_statistics_update_listener(self) -> None:
        """Cancel the scheduled statistics update listener."""
        if self._statistics_update_listener:
            self._statistics_update_listener()
            self._statistics_update_listener = None

    def _async_cancel_updates_stalled_listener(self) -> None:
        """Cancel the updates stalled event listener."""
        if self._updates_stalled_listener:
            self._updates_stalled_listener()
            self._updates_stalled_listener = None

    @callback
    async def _async_perform_reset(
        self,
        now: dt.datetime | None = None,  # noqa: ARG002
    ) -> None:
        """Timer callback for daily resets."""
        assert self.change is None, (
            "only one change handler should be invoked before refresh"
        )

        _LOGGER.debug(
            "%s (%s): executing handler for daily midnight cycle reset "
            "-> refresh:reset-request",
            self.config_entry.title,
            self.config_entry.entry_id,
        )

        self.change = ResetRequest()
        self._async_cancel_reset_listener()

        await self.async_refresh()

    @callback
    async def _async_handle_statistics_update(
        self,
        now: dt.datetime,  # noqa: ARG002
    ) -> None:
        """Timer callback for sensor update."""
        _LOGGER.debug(
            "%s (%s): executing handler for scheduled statistics update",
            self.config_entry.title,
            self.config_entry.entry_id,
        )

        # update each of the stats while tracking which ones become invalid
        became_invalid = set()
        for key, stat in self.statistics.items():
            initial_value = stat.value
            stat.update()
            updated_value = stat.value

            if initial_value is not None and updated_value is None:
                became_invalid.add(key)

        # now that the updates are complete, reschedule for another statistic
        # update.
        self._async_cancel_statistics_update_listener()
        self._schedule_statistics_update()

        assert self.change is None, (
            "only one change handler should be invoked before refresh"
        )

        # check if any speed sensors became invalid which results in needing to
        # do a refresh for recalculating the speed and mode of transit. but if
        # a recalculation isn't needed, then update all the listening sensors so
        # they can show updated values (on any attributes).
        speed_sensors_became_invalid = became_invalid & {
            "speed_recent_avg",
            "speed_recent_max",
        }

        if speed_sensors_became_invalid:
            _LOGGER.debug(
                "%s (%s): speed sensor(s) became invalid: %s "
                "-> refresh:speed-stale-indicator",
                self.config_entry.title,
                self.config_entry.entry_id,
                speed_sensors_became_invalid,
            )

            self.change = SpeedStaleIndicator()

            await self.async_refresh()
        else:
            self.async_update_listeners()

    @callback
    async def _async_handle_updates_stalled(
        self,
        now: dt.datetime | None = None,  # noqa: ARG002
    ) -> None:
        """Timer callback for updates stalling."""
        assert self.change is None, (
            "only one change handler should be invoked before refresh"
        )

        _LOGGER.debug(
            "%s (%s): executing handler for updates having stalled "
            "-> refresh:updates-stalled-indicator",
            self.config_entry.title,
            self.config_entry.entry_id,
        )

        self.change = UpdatesStalledIndicator()
        self._async_cancel_updates_stalled_listener()

        await self.async_refresh()

    async def _async_setup(self) -> None:
        await super()._async_setup()

        self.data = MovementData(
            distance=0,
            adjustments=0,
            speed=None,
            mode_of_transit=None,
            change_count=-1,
            ignore_count=0,
        )

    async def _async_update_data(self) -> MovementData:
        assert self.data is not None

        for stat in self.statistics:
            stat.update()

        self.update: MovementData = replace(self.data, distance=0, adjustments=0)

        with self.transition.update_pending(noop_update_on_exit=True):
            try:
                self._internal_recalc()
            except SkipUpdateCondition as err:
                self.update = replace(
                    self.data,
                    ignore_count=self.data.ignore_count + 1,
                )
                _LOGGER.debug(
                    "%s (%s): skipping update (%s)",
                    self.config_entry.title,
                    self.config_entry.entry_id,
                    err.reason,
                )
            else:
                _LOGGER.debug(
                    "%s (%s): final data after update %s",
                    self.config_entry.title,
                    self.config_entry.entry_id,
                    self.update,
                )

        self._recalc_default_typed_movement_data()
        self._notify_dependent_trigger_entities()
        self._add_statistics_post_update()
        self._schedule_reset_event()
        self._schedule_statistics_update()
        self._schedule_updates_stalled_event_post_update()

        # this event is only for users who with to use it to help debug
        # the internals of the integration. it's not public facing/stable nor
        # is it tested.
        self.hass.bus.async_fire(
            "movement._change",
            {
                "config_entry_id": self.config_entry.entry_id,
                "tracked_entity": self.tracked_entity,
                "change_type": type(self.change).__name__,
                "change": _serialize(self.change),
                "update": {
                    **self.update.as_dict(),
                    "history": [item.as_dict() for item in self.history.items],
                },
            },
        )

        self.change = None

        return self.update

    def _add_statistics_post_update(self) -> None:
        """Add necessary values to all statistics objects.

        This must be done post-update when `self.update` has been set.
        """
        update = self.update
        now_timestamp = time.time()

        if update.change_count >= 0 and (update.change_count != self.data.change_count):
            self.statistics.update_rate.add_state(update.change_count, now_timestamp)

        if update.speed and (update.speed != self.data.speed):
            self.statistics.speed_recent_avg.add_state(update.speed, now_timestamp)
            self.statistics.speed_recent_max.add_state(update.speed, now_timestamp)

    def _schedule_reset_event(self) -> None:
        """Ensure scheduling is in place for restting at midnight."""
        if not self._reset_listener:
            next_midnight = dt_util.start_of_local_day(
                dt_util.now() + dt.timedelta(days=1),
            )
            self._reset_listener = evt.async_track_point_in_time(
                self.hass,
                self._async_perform_reset,
                next_midnight,
            )

    def _schedule_statistics_update(self) -> None:
        """Reschedule when the next statistics update will occur.

        Recalculation is based on the current state of statistics objects. This
        method _does not_ update the statistics. The caller must do so before
        invoking this method.
        """
        timestamps = [
            purge_timestamp
            for statistic in self.statistics
            if (purge_timestamp := statistic.next_to_purge_timestamp())
        ]

        if timestamps:
            utc_time = dt_util.utc_from_timestamp(min(timestamps))
            _LOGGER.debug(
                "%s (%s): scheduling statistics update at %s",
                self.config_entry.title,
                self.config_entry.entry_id,
                utc_time,
            )
            self._async_cancel_statistics_update_listener()
            self._statistics_update_listener = evt.async_track_point_in_utc_time(
                self.hass,
                self._async_handle_statistics_update,
                utc_time,
            )

    def _schedule_updates_stalled_event_post_update(self) -> None:
        """Ensure scheduling is in place for handling stalled updates.

        This must be done post-update when `self.update` has been set.
        """
        update = self.update
        data = self.data

        assert update is not None
        assert data is not None

        # the speed is valid until 20 minutes from either:
        #
        # - the time an update was last performed (that actually added distance
        #   and the update_rate statstitic)
        # - the time that a transition began
        #
        # changes made that maintain a previous transition state are not
        # applicable, the speed will continue to be valid from the time the
        # transition started.
        is_distance_added = update.distance > data.distance
        is_transition_starting = len(self.transition.items or []) == 1
        is_transition_continuing = len(self.transition.items or []) > max(
            1,
            len(self.transition.prior or []),
        )
        is_applicable_change = not is_transition_continuing
        should_reschedule = is_applicable_change and (
            is_distance_added or is_transition_starting
        )

        if should_reschedule or not self._updates_stalled_listener:
            self._async_cancel_updates_stalled_listener()
            self._updates_stalled_listener = evt.async_call_later(
                self.hass,
                UPDATES_STALLED_DELTA.total_seconds(),
                self._async_handle_updates_stalled,
            )

    def _internal_recalc(
        self,
    ) -> None:
        """Perform internal recalculation (main entrypoint).

        This controls the sequence of events that needs to happen to calculate
        all of the values that need to be populated in an update. It expects
        that `self.data` & `self.update` have been created prior to being called
        and that all statistics were previously updated.

        Raises:
            SkipUpdateCondition: When the update should be skipped.
        """
        update = self.update
        data = self.data

        assert update is not None
        assert data is not None

        transitioning = False

        if isinstance(self.change, StateChangedData):
            try:
                self.history.add_entry_from_state_change(
                    self.change,
                    unworkable=partial(_raise, SkipUpdateCondition),
                )
            except SkipUpdateCondition as err:
                _LOGGER.log(
                    _TRACE,
                    "updated history, but skipping update (%s): %s",
                    err.reason,
                    self.history.items,
                )
                raise
            else:
                _LOGGER.log(_TRACE, "updated history: %s", self.history.items)

            calculate_distance(
                update=self.update,
                history=self.history,
            )

            try:
                calculate_speed(
                    prior=self.data,
                    update=self.update,
                    history=self.history,
                )
            except TransitionRequiredCondition as err:
                _LOGGER.log(
                    _TRACE,
                    "updated speed, but will enter/continue transition state (%s): %s",
                    err.reason,
                    update.speed,
                )
                transitioning = True

        # calculate mode of transit
        proposed_mode = (
            mode_of_transit_from_speed(update.speed) if update.speed else None
        )
        try:
            update_or_maintain_mode(
                prior=self.data,
                update=self.update,
                statistics=self.statistics,
                transition=self.transition,
                proposed_mode=proposed_mode,
            )
        except TransitionRequiredCondition as err:
            _LOGGER.log(
                _TRACE,
                "updated mode of transit, but will enter/continue transition state (%s): %s",
                err.reason,
                update.mode_of_transit,
            )
            transitioning = True

        _LOGGER.debug("proposed_mode: %s", proposed_mode)
        _LOGGER.debug("mode: %s", update.mode_of_transit)

        # handle per-person customizations to distance traveled
        update.adjustments = calculate_distance_adjustments(
            distance=update.distance,
            speed=update.speed,
            mode_of_transit=update.mode_of_transit,
            prior_mode_of_transit=data.mode_of_transit,
            transitioning=transitioning,
            config_entry=self.config_entry,
        )
        _LOGGER.debug("calculated adjustments: %s", update.adjustments)

        # set values from manual distance adjustment after all other calculations so
        # the manual data doesn't affect those calculations. the speed is set to
        # zero to prevent the mode from being cleared later & also as a way of
        # indicating that this was done manually.
        if isinstance(self.change, ServiceAdjustment):
            update.distance = self.change.distance
            update.adjustments = self.change.adjustments
            update.mode_of_transit = self.change.mode_of_transit
            update.speed = 0
            update.change_count = 0
            update.ignore_count = 0

        # store updates for transition when speed can't be calculated & add
        # finalized adjustments once they can be calculated
        update.adjustments = self.transition.process_update(
            update=self.update,
            transitioning=transitioning,
        )

        # calculate total_increasing based state/attributes after calculating final
        # distance, but this may be cleared later.
        total_distance = (data.distance) + update.distance + update.adjustments
        total_adjustments = (data.adjustments) + update.adjustments

        # handle reset for the start of a new day.
        if isinstance(self.change, ResetRequest):
            total_distance = 0
            total_adjustments = 0
            update.speed = None
            update.ignore_count = 0
            self.transition.reset(None)

        # handle reset for when updates stall.
        if isinstance(self.change, UpdatesStalledIndicator):
            update.speed = None
            self.transition.reset(None)

        # bind mode reset to any speed resets that have occurred.
        update.mode_of_transit = (
            None if update.speed is None else update.mode_of_transit
        )

        # update a few items in the final data now
        update.adjustments = total_adjustments
        update.distance = total_distance

        # increment change count if it's about to change
        if update.distance != data.distance:
            update.change_count = max(update.change_count, 0) + 1

    def _recalc_default_typed_movement_data(self) -> None:
        """Recalculation for walking, biking, and driving sensor data.

        This should be called after the main recalculation is complete.
        """
        reset = isinstance(self.change, ResetRequest)

        class SharedKwargs(TypedDict):
            entity_id: str
            reset: bool
            prior: MovementData
            update: MovementData
            transition: TransitionRegistry

        shared_kwargs: SharedKwargs = {
            "entity_id": "",
            "reset": reset,
            "prior": self.data,
            "update": self.update,
            "transition": self.transition,
        }

        self.walking_movement_data = get_updates_for_typed_movement_sensor(
            type_data=self.walking_movement_data,
            mode_type=ModeOfTransit.WALKING,
            **shared_kwargs,
        )
        self.biking_movement_data = get_updates_for_typed_movement_sensor(
            type_data=self.biking_movement_data,
            mode_type=ModeOfTransit.BIKING,
            **shared_kwargs,
        )
        self.driving_movement_data = get_updates_for_typed_movement_sensor(
            type_data=self.driving_movement_data,
            mode_type=ModeOfTransit.DRIVING,
            **shared_kwargs,
        )

    def _notify_dependent_trigger_entities(self) -> None:
        reset = isinstance(self.change, ResetRequest)

        for entity_id in self.dependent_entities:
            try:
                type_data, mode_type = (
                    self._get_dependent_trigger_entity_config_from_state(entity_id)
                )
                event_data = get_updates_for_typed_movement_sensor(
                    entity_id=entity_id,
                    type_data=type_data,
                    mode_type=mode_type,
                    reset=reset,
                    prior=self.data,
                    update=self.update,
                    transition=self.transition,
                ).as_state_dict()

                from_dict = self.data.as_dict()
                from_distance = from_dict.pop("distance", 0)
                from_state = {"state": from_distance, "attributes": from_dict}
                to_dict = self.update.as_dict()
                to_distance = to_dict.pop("distance", 0)
                to_state = {"state": to_distance, "attributes": to_dict}

                self.hass.bus.async_fire(
                    "movement.template_entity_should_apply_update",
                    {
                        "entity_id": entity_id,
                        "config_entry_id": self.config_entry.entry_id,
                        "reason": "reset" if reset else "update",
                        "from_state": from_state,
                        "to_state": to_state,
                        "_for": slugify(
                            re.sub(r"([A-Z]+)", r" \1", type(self.change).__name__),
                        ),
                        "updates": event_data,
                    },
                )
            except EntityMissingError:
                _LOGGER.warning(
                    "%s (%s) could not notify dependent entity %s because it could not be found",
                    self.config_entry.title,
                    self.config_entry.entry_id,
                    entity_id,
                )

    def _get_dependent_trigger_entity_config_from_state(
        self,
        entity_id: str,
    ) -> tuple[TypedMovementData, ModeOfTransit]:
        """Get dependent trigger entity config.

        The result is the state as TypedMovementData and mode type data.

        Returns:
            The typed movement data & mode of transit.

        Raises:
            EntityMissingError: If the entity cannot be found.
            MisconfigurationError: If the entity is missing a mode type
                attribute.
        """
        if not (state := self.hass.states.get(entity_id)):
            raise EntityMissingError(entity_id)

        distance = (
            float(state.state) if state.state not in {"unknown", "undefined"} else 0
        )
        attributes = dict(state.attributes) if state else {}
        type_data = TypedMovementData.from_dict({"distance": distance, **attributes})
        mode_type = attributes.pop("mode_type", None)

        _LOGGER.debug("mode type found from sensor attributes %s", mode_type)

        if not mode_type:
            msg = f"Missing `mode_type` attribute on dependent template entity {entity_id}"
            raise MisconfigurationError(msg)

        return type_data, mode_type

    def _create_removed_tracked_entity_issue(self, entity_id: str) -> None:
        """Create a repair issue for a removed tracked entity."""
        async_create_issue(
            self.hass,
            DOMAIN,
            f"tracked_entity_removed_{entity_id}",
            is_fixable=True,
            is_persistent=True,
            severity=IssueSeverity.WARNING,
            translation_key="tracked_entity_removed",
            translation_placeholders={
                "entity_id": entity_id,
                "name": self.name,
            },
        )


def _serialize(data: Any) -> Any:  # noqa: ANN401
    if is_dataclass(type(data)):
        data = {
            field.name: _serialize(getattr(data, field.name)) for field in fields(data)
        }
    elif hasattr(data, "as_dict") and callable(data.as_dict):
        data = _serialize(data.as_dict())
    return data


def _raise(
    exception: type[Exception],
    *args,  # noqa: ANN002
    **kwargs,  # noqa: ANN003
) -> NoReturn:
    raise exception(*args, **kwargs)
