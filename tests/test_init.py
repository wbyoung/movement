"""Test component setup."""

from typing import Any
from unittest.mock import Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.movement.const import (
    CONF_DEPENDENT_ENTITIES,
    CONF_TRACKED_ENTITY,
    DOMAIN,
)
from custom_components.movement.coordinator import (
    SPEED_MAXIMUM_STATISTIC_MAX_AGE,
    UPDATES_STALLED_DELTA,
)

from . import MockNow, setup_added_integration, setup_integration


async def test_async_setup(hass: HomeAssistant):
    """Test the component gets setup."""
    assert await async_setup_component(hass, DOMAIN, {}) is True


async def test_standard_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test all devices and entities in a standard setup."""

    await setup_integration(hass, mock_config_entry)

    device_id = mock_config_entry.entry_id
    device = device_registry.async_get_device({(DOMAIN, device_id)})

    assert device is not None
    assert device == snapshot(name="device")

    entities = entity_registry.entities.get_entries_for_device_id(device.id)
    assert entities == snapshot(name="entities")

    for entity in entities:
        assert hass.states.get(entity.entity_id) == snapshot(name=entity.entity_id)


async def test_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.data.get(DOMAIN)


async def test_unload_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert mock_config_entry.state is ConfigEntryState.LOADED

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=False,
    ):
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.FAILED_UNLOAD

    # manually cleanup since unload failed
    mock_config_entry.runtime_data.coordinator.cancel_all_listeners()


RESET_MESSAGE = "executing handler for daily midnight cycle reset"
STATISTICS_UPDATE_MESSAGE = "executing handler for scheduled statistics update"
SPEED_SENSORS_INVALID_MESSAGE = "speed sensor(s) became invalid"
UPDATES_STALLED_MESSAGE = "executing handler for updates having stalled"


@pytest.mark.parametrize(
    ("changes", "expected_logged", "expected_not_logged"),
    [
        (
            [(46.723, {"latitude": 35.052, "longitude": 137.145})],
            [],
            [
                RESET_MESSAGE,
                STATISTICS_UPDATE_MESSAGE,
                SPEED_SENSORS_INVALID_MESSAGE,
                UPDATES_STALLED_MESSAGE,
            ],
        ),
        (
            [
                (46.723, {"latitude": 35.052, "longitude": 137.145}),
                (53.821, {"latitude": 35.050, "longitude": 137.147}),
                (SPEED_MAXIMUM_STATISTIC_MAX_AGE.total_seconds() - 10, None),
            ],
            [STATISTICS_UPDATE_MESSAGE],
            [RESET_MESSAGE, SPEED_SENSORS_INVALID_MESSAGE, UPDATES_STALLED_MESSAGE],
        ),
        (
            [
                (46.723, {"latitude": 35.052, "longitude": 137.145}),
                (53.821, {"latitude": 35.050, "longitude": 137.147}),
                (SPEED_MAXIMUM_STATISTIC_MAX_AGE.total_seconds() + 10, None),
            ],
            [STATISTICS_UPDATE_MESSAGE, SPEED_SENSORS_INVALID_MESSAGE],
            [RESET_MESSAGE, UPDATES_STALLED_MESSAGE],
        ),
        (
            [
                (46.723, {"latitude": 35.052, "longitude": 137.145}),
                (SPEED_MAXIMUM_STATISTIC_MAX_AGE.total_seconds() + 10, None),
                (UPDATES_STALLED_DELTA.total_seconds() + 10, None),
            ],
            [UPDATES_STALLED_MESSAGE],
            [RESET_MESSAGE],
        ),
        (
            [
                (46.723, {"latitude": 35.052, "longitude": 137.145}),
                (SPEED_MAXIMUM_STATISTIC_MAX_AGE.total_seconds() + 10, None),
                (UPDATES_STALLED_DELTA.total_seconds() + 10, None),
                (86400, None),
            ],
            [RESET_MESSAGE],
            [],
        ),
    ],
    ids=[
        "no_activity",
        "statistics_update_no_reload",
        "statistics_update_reload_for_speed",
        "updates_stalled",
        "midnight_reset",
    ],
)
async def test_scheduled_actions(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
    mock_now: MockNow,
    changes: list[tuple[float, dict[str, Any] | None]],
    expected_logged: list[str],
    expected_not_logged: list[str],
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
        mock_now._tick(tick)

        if change_attrs:
            hass.states.async_set(
                "person.akio_toyoda",
                "not_home",
                initial_attrs | change_attrs,
            )

        await hass.async_block_till_done()

    for message in expected_logged:
        assert message in caplog.text

    for message in expected_not_logged:
        assert message not in caplog.text

    device_id = mock_config_entry.entry_id
    device = device_registry.async_get_device({(DOMAIN, device_id)})
    entities = entity_registry.entities.get_entries_for_device_id(device.id)
    assert entities == snapshot(name="entities")

    for entity in entities:
        assert hass.states.get(entity.entity_id) == snapshot(name=entity.entity_id)


@pytest.mark.parametrize(
    ("sensor_attrs", "tick_duration", "update_location", "expected_call_count"),
    [
        ({"mode_type": "driving"}, 46.723, True, 1),
        ({}, 46.723, True, 0),
        ({"mode_type": "driving"}, 86400, False, 2),  # stalled & reset
    ],
    ids=["mode_type_driving", "mode_type_missing", "midnight_reset"],
)
async def test_event_emitted_for_dependent_template_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_now: MockNow,
    snapshot: SnapshotAssertion,
    sensor_attrs: dict[str, Any],
    tick_duration: int,
    update_location: bool,
    expected_call_count: int,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test sensors when tracked device changes state."""

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data=mock_config_entry.data
        | {CONF_DEPENDENT_ENTITIES: ["sensor.toyota_prius_distance"]},
    )

    hass.states.async_set(
        "person.akio_toyoda",
        "not_home",
        {
            "friendly_name": "Akio Toyoda",
            "latitude": 35.054,
            "longitude": 137.143,
            "gps_accuracy": 5,
        },
    )

    hass.states.async_set(
        "sensor.toyota_prius_distance",
        "1.34",
        {
            "friendly_name": "Toyota Prius Distance",
        }
        | sensor_attrs,
    )

    await setup_added_integration(hass, mock_config_entry)

    handle_event = Mock()
    cancel = hass.bus.async_listen(
        "movement.template_entity_should_apply_update", handle_event
    )

    mock_now._tick(tick_duration)

    if update_location:
        hass.states.async_set(
            "person.akio_toyoda",
            "not_home",
            {
                "friendly_name": "Akio Toyoda",
                "latitude": 35.052,
                "longitude": 137.145,
                "gps_accuracy": 15,
            },
        )

    try:
        await hass.async_block_till_done()
    finally:
        cancel()

    assert handle_event.call_count == expected_call_count
    assert [mock_call.args for mock_call in handle_event.mock_calls] == snapshot(
        name="event-triggers"
    )


async def test_track_renamed_tracked_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that config entry data is updated when tracked entity is renamed."""
    t1 = entity_registry.async_get_or_create(
        "person", "person", "akio_toyoda", suggested_object_id="akio_toyoda"
    )

    hass.states.async_set(t1.entity_id, "not_home")

    assert t1.entity_id == mock_config_entry.data[CONF_TRACKED_ENTITY]
    await setup_integration(hass, mock_config_entry)

    entity_registry.async_update_entity(
        t1.entity_id, new_entity_id=f"{t1.entity_id}_renamed"
    )
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert entry
    assert entry.data[CONF_TRACKED_ENTITY] == f"{t1.entity_id}_renamed"


async def test_track_renamed_dependent_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that config entry data is updated when dependent entity is
    renamed."""
    t1 = entity_registry.async_get_or_create(
        "sensor",
        "template",
        "toyota_prius_distance",
        suggested_object_id="toyota_prius_distance",
    )

    hass.states.async_set(
        t1.entity_id,
        "2.1",
        {
            "friendly_name": "Toyota Prius Distance",
            "mode_type": "driving",
        },
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data=mock_config_entry.data
        | {CONF_DEPENDENT_ENTITIES: ["sensor.toyota_prius_distance"]},
    )

    assert [t1.entity_id] == mock_config_entry.data[CONF_DEPENDENT_ENTITIES]
    await setup_added_integration(hass, mock_config_entry)

    entity_registry.async_update_entity(
        t1.entity_id, new_entity_id=f"{t1.entity_id}_renamed"
    )

    # even with an attempt to set this, the new config entry & coordinator may
    # do a refresh before it can be completed (see below for asserting the logs
    # have a warning).
    hass.states.async_set(
        f"{t1.entity_id}_renamed",
        "2.1",
        {
            "friendly_name": "Toyota Prius Distance",
            "mode_type": "driving",
        },
    )

    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert entry
    assert entry.data[CONF_DEPENDENT_ENTITIES] == [f"{t1.entity_id}_renamed"]

    # when renamed, the entity lookup will occur before the state has a chance
    # to make it into the state machine, so a warning needs to be generated and
    # presented to the user (but this is also generally useful for gracefully
    # handling the missing entity, i.e. it's deleted).
    assert (
        "could not notify dependent entity sensor.toyota_prius_distance_renamed because it could not be found"
        in caplog.text
    )


async def test_create_removed_tracked_entity_issue(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test we create an issue for removed tracked entities."""
    t1 = entity_registry.async_get_or_create(
        "person", "person", "akio_toyoda", suggested_object_id="akio_toyoda"
    )

    hass.states.async_set(t1.entity_id, "not_home")

    await setup_integration(hass, mock_config_entry)

    hass.states.async_remove(t1.entity_id)
    entity_registry.async_remove(t1.entity_id)
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(
        DOMAIN, f"tracked_entity_removed_{t1.entity_id}"
    )


async def test_create_removed_dependent_entity_issue(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test we create an issue for removed tracked entities."""
    t1 = entity_registry.async_get_or_create(
        "sensor",
        "template",
        "toyota_prius_distance",
        suggested_object_id="toyota_prius_distance",
    )

    hass.states.async_set(
        t1.entity_id,
        "2.1",
        {
            "friendly_name": "Toyota Prius Distance",
            "mode_type": "driving",
        },
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data=mock_config_entry.data
        | {CONF_DEPENDENT_ENTITIES: ["sensor.toyota_prius_distance"]},
    )

    assert [t1.entity_id] == mock_config_entry.data[CONF_DEPENDENT_ENTITIES]
    await setup_added_integration(hass, mock_config_entry)

    hass.states.async_remove(t1.entity_id)
    entity_registry.async_remove(t1.entity_id)
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(
        DOMAIN, f"tracked_entity_removed_{t1.entity_id}"
    )
