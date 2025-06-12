"""Diagnostics support for Movement."""

from collections.abc import Callable, Mapping
import random
from typing import Any, cast, overload

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
)
from homeassistant.core import HomeAssistant, callback

from .coordinator import MovementUpdateCoordinator

CONF_REFRESH_TOKEN = "refresh_token"  # noqa: S105
CONF_VIN = "vin"

TO_REDACT = {
    CONF_API_KEY,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_VIN,
}


async def async_get_config_entry_diagnostics(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: MovementUpdateCoordinator = entry.runtime_data.coordinator
    data: dict[str, Any] = {
        "entry": entry.as_dict(),
        "data": coordinator.data.as_dict(),
        "history": [item.as_dict() for item in coordinator.history.items],
        "transition": [item.as_dict() for item in coordinator.transition.items]
        if coordinator.transition.items is not None
        else None,
    }

    add_latitude = random.uniform(0, 180)  # noqa: S311
    add_longitude = random.uniform(0, 360)  # noqa: S311

    return map_data(
        async_redact_data(data, TO_REDACT),
        {
            CONF_LATITUDE: lambda x: mod_latitude(x + add_latitude),
            CONF_LONGITUDE: lambda x: mod_longitude(x + add_longitude),
        },
    )


@overload
def map_data(
    data: Mapping, mappers: Mapping[Any, Callable[[Any], Any]]
) -> dict: ...  # pragma: no cover


@overload
def map_data[T](data: T, mappers: Mapping[Any, Callable[[Any], Any]]) -> T: ...


@callback
def map_data[T](data: T, mappers: Mapping[Any, Callable[[Any], Any]]) -> T:
    """Map values in a dict.

    Returns:
        The data with values mapped based on the given mappers.
    """
    if not isinstance(data, (Mapping, list)):
        return data

    if isinstance(data, list):
        return cast("T", [map_data(val, mappers) for val in data])

    result = {**data}

    for key, value in result.items():
        if key in mappers:
            result[key] = mappers[key](result[key])
        elif isinstance(value, Mapping):
            result[key] = map_data(value, mappers)
        elif isinstance(value, list):
            result[key] = [map_data(item, mappers) for item in value]

    return cast("T", result)


def mod_latitude(value: float) -> float:
    return (90 + value) % 180 - 90


def mod_longitude(value: float) -> float:
    return (180 + value) % 360 - 180
