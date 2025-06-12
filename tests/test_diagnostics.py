"""Test Movement diagnostics."""

import datetime as dt
from typing import Any
from unittest.mock import patch

from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props
from syrupy.matchers import path_type

from custom_components.movement.diagnostics import map_data

from . import MOCK_UTC_NOW, setup_integration


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [(46.723, {"latitude": 35.052, "longitude": 137.145})],
        [
            (46.723, {"latitude": 35.052, "longitude": 137.145}),
            (53.821, {"latitude": 35.05, "longitude": 137.147}),
        ],
    ],
    ids=[
        "no_activity",
        "no_movement",
        "some_movement",
    ],
)
async def test_entry_diagnostics(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    snapshot: SnapshotAssertion,
    changes: list[tuple[float, dict[str, Any] | None]],
) -> None:
    """Test config entry diagnostics."""
    await async_setup_component(hass, "homeassistant", {})

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

    with freeze_time(MOCK_UTC_NOW) as freezer:
        await setup_integration(hass, mock_config_entry)

        for tick, change_attrs in changes:
            freezer.tick(dt.timedelta(seconds=tick))
            async_fire_time_changed(hass)

            if change_attrs:
                hass.states.async_set(
                    "person.akio_toyoda",
                    "not_home",
                    initial_attrs | change_attrs,
                )

            await hass.async_block_till_done()

    with patch(
        "random.uniform",
        return_value=True,
    ) as mock_random:
        mock_random.side_effect = [-30, 22]

        assert await get_diagnostics_for_config_entry(
            hass, hass_client, mock_config_entry
        ) == snapshot(
            exclude=props("created_at", "modified_at"),
            matcher=_round_floats_matcher,
        )


@pytest.mark.parametrize(
    ("data", "mappers", "expected"),
    [
        ([], {}, []),
        ({}, {}, {}),
        ("simple-string", {}, "simple-string"),
        (
            {"map_me": 1, "keep_me": 1},
            {"map_me": lambda x: f"changed-{x}"},
            {"map_me": "changed-1", "keep_me": 1},
        ),
    ],
    ids=[
        "empty_list",
        "empty_object",
        "string",
        "simple-conversion",
    ],
)
def test_map_data(
    data: Any,
    mappers: dict[str, Any],
    expected: Any,
) -> None:
    assert map_data(data, mappers) == expected


_round_floats_matcher = path_type(
    types=(float,),
    replacer=lambda data, _: round(data, 5),
)
