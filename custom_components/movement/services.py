"""Support for the Movement integration."""

from functools import partial
from typing import Final

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import selector
import voluptuous as vol

from .const import DOMAIN
from .coordinator import MovementUpdateCoordinator
from .types import ModeOfTransit, MovementConfigEntryRuntimeData, ServiceAdjustment

SERVICE_NAME_ADD_DISTANCE: Final = "add_distance"
ATTR_ADJUSTMENTS: Final = "adjustments"
ATTR_ATTRIBUTES: Final = "attributes"
ATTR_CONFIG_ENTRY: Final = "config_entry"
ATTR_DISTANCE: Final = "distance"
ATTR_MODE_OF_TRANSIT: Final = "mode_of_transit"
ATTR_STATE: Final = "state"
ATTR_TRIGGER: Final = "trigger"


SERVICE_SCHEMA_ADD_DISTANCE: Final = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): selector.ConfigEntrySelector(
            {
                "integration": DOMAIN,
            }
        ),
        vol.Optional(ATTR_DISTANCE): vol.Coerce(float),
        vol.Optional(ATTR_ADJUSTMENTS): vol.Coerce(float),
        vol.Optional(ATTR_MODE_OF_TRANSIT): vol.Coerce(ModeOfTransit),
    }
)


def _get_coordinator(
    hass: HomeAssistant, call: ServiceCall
) -> MovementUpdateCoordinator:
    """Get the coordinator from the entry."""

    entry_id: str = call.data[ATTR_CONFIG_ENTRY]
    entry: ConfigEntry | None = hass.config_entries.async_get_entry(entry_id)

    if not entry:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_config_entry",
            translation_placeholders={
                "config_entry": entry_id,
            },
        )

    if entry.state != ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unloaded_config_entry",
            translation_placeholders={
                "config_entry": entry.title,
            },
        )

    runtime_data: MovementConfigEntryRuntimeData = entry.runtime_data

    return runtime_data.coordinator


async def _add_distance(
    call: ServiceCall,
    *,
    hass: HomeAssistant,
) -> ServiceResponse:
    coordinator = _get_coordinator(hass, call)

    adjustment = ServiceAdjustment(
        distance=call.data.get(ATTR_DISTANCE, 0),
        adjustments=call.data.get(ATTR_ADJUSTMENTS, 0),
        mode_of_transit=call.data.get(ATTR_MODE_OF_TRANSIT),
    )

    await coordinator.async_perform_service_adjustment(adjustment)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Set up Movement services."""

    hass.services.async_register(
        DOMAIN,
        SERVICE_NAME_ADD_DISTANCE,
        partial(_add_distance, hass=hass),
        schema=SERVICE_SCHEMA_ADD_DISTANCE,
        supports_response=SupportsResponse.NONE,
    )
