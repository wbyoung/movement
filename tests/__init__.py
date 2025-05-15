import datetime as dt

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

MOCK_UTC_NOW = dt.datetime(2025, 5, 20, 10, 51, 32, 3245, tzinfo=dt.UTC)


class MockNow:
    def __init__(self, hass: HomeAssistant, freezer: FrozenDateTimeFactory):
        super().__init__()
        self.hass = hass
        self.freezer = freezer

    def _tick(self, seconds) -> None:
        self.freezer.tick(dt.timedelta(seconds=seconds))
        async_fire_time_changed(self.hass)


async def setup_integration(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Helper for setting up the component."""
    config_entry.add_to_hass(hass)
    await setup_added_integration(hass, config_entry)


async def setup_added_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Helper for setting up a previously added component."""

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
