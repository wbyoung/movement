"""Test sensors."""

import datetime as dt
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.restore_state import STORAGE_KEY as RESTORE_STATE_KEY
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_restore_state_shutdown_restart,
    mock_restore_cache_with_extra_data,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.movement.const import DOMAIN
from custom_components.movement.types import (
    ABSENT_NONE,
    HistoryEntry,
    Location,
    ModeOfTransit,
    MovementData,
    TransitionEntry,
    TypedMovementData,
)

from . import MockNow, setup_integration


@pytest.mark.parametrize(
    ("changes",),
    [
        ([(96.592, {"latitude": 35.053, "longitude": 137.144, "gps_accuracy": 15})],),
        (
            [
                (53.564, {"latitude": 35.053, "longitude": 137.144, "gps_accuracy": 4}),
                (0, {"latitude": 35.052, "longitude": 137.145, "gps_accuracy": 2}),
                (0, {"latitude": 35.051, "longitude": 137.146, "gps_accuracy": 3}),
            ],
        ),
    ],
    ids=["single_change", "multiple_change_in_one_tick"],
)
async def test_change_on_tracked_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_now: MockNow,
    snapshot: SnapshotAssertion,
    changes: list[tuple[float, dict[str, Any] | None]],
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test sensors when tracked device changes state."""

    initial_attrs = {
        "friendly_name": "Akio Toyoda",
        "latitude": 35.054,
        "longitude": 137.143,
        "gps_accuracy": 5,
    }

    hass.states.async_set(
        "person.akio_toyoda",
        "not_home",
        initial_attrs,
    )

    await setup_integration(hass, mock_config_entry)

    for tick, change_attrs in changes:
        if tick:
            mock_now._tick(tick)

        if change_attrs:
            hass.states.async_set(
                "person.akio_toyoda",
                "not_home",
                initial_attrs | change_attrs,
            )

        await hass.async_block_till_done()

    device_id = mock_config_entry.entry_id
    device = device_registry.async_get_device({(DOMAIN, device_id)})

    assert device is not None
    assert device == snapshot(name="device")

    entities = entity_registry.entities.get_entries_for_device_id(device.id)
    assert entities == snapshot(name="entities")

    for entity in entities:
        assert hass.states.get(entity.entity_id) == snapshot(name=entity.entity_id)


RESTORE_STATE_PARAMETRIZE_ARGS = [
    ("entity_id", "data", "history", "transition", "attr", "expected_state"),
    [
        (
            "sensor.mock_title_distance_traveled",
            MovementData(
                distance=4.56,
                adjustments=2.31,
                speed=11.3,
                mode_of_transit=ModeOfTransit.BIKING,
                change_count=4,
                ignore_count=2,
            ),
            [
                HistoryEntry(
                    at=dt.datetime(2025, 5, 20, 21, 21, 45, 3945),
                    location=Location(latitude=35.0539, longitude=137.1441),
                    accuracy=6,
                ),
                HistoryEntry(
                    at=dt.datetime(2025, 5, 20, 21, 21, 45, 3945),
                    location=Location(latitude=35.0539, longitude=137.1441),
                    accuracy=4,
                    debounce=True,
                ),
                HistoryEntry(
                    at=dt.datetime(2025, 5, 20, 21, 18, 15, 2384),
                    location=ABSENT_NONE,
                    accuracy=832,
                    ignore="inaccurate",
                ),
            ],
            [
                TransitionEntry(distance=0.35, adjustments=0.1),
                TransitionEntry(distance=0.25),
            ],
            "data",
            "4.56",
        ),
        (
            "sensor.mock_title_distance_walking",
            TypedMovementData(
                distance=3.21,
                trip_distance=1.1,
                trip_adjustments=0,
                trip_start=dt.datetime(2025, 5, 20, 21, 21, 59, 2134),
            ),
            None,
            None,
            "walking_movement_data",
            "3.21",
        ),
        (
            "sensor.mock_title_distance_biking",
            TypedMovementData(
                distance=6.26,
                trip_distance=2.1,
                trip_adjustments=None,
                trip_start=dt.datetime(2025, 5, 20, 21, 22, 11, 3991),
            ),
            None,
            None,
            "biking_movement_data",
            "6.26",
        ),
        (
            "sensor.mock_title_distance_driving",
            TypedMovementData(
                distance=15.22,
                trip_distance=14.84,
                trip_adjustments=3.21,
                trip_start=dt.datetime(2025, 5, 20, 21, 22, 41, 3984),
            ),
            None,
            None,
            "driving_movement_data",
            "15.22",
        ),
    ],
]
RESTORE_STATE_PARAMETRIZE_IDS = ["distance_traveled", "walking", "biking", "driving"]


@pytest.mark.parametrize(
    *RESTORE_STATE_PARAMETRIZE_ARGS,
    ids=RESTORE_STATE_PARAMETRIZE_IDS,
)
async def test_restore_sensor_save_state(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    mock_now: MockNow,
    snapshot: SnapshotAssertion,
    entity_id: str,
    data: Any,
    history: list[HistoryEntry],
    transition: list[TransitionEntry] | None,
    attr: str,
    expected_state: str,
) -> None:
    """Test saving sensor/coordinator state."""

    await setup_integration(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.coordinator
    coordinator.inject_data(
        coordinator.data, history=history or [], transition=transition
    )
    setattr(coordinator, attr, data)

    await async_mock_restore_state_shutdown_restart(hass)  # trigger saving state

    stored_entity_data = [
        item["extra_data"]
        for item in hass_storage[RESTORE_STATE_KEY]["data"]
        if item["state"]["entity_id"] == entity_id
    ]

    expected_stored_data = data.as_dict()

    if history is not None:
        expected_stored_data["history"] = [item.as_dict() for item in history]

    if transition is not None:
        expected_stored_data["transition"] = [item.as_dict() for item in transition]

    assert stored_entity_data[0] == expected_stored_data
    assert stored_entity_data == snapshot


@pytest.mark.parametrize(
    *RESTORE_STATE_PARAMETRIZE_ARGS, ids=RESTORE_STATE_PARAMETRIZE_IDS
)
async def test_restore_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    entity_id: str,
    data: Any,
    history: list[HistoryEntry],
    transition: list[TransitionEntry] | None,
    attr: str,
    expected_state: str,
) -> None:
    """Test restoring sensor/coordinator state."""

    extra_stored_data = {}

    if history is not None:
        extra_stored_data["history"] = [item.as_dict() for item in history]

    if transition is not None:
        extra_stored_data["transition"] = [item.as_dict() for item in transition]

    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(
                    entity_id,
                    "mock-state",  # note: in reality, this would match the stored data
                ),
                data.as_dict() | extra_stored_data,
            ),
        ),
    )

    await setup_integration(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.coordinator
    state = hass.states.get(entity_id)
    assert state
    assert state.state == expected_state

    assert getattr(coordinator, attr) is not data
    assert getattr(coordinator, attr) == data
    assert getattr(coordinator, attr) == snapshot

    if history is not None:
        assert coordinator.history.items == snapshot(name="history")

    if transition is not None:
        assert coordinator.transition.items == snapshot(name="transition")
