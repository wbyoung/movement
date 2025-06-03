"""Calculation functions."""

import datetime as dt
import logging
import math

from homeassistant.util import dt as dt_util

from .const import (
    CONF_HIGHWAY,
    CONF_LOCAL,
    CONF_MULTIPLIERS,
    CONF_NEIGHBORHOOD,
    CONF_TRIP_ADDITION,
    HISTORY_EXPIRATION_DELTA,
    SPEED_USABLE_DELTA,
    UPDATES_STALLED_DELTA,
)
from .history import HistoryRegistry
from .transition import TransitionRegistry
from .types import (
    ABSENT_NONE,
    AbsentNone,
    HistoryEntry,
    Location,
    ModeOfTransit,
    MovementConfigEntry,
    MovementData,
    ResetRequest,
    ServiceAdjustment,
    SpeedStaleIndicator,
    StateChangedData,
    StatisticGroup,
    TransitionRequiredCondition,
    TypedMovementData,
    UpdatesStalledIndicator,
)

type ChangeType = (
    ResetRequest
    | ServiceAdjustment
    | SpeedStaleIndicator
    | StateChangedData
    | UpdatesStalledIndicator
    | None
)


SPEED_STALE_DELTA = UPDATES_STALLED_DELTA
DISTANCE_THRESHOLDS_BEFORE_MODE_CHANGE = {
    "walking": 0.0,
    "biking": 1.0,
    "driving": 0.0,
}


_LOGGER = logging.getLogger(__name__)
_TRACE = 5


def calculate_distance(
    *,
    update: MovementData,
    history: HistoryRegistry,
) -> None:
    """Calculate the distance moved for an update.

    Args:
        update: The update into which calculated update values are stored. Note
            that distance set by this function is only the current distance
            traveled and not the cumulative/total distance traveled.
        history: The history containing information about prior locations. The
            distance from `prior_entry.location` to `current_entry.location`
            will be calculated.
    """
    assert update is not None

    _LOGGER.log(_TRACE, "calculate_distance")

    to_location = history.current_entry.location
    from_location = history.prior_entry.location

    # from_location has to have a value because the registry filtered to a
    # usable set of items when it had a new item added & updated everything.
    # if it hadn't been set, this update would have been skipped.
    assert from_location, (
        "history.prior_entry.location must have been set during history update"
    )

    # make calculations for distance
    _LOGGER.debug("calculating from: %s -> %s", from_location, to_location)
    assert not isinstance(from_location, AbsentNone)
    assert not isinstance(to_location, AbsentNone)
    distance = haversine(from_location, to_location)

    _LOGGER.debug("distance: %s", distance)

    # final assignment of all output information
    update.distance = distance


def calculate_speed(  # noqa: PLR0914
    *,
    prior: MovementData,
    update: MovementData,
    history: HistoryRegistry,
) -> None:
    """Calculate speed while considering various factors.

    Args:
        prior: The state of data prior to what's currently being calculated.
        update: The update into which calculated update values are stored.
        history: The history containing information about prior locations.

    Raises:
        TransitionRequiredCondition: If updates have stalled or if GPS accuracy
            is poor.

    #### Consideration #1

    Sometimes updates will stall and it's not really possible to know how
    quickly the person is traveling. In this case, speed is not calculated and
    `TransitionRequiredCondition` will be raised.  (In this case, the current
    speed of `None` is maintained.) It is the responsibility of the caller to
    handle this condition (likely by setting a `transitioning` flag & passing
    that off to `TransitionRegistry.process_update`). The distance traveled
    should be stored for later use once speed can be calculated (i.e.
    calculation of adjustments).

    This can also occur for considerations #2 & #3 below. The
    `TransitionRequiredCondition` exception will be raised in these cases as
    well. The difference in those cases is that the previously calculated
    `speed`, the value stored in `data.speed`/`update.speed`, will have a value
    and the current speed and `mode_of_transit` can be maintained at those
    previous values while the transition occurs.

    #### Consideration #2

    Sometimes updates will arrive after some delay and could end up clustered
    together. For example, if you walk through a mobile data dead zone, you
    could walk 50 meters in 45 seconds, with a location update detetected by the
    app at the start and the end of this interval. If, however, the app attempts
    to send an update & it doesn't timeout, both updates could end up reaching
    the Home Assistant server within seconds (or less). 50 m/s is 180 km/h which
    is quite fast. Using an older value from the history makes for a bit more
    sane speed calculation. This will look at entries up to an hour old
    (`HISTORY_EXPIRATION_DELTA`).

    This can also result in the rasising of `TransitionRequiredCondition`. See
    consideration #1.

    #### Consideration #3

    The third consideration is to avoid calculating speed based on changes in
    distance that are mostly due to inaccuracy of GPS location.

    Sometimes updates will be coming in with decent accuracy, then the accuracy
    will drop with subsequent updates. If someone is stationary and poor
    accuracy results in an update with a location that's 50 meters away within
    10 seconds of the last update, the naive calculation has them at 18km/hr.
    This means a stationary person can go from `walking` to `biking` or
    `driving`. Obviously, these somewhat inaccurate updates can't be ignored
    completely or it won't be possible to determine speed & mode of transit at
    all in many cases.

    The solution used here is to search back through the location history
    and find the first entry where the movement from that location to the
    current location exceeds the sum of their accuracies. When searching due
    to inaccurate GPS, the search only goes back 20 minutes
    (`SPEED_STALE_DELTA`) instead of through the full history to avoid choosing
    a value with great accuracy that's from long enough ago that it's also part
    of a different mode of transit. If nothing is found, it does not calculate a
    speed & indicates that it should be considered in transition until more
    updates occur.

    This may mean looking back relatively far in time to calculate speed, but
    it's likely that while driving & GPS updates flowing because a device is
    using mapping software or connected to an infotainment system, the distance
    changes are large enough to overcome the GPS inaccuracy easily because GPS
    accuracy is usually within 200m.

    This can also result in the rasising of `TransitionRequiredCondition`. See
    consideration #1.

    #### Consideration #4

    Large jumps in distance are possible when the phone is not sending updates
    for a period of time. These changes could be because the phone is off, in
    airplane mode, or just doesn't have signal. The case of getting off of an
    airplane is being handled by not setting a speed (and mode of transit). High
    speed, distance, and a long delay can catch this case.
    """
    assert prior is not None
    assert update is not None

    _LOGGER.debug("_calculate_speed")

    distance = update.distance
    location = history.current_entry.location
    accuracy = history.current_entry.accuracy

    # see consideration #1 above
    current_time = dt_util.utcnow()
    delta = current_time - history.prior_entry.at
    has_stalled = prior.mode_of_transit is None and delta > HISTORY_EXPIRATION_DELTA

    # see considerations #2 & #3 above
    accuracy_preventing_calculation = False
    matched_pair: tuple[float, dt.timedelta] | None = None  # distance, delta
    still_acceptable_movement = True
    for index, entry in enumerate(history.prior):
        assert not isinstance(entry.location, AbsentNone)
        assert not isinstance(location, AbsentNone)

        delta = current_time - entry.at
        distance = haversine(entry.location, location)
        distance_in_meters = distance * 1000
        accuracy_combined = accuracy + entry.accuracy
        accuracy_combined = (
            accuracy_combined
            if accuracy_combined < HistoryEntry.NO_ACCURACY
            else distance_in_meters
        )
        acceptable_movement = distance_in_meters >= accuracy_combined
        still_acceptable_movement = still_acceptable_movement and acceptable_movement

        delta_min = SPEED_USABLE_DELTA
        delta_max = (
            HISTORY_EXPIRATION_DELTA if still_acceptable_movement else SPEED_STALE_DELTA
        )
        acceptable_time_lapsed = delta >= delta_min and delta < delta_max

        _LOGGER.debug(
            "\n"
            "  [%s]\n"
            "    delta: %s\n"
            "    distance_in_meters: %s\n"
            "    accuracy_combined: %s\n"
            "    acceptable_movement: %s\n"
            "    acceptable_time_lapsed: %s",
            index,
            delta,
            distance_in_meters,
            accuracy_combined,
            acceptable_movement,
            acceptable_time_lapsed,
        )

        if acceptable_time_lapsed and acceptable_movement:
            matched_pair = (distance, delta)
            break

    if matched_pair is not None:
        distance, delta = matched_pair
    else:
        accuracy_preventing_calculation = True

    speed = distance / delta.total_seconds() * 3600

    _LOGGER.debug("  calculated speed: %s", speed)

    # see consideration #4 above
    clear_speed_related_attrs = (
        speed > 200 and distance > 250 and delta > dt.timedelta(minutes=60)
    )

    # final assignment of all output information
    if clear_speed_related_attrs:
        update.speed = None
    else:
        if has_stalled:
            raise TransitionRequiredCondition("stalled")
        if accuracy_preventing_calculation:
            raise TransitionRequiredCondition("poor_gps_accuracy")
        update.speed = speed


def update_or_maintain_mode(
    *,
    prior: MovementData,
    update: MovementData,
    statistics: StatisticGroup,
    transition: TransitionRegistry,
    proposed_mode: ModeOfTransit | None,
) -> None:
    """Update the mode of transit if shouldn't be maintained at the prior value.

    It will be maintained in two cases, discussed in more detail below:

    - The prior mode may be constrained based on the recent combined speed
    - Transition to a new mode may be dependent on reaching a cretain distance
        threshold before establishing the mode

    #### Constraint Based on Recent Combined Max Speed

    There are a few possibilities to consider with respect to the prior mode
    of transit (`prior.mode_of_transit`), the proposed mode (the newly
    calculated mode given via `proposed_mode`), and the constraint mode
    calculated within this method (based on the recent combined max speed):

    1. No prior mode: the mode should not be maintained. There's no reason to
       maintain an unknown value.
    2. No proposed mode: the mode should be maintained. There's no reason to
       switch to an unknown value. (This should only happen when recalculating
       the mode of transit, but the generalization here is be fine.)
    3. Proposed mode is greater than or equal to the prior mode: the mode
       should not be maintained. Switching to a faster mode of transit should
       always occur when it's due to the newly calculated speed being faster
       than it was before. (Switching to the same mode is no real change at
       all & maintaining that doesn't really matter.)
    4. Proposed mode is less than the prior mode: the prior mode of transit
       may need to be maintained. If the constraint mode is greater than or
       equal to the prior mode, then the mode of transit should be maintained
       at the prior value.

    In the last case above, an example is helpful. A person who has been driving
    may stop for a while at a traffic light. In this case, their recent combined
    max speed will remain high, and the mode calculated from it will remain
    `driving` for a period of time. Their actual speed may drop down to walking
    pace, though. The prior mode of transit needs needs to be maintained. In
    this case, the calculated constraint mode is `driving` and since it is
    greater than or equal to the prior mode of transit, the function returns
    `True` to indicate that the mode should remain at its prior value.

    The above scenario also should be considered for someone who is biking and
    comes to a temporary stop. They should not be considered to now be walking
    (until the recent combined max speed values decrease to walking pace).

    Note: it is also possible for the mode of transit constraint that's
    calculated from the recent combined max speed to be higher than the prior
    mode of transit. For instance, when driving, eventually the average speeds
    will come down low enough that the mode of transit no longer needs to be
    maintained. In this case, someone who was `driving` may be change to
    `walking` because their prior speed is slow enough. But their average
    speed may still be in the `biking` range. While not a part of this
    functions's logic, it's important that this be considered. The mode of
    transit constraint should only used as a constraint, not a value to use for
    the mode of transit. If used, another update after the person moved from
    `driving` to `walking` could change them to `biking` with another small
    walking speed distance change which doesn't make sense.

    #### Transition When Distance Thresholds Are Defined

    Distance thresholds can be configured for any mode in
    `DISTANCE_THRESHOLDS_BEFORE_MODE_CHANGE`, and the distance changes will be
    put into `transition` until that distance is reached (or a new update
    selects a different mode).

    Args:
        prior: The state of data prior to what's currently being calculated.
        update: The update into which calculated update values are stored.
        statistics: The statistics containing recent speed details.
        transition: The transition containing information about updates that
            could not be processed immediately.
        proposed_mode: Proposed (newly calculated) mode of transit

    Raises:
        TransitionRequiredCondition: If the prior mode of transit should be
            maintaied.
    """
    assert prior is not None
    assert update is not None

    maintain = False
    distance = update.distance
    speed = update.speed
    mode = update.mode_of_transit
    prior_mode = prior.mode_of_transit

    if not prior_mode:
        maintain = False
    elif not proposed_mode:
        maintain = True
    else:
        speed_recent_combined_max = max(
            default_0(speed),
            default_0(statistics.speed_recent_avg.value),
            default_0(statistics.speed_recent_max.value),
        )
        constraint_mode = mode_of_transit_from_speed(speed_recent_combined_max)

        _LOGGER.debug("constraint_mode: %s", constraint_mode)

        mode_levels = [
            ModeOfTransit.WALKING,
            ModeOfTransit.BIKING,
            ModeOfTransit.DRIVING,
        ]
        prior_mode_level = mode_levels.index(prior_mode)
        proposed_mode_level = mode_levels.index(proposed_mode)
        constraint_mode_level = mode_levels.index(constraint_mode)

        if proposed_mode_level >= prior_mode_level:
            maintain = False
        else:
            maintain = constraint_mode_level >= prior_mode_level

    # check that distance threshold has been met when mode is changing
    if not maintain and proposed_mode != prior_mode:
        transition_distances = sum(item.distance for item in transition.items or [])
        threshold = (
            DISTANCE_THRESHOLDS_BEFORE_MODE_CHANGE.get(str(proposed_mode), 0)
            if proposed_mode is not None
            else 0
        )
        maintain = distance + transition_distances < threshold

        _LOGGER.debug("constraining transition to %s: %s", proposed_mode, maintain)

        if maintain:
            msg = f"maintain mode: {mode}"
            raise TransitionRequiredCondition(msg)

    if not maintain:
        mode = proposed_mode

    # final assignment of all output information
    update.mode_of_transit = mode


def calculate_distance_adjustments(
    *,
    distance: float,
    speed: float | None,
    mode_of_transit: ModeOfTransit | None,
    prior_mode_of_transit: ModeOfTransit | None,
    transitioning: bool,
    config_entry: MovementConfigEntry,
) -> float:
    """Calculate per-person customizations to driving distance.

    Args:
        distance: The change in distance for the current update.
        speed: The speed for the current update.
        mode_of_transit: The mode of transit for the current update.
        prior_mode_of_transit: The mode of transit prior to this update.
        transitioning: Used to indicate that the current update is considered
            to be in transition.
        config_entry: The config entry containing the user's settings.

    Returns:
        The distance adjustments.
    """
    mode = mode_of_transit
    distance_adjustments = 0

    if not transitioning and mode == ModeOfTransit.DRIVING:
        settings = config_entry.data
        trip_start = prior_mode_of_transit != ModeOfTransit.DRIVING
        trip_addition = settings.get(CONF_TRIP_ADDITION, 0)
        road_type = (
            CONF_HIGHWAY
            if (default_0(speed)) >= 85
            else CONF_NEIGHBORHOOD
            if (default_0(speed)) < 40
            else CONF_LOCAL
        )
        multipliers = settings.get(CONF_MULTIPLIERS, {})
        multiplier = multipliers.get(road_type, 1)
        distance_adjustments = (distance * multiplier - distance) + (
            trip_addition if trip_start else 0
        )

    return distance_adjustments


def mode_of_transit_from_speed(speed: float) -> ModeOfTransit:
    """Calculate mode of transit from speed.

    The following information is informative in making a judgment about speed
    thresholds:

    - Brisk walking pace 5.6-6.4 km/h
    - Fast walking pace 6.4-8 km/h
    - Commuter biking can top out at about 16 km/hr

    Returns:
        The mode of transit.
    """
    return (
        ModeOfTransit.DRIVING
        if speed >= 16
        else ModeOfTransit.BIKING
        if speed >= 8
        else ModeOfTransit.WALKING
    )


def get_updates_for_typed_movement_sensor(
    *,
    entity_id: str,
    type_data: TypedMovementData,
    mode_type: ModeOfTransit,
    reset: bool = False,
    prior: MovementData | None,  # can only be none for reset
    update: MovementData | None,  # can only be none for reset
    transition: TransitionRegistry,
) -> TypedMovementData:
    """Get updates for a typed movement sensor, i.e. distance walking.

    This is also used for dependent template entities.

    Returns:
        The typed movement data.
    """
    _LOGGER.debug(
        "_typed_distance calculation for `%s` on %s (%s)",
        "reset" if reset else "update",
        entity_id or "internal",
        mode_type or "mode type pending",
    )

    if reset:
        return TypedMovementData(
            distance=0,
            trip_start=None,
            trip_distance=None,
            trip_adjustments=None,
        )

    assert prior is not None
    assert update is not None

    if update.distance == 0:
        return type_data

    distance = type_data.distance
    trip_start = type_data.trip_start
    total_trip_distance = type_data.trip_distance or 0
    total_trip_distance_adjustments = type_data.trip_adjustments or 0

    from_mode = prior.mode_of_transit
    to_mode = update.mode_of_transit
    modes = [from_mode, to_mode]
    in_transition = (
        len(
            [
                item
                for item in (transition.items or [])
                if item.adjustments == ABSENT_NONE
            ],
        )
        > 0
    )
    stalled_from_in_transition = (
        transition.prior is not None
        and transition.items is None
        and update.speed is None
        and to_mode is None
    )

    contributes_to = {
        ModeOfTransit.WALKING: (
            (ModeOfTransit.WALKING in modes or stalled_from_in_transition)
            and (ModeOfTransit.BIKING not in modes)
            and (ModeOfTransit.DRIVING not in modes)
        ),
        ModeOfTransit.BIKING: (
            (ModeOfTransit.BIKING in modes) and (ModeOfTransit.DRIVING not in modes)
        ),
        ModeOfTransit.DRIVING: (ModeOfTransit.DRIVING in modes),
    }

    _LOGGER.debug("contributes_to: %s", contributes_to)

    contributes = contributes_to[mode_type]
    _LOGGER.debug("contributes: %s from %s", contributes, repr(mode_type))

    # count the distance traveled in transition (before being finalized).
    #
    # the objects in the transition registry that have `adjustments` set are
    # finalized.
    #
    # the sequence of events is:
    #
    #   - updates were stalled for a period of time. (there is another case
    #     where this doesn't happen first that is based on GPS accuracy.)
    #   - a location change came in to the `MovementUpdateCoordinator`.
    #   - the distance change got recorded immediately in the
    #     `MovementUpdateCoordinator` and on the
    #     `sensor.<person_name>_distance_traveled` sensor, but it couldn't
    #     calculate speed & mode of transit, so it stored the distance change
    #     in the transition registry. (this is the other case mentioned above -
    #     GPS accuracy could have prevented the speed & mode of transit
    #     calculation and speed & mode of transit will just be held at their
    #     current values in this case.)
    #   - another location change came in to the `MovementUpdateCoordinator` &
    #     the speed and mode of transit got calculated.
    #   - the coordinator updated the transition registry to include the
    #     `adjustments`, finalizing them, now that the mode of transit is known.
    #     the `adjustments` calculated during this update for each transition
    #     object are also included in their individual `distance` values as well
    #     as in the `sensor.<person_name>_distance_traveled` state total and
    #     adjustments total (hence why they will not be subtraced out here).
    #
    # at this point, the `adjustments` will be included automatically when
    # updating this mode of transit based sensor (without analyzing the
    # `transition` objects). but the original distance traveled will not have
    # been counted in any prior update because the mode of transit was not
    # known at that time.
    #
    # sum the `distance` from each of the finalized `transition` objects (those
    # with `adjustments` defined), but since that includes the `adjustments`
    # that were calculated now that the mode is known, they need to be
    # subtracted out to be left with the distance change that was recorded in
    # the coordinator and on the main sensor during the transition. this is
    # logically nearly identical to summing the `distance` values from the
    # entries in the prior entries of the transition registry, but better
    # protects from losing values over multiple state changes.
    #
    # note: do not re-add the `adjustments` anywhere.
    distance_from_transition = sum(
        item.distance
        for item in (transition.items or [])
        if item.adjustments != ABSENT_NONE
    ) - sum(
        item.adjustments
        for item in (transition.items or [])
        if item.adjustments != ABSENT_NONE
    )

    _LOGGER.debug("distance_from_transition: %s", distance_from_transition)

    # like above, but since a mode of transit was never calculated, these
    # transition objects will never be finalized. sum them from the prior
    # entries without regard to their finaized state before they're lost
    # forever.
    if stalled_from_in_transition:
        distance_from_transition += sum(
            item.distance for item in (transition.prior or [])
        )

    # distance traveled can go into transition state while maintaining speed &
    # mode of transit. see `calculate_speed` consideration #1.
    if in_transition:
        contributes = False

    applicable_distance = (
        update.distance - prior.distance + distance_from_transition
        if contributes
        else 0
    )
    applicable_distance_adjustments = (
        update.adjustments - prior.adjustments if contributes else 0
    )

    _LOGGER.debug("applicable_distance: %s", applicable_distance)
    _LOGGER.debug(
        "applicable_distance_adjustments: %s",
        applicable_distance_adjustments,
    )

    # if mode is changing to be the target type, then we need a trip reset
    if from_mode != mode_type and to_mode == mode_type:
        current_time = dt_util.utcnow()
        trip_start = current_time
        total_trip_distance = 0
        total_trip_distance_adjustments = 0

    _LOGGER.debug(
        "distance = distance (%s) + applicable_distance (%s)",
        distance,
        applicable_distance,
    )
    distance += applicable_distance
    total_trip_distance += applicable_distance
    total_trip_distance_adjustments += applicable_distance_adjustments

    return TypedMovementData(
        distance=distance,
        trip_start=trip_start,
        trip_distance=total_trip_distance,
        trip_adjustments=total_trip_distance_adjustments,
    )


def haversine(x: Location, y: Location) -> float:
    d_lat = (y.latitude - x.latitude) * math.pi / 180
    d_long = (y.longitude - x.longitude) * math.pi / 180
    a = (math.sin(d_lat / 2) * math.sin(d_lat / 2)) + (
        math.sin(d_long / 2)
        * math.sin(d_long / 2)
        * math.cos(x.latitude * math.pi / 180)
        * math.cos(y.latitude * math.pi / 180)
    )
    rad = 6371
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return rad * c


def default_0(value: float | None) -> float:
    return 0.0 if value is None else value
