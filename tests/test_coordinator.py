"""Test coordinator."""

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, fields
import datetime as dt
from typing import Any, cast
from unittest.mock import Mock, patch

from homeassistant.core import (
    EVENT_STATE_CHANGED,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

from custom_components.movement.calculations import (
    get_updates_for_typed_movement_sensor,
)
from custom_components.movement.const import (
    CONF_HIGHWAY,
    CONF_LOCAL,
    CONF_MULTIPLIERS,
    CONF_NEIGHBORHOOD,
    CONF_TRACKED_ENTITY,
    CONF_TRIP_ADDITION,
    DOMAIN,
)
from custom_components.movement.coordinator import MovementUpdateCoordinator
from custom_components.movement.statistics import Statistic
from custom_components.movement.transition import TransitionRegistry
from custom_components.movement.types import (
    ABSENT_FALSE,
    ABSENT_NONE,
    HistoryEntry,
    ModeOfTransit,
    MovementData,
    ServiceAdjustment,
    StatisticGroup,
    TransitionEntry,
)


async def test_data_calculation(
    hass: HomeAssistant,
    scenario_fixture: str,
    scenario: dict,
    snapshot: SnapshotAssertion,
) -> None:
    """Test sensors when tracked device changes state."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="mock-unique-id",
        data={
            CONF_TRACKED_ENTITY: "person.akio_toyoda",
            CONF_TRIP_ADDITION: "0",
            CONF_MULTIPLIERS: {
                CONF_NEIGHBORHOOD: "0",
                CONF_LOCAL: "0",
                CONF_HIGHWAY: "0",
                **scenario.get("config_entry", {}).get(CONF_MULTIPLIERS, {}),
            },
            **{
                key: value
                for key, value in scenario.get("config_entry", {}).items()
                if key != CONF_MULTIPLIERS
            },
        },
    )

    coordinator_config = scenario.get("coordinator", {})
    history = coordinator_config.pop("history", None) or []
    transition = coordinator_config.pop("transition", None)
    coordinator = MovementUpdateCoordinator(hass, mock_config_entry)
    coordinator.inject_data(
        MovementData.from_dict(coordinator_config),
        history=[*map(HistoryEntry.from_dict, history)],
        transition=(transition and [*map(TransitionEntry.from_dict, transition)]),
    )
    coordinator.statistics = StatisticGroup(
        **{field.name: Mock(spec=Statistic) for field in fields(StatisticGroup)}
    )

    for mock in coordinator.statistics:
        mock.value = None
        mock.next_to_purge_timestamp.return_value = None

    for key, value in coordinator_config.items():
        if key == "statistics":
            for sensor_key, sensor_value in value.items():
                mock = getattr(coordinator.statistics, sensor_key)
                mock.value = sensor_value
        if key == "last_changed":
            setattr(coordinator, "last_changed", dt_util.parse_datetime(value))

    change = scenario["change"]
    change_type = change["id"]
    data: Any | None = None
    expectation = scenario.get("result")
    result: dict | None = None

    if change_type == "add_distance":
        now = dt_util.parse_datetime(change["now"])
        from_state_last_change = dt_util.parse_datetime(
            scenario.get("coordinator", {}).get("last_changed")
        )
        from_state = change["from_state"]
        to_state = change["to_state"]

        # match the last change on the from state to what's used for the value
        # on the coordinator. these values are probably pretty interchangeable
        # (the value on the coordinator is based on when the distance last
        # changed, i.e. when the tracked entity changes). an effort should be
        # made in the future to refactor and choose which of these to use.
        # at the time of this writing, the value was only used as a fallback
        # for when no history was available on the coordinator anyway.
        if from_state_last_change:
            from_state["last_changed"] = from_state_last_change

        event = Event(
            EVENT_STATE_CHANGED,
            EventStateChangedData(
                entity_id="person.akio_toyoda",
                old_state=State(
                    "person.akio_toyoda", **({"state": "undefined"} | from_state)
                ),
                new_state=State(
                    "person.akio_toyoda", **({"state": "undefined"} | to_state)
                ),
            ),
        )

        with patch("homeassistant.util.dt.utcnow", return_value=now):
            await coordinator.async_handle_entity_state_change(event)
    elif change_type == "recalculate_mode_of_transit":
        await coordinator.async_refresh()
    elif change_type == "updates_stalled":
        await coordinator._async_handle_updates_stalled()
    elif change_type == "add_distance_manually":
        await coordinator.async_perform_service_adjustment(
            ServiceAdjustment(**change["data"])
        )
    elif change_type == "reset":
        await coordinator._async_perform_reset()
    elif change_type == "mode_type_sensor":
        now = dt_util.parse_datetime(change["now"])
        trigger = scenario["trigger"]
        reset = trigger.get("id") == "reset"

        if not reset:
            from_state = trigger["from_state"]
            to_state = trigger["to_state"]
            coordinator.data = _load_movement_data(from_state)
            coordinator.update = _load_movement_data(to_state)
            coordinator.transition = TransitionRegistry(
                coordinator.config_entry,
                _load_transitions(to_state.get("attributes", {})),
                _load_transitions(from_state.get("attributes", {})),
            )

        hass.states.async_set(
            "sensor.toyota_prius_distance",
            str(scenario["sensor_state"]["state"]),
            scenario["sensor_state"]["attributes"]
            | {
                "mode_type": scenario["sensor_type"],
            },
        )

        with patch("homeassistant.util.dt.utcnow", return_value=now):
            type_data, mode_type = (
                coordinator._get_dependent_trigger_entity_config_from_state(
                    "sensor.toyota_prius_distance"
                )
            )
            data = get_updates_for_typed_movement_sensor(
                entity_id="sensor.toyota_prius_distance",
                reset=reset,
                type_data=type_data,
                mode_type=mode_type,
                prior=coordinator.data,
                update=coordinator.update if not reset else None,
                transition=coordinator.transition,
            )

        result = data.as_state_dict()
    elif change_type == "_internal:speed_valid_util":
        # note: these tests cover some internal logic. the tests have been
        # preserved from when this was originally built using templates and
        # sensors rather than a custom integration. these were all scenarios for
        # an individual sensor for how long the speed would stay valid. it
        # triggered when the `distance_traveled` sensor changed to a non-zero
        # (and valid) value. they may be covered by broader tests in
        # `test_init.py` or `test_sensors.py`, but have been maintained
        # nonetheless.
        cancel_mock: Mock | None = None

        if scenario["additional_setup"] == "mock_cancel_callback":
            cancel_mock = Mock()
            coordinator._updates_stalled_listener = cast(Any, cancel_mock)

        with patch("homeassistant.helpers.event.async_call_later") as mock:
            coordinator.update = MovementData.from_dict(change["coordinator"])
            coordinator.transition = TransitionRegistry(
                coordinator.config_entry,
                _load_transitions(change["coordinator"]),
                coordinator.transition.items,
            )
            coordinator._schedule_updates_stalled_event_post_update()
        if cancel_mock:
            if expectation:
                cancel_mock.assert_called_once()
            else:
                cancel_mock.assert_not_called()

        result = {
            "async_call_later[].args[1]": [call.args[1] for call in mock.call_args_list]
        }
        expectation = (
            {"async_call_later[].args[1]": [expectation]}
            if expectation is not None
            else None
        )
    else:
        raise AssertionError(
            f"Scenario {scenario_fixture} defines unknown change type {change_type} for key `change.id`"
        )

    coordinator.cancel_all_listeners()

    if data is None and result is None:
        data = coordinator.data
        result = asdict(data)
        result.pop("change_count", None)  # not part of YAML files
        result["history"] = [item.as_dict() for item in coordinator.history.items]
        result["transition"] = (
            [item.as_dict() for item in coordinator.transition.items]
            if coordinator.transition.items is not None
            else None
        )

    if expectation:
        assert _to_yaml_assertable(result) == expectation

    if data:
        assert data == snapshot(
            name="data",
            matcher=_round_floats_matcher,
        )

    if data == coordinator.data:
        assert coordinator.history.items == snapshot(
            name="history",
            matcher=_round_floats_matcher,
        )

        assert coordinator.transition.items == snapshot(
            name="transition",
            matcher=_round_floats_matcher,
        )


_round_floats_matcher = path_type(
    types=(float,), replacer=lambda data, _: round(data, 5)
)


def _to_yaml_assertable(value: Any, preserve_keys=["location"]):
    if isinstance(value, bool):
        return value
    elif isinstance(value, (int, float)):
        if value == HistoryEntry.NO_ACCURACY:
            value = 1e99
        return round(value, 3)
    elif isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    elif isinstance(value, Mapping):
        return {
            key: (
                sub_value
                if key in preserve_keys
                else _to_yaml_assertable(sub_value, preserve_keys)
            )
            for key, sub_value in value.items()
            if sub_value not in (ABSENT_FALSE, ABSENT_NONE)
        }
    elif isinstance(value, (list, tuple)):
        return [_to_yaml_assertable(item, preserve_keys) for item in value]
    elif isinstance(value, str):
        with suppress(ValueError):
            int_value = int(value)
            if str(int_value) == value:
                return int_value
        with suppress(ValueError):
            float_value = float(value)
            if str(float_value) == value:
                return round(float_value, 3)
        return value
    else:
        return value


def _load_movement_data(data: dict[str, Any]) -> MovementData:
    state = data.get("state", "0")
    attrs = data.get("attributes", {})
    return MovementData(
        distance=float(state),
        adjustments=attrs.get("adjustments", 0),
        speed=attrs.get("speed"),
        mode_of_transit=cast(ModeOfTransit, attrs.get("mode_of_transit")),
        change_count=0,
        ignore_count=attrs.get("ignore_count", 0),
    )


def _load_transitions(attrs: dict[str, Any]) -> list[TransitionEntry] | None:
    transition = attrs.get("transition")
    return transition and [TransitionEntry.from_dict(item) for item in transition]
