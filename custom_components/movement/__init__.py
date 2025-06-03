"""The Movement integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_entity_registry_updated_event,
    async_track_state_change_event,
)
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DEPENDENT_ENTITIES, CONF_TRACKED_ENTITY, DOMAIN
from .coordinator import MovementUpdateCoordinator
from .services import async_setup_services
from .types import MovementConfigEntry, MovementConfigEntryRuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(  # noqa: RUF029
    hass: HomeAssistant,
    config: ConfigType,  # noqa: ARG001
) -> bool:
    """Set up Movement services.

    Returns:
        If the setup was successful.
    """
    async_setup_services(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: MovementConfigEntry) -> bool:
    """Set up Movement from a config entry.

    Returns:
        If the setup was successful.
    """
    _LOGGER.debug("setup %s with config:%s", entry.title, entry.data)

    coordinator = MovementUpdateCoordinator(hass, entry)

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            [entry.data[CONF_TRACKED_ENTITY]],
            coordinator.async_handle_entity_state_change,
        ),
    )

    entry.async_on_unload(
        async_track_entity_registry_updated_event(
            hass,
            [
                entry.data[CONF_TRACKED_ENTITY],
                *entry.data.get(CONF_DEPENDENT_ENTITIES, []),
            ],
            coordinator.async_handle_tracked_entity_change,
        ),
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = MovementConfigEntryRuntimeData(
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MovementConfigEntry) -> bool:
    """Unload a config entry.

    Returns:
        If the unload was successful.
    """
    unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = entry.runtime_data.coordinator
        coordinator.cancel_all_listeners()

    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant,
    entry: MovementConfigEntry,
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
