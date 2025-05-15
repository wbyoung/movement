"""Test services for the Movement integration."""

import datetime as dt
from enum import Flag
import re
from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion
import voluptuous as vol

from custom_components.movement.const import DOMAIN
from custom_components.movement.services import (
    ATTR_ADJUSTMENTS,
    ATTR_CONFIG_ENTRY,
    ATTR_DISTANCE,
    ATTR_MODE_OF_TRANSIT,
    SERVICE_NAME_ADD_DISTANCE,
)
from custom_components.movement.types import (
    HistoryEntry,
    Location,
    ModeOfTransit,
    MovementData,
)

from . import MockNow


class DefaultConfigEntry(Flag):
    _singleton = True


USE_CONFIG = DefaultConfigEntry._singleton


@pytest.fixture
def config_entry_data(
    mock_config_entry: MockConfigEntry, request: pytest.FixtureRequest
) -> dict[str, str]:
    """Fixture for the config entry."""
    if "config_entry" in request.param and request.param["config_entry"] is USE_CONFIG:
        return {"config_entry": mock_config_entry.entry_id}

    return cast(dict[str, str], request.param)


@pytest.mark.usefixtures("init_integration")
async def test_has_services(
    hass: HomeAssistant,
) -> None:
    """Test the existence of the Movement Service."""
    assert hass.services.has_service(DOMAIN, SERVICE_NAME_ADD_DISTANCE)


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("attrs",),
    [
        ({ATTR_DISTANCE: 1.2},),
        ({ATTR_ADJUSTMENTS: 3.1},),
        (
            {
                ATTR_DISTANCE: 1.2,
                ATTR_ADJUSTMENTS: 3.1,
                ATTR_MODE_OF_TRANSIT: str(ModeOfTransit.BIKING),
            },
        ),
    ],
    ids=["distance_only", "adjustments_only", "all_attrs"],
)
async def test_add_distance_service(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_now: MockNow,
    snapshot: SnapshotAssertion,
    attrs: dict[str, Any],
):
    """Test `add_distance` service call."""
    coordinator = mock_config_entry.runtime_data.coordinator
    coordinator.inject_data(
        data=MovementData(
            distance=0,
            adjustments=0,
            speed=0,
            mode_of_transit=ModeOfTransit.WALKING,
            change_count=0,
            ignore_count=0,
        ),
        history=[
            HistoryEntry(
                at=dt_util.utcnow() - dt.timedelta(seconds=51.23),
                location=Location(55.301973, -114.820543),
                accuracy=44,
            )
        ],
        transition=None,
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_NAME_ADD_DISTANCE,
        {
            ATTR_CONFIG_ENTRY: mock_config_entry.entry_id,
            **attrs,
        },
        blocking=True,
    )

    assert hass.states.get("sensor.mock_title_distance_traveled") == snapshot


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("config_entry_data", "service_data", "error", "error_message"),
    [
        ({}, {}, vol.er.Error, "required key not provided .+"),
        (
            {"config_entry": USE_CONFIG},
            {"distance": "incorrect distance value"},
            vol.er.Error,
            "expected float for dictionary value .+",
        ),
        (
            {"config_entry": USE_CONFIG},
            {"adjustments": "incorrect adjustments value"},
            vol.er.Error,
            "expected float for dictionary value .+",
        ),
        (
            {"config_entry": USE_CONFIG},
            {"mode_of_transit": "incorrect mode_of_transit value"},
            vol.er.Error,
            "expected ModeOfTransit or one of 'walking', 'biking', 'driving' for dictionary value .+",
        ),
        (
            {"config_entry": "incorrect entry"},
            {},
            ServiceValidationError,
            "Invalid config entry.+",
        ),
    ],
    indirect=["config_entry_data"],
)
async def test_add_distance_service_validation(
    hass: HomeAssistant,
    config_entry_data: dict[str, str],
    service_data: dict[str, str],
    error: type[Exception],
    error_message: str,
) -> None:
    """Test the `add_distance` service validation."""

    with pytest.raises(error) as exc:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_NAME_ADD_DISTANCE,
            config_entry_data | service_data,
            blocking=True,
        )
    assert re.match(error_message, str(exc.value))


@pytest.mark.usefixtures("init_integration")
async def test_add_distance_service_called_with_unloaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test `add_distance` service call with unloaded config entry."""
    await hass.config_entries.async_unload(mock_config_entry.entry_id)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_NAME_ADD_DISTANCE,
            {"config_entry": mock_config_entry.entry_id},
            blocking=True,
        )
