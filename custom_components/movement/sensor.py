"""Support for the Movement service."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable, NamedTuple

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfLength,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import (
    ExtraStoredData,
    RestoredExtraData,
    RestoreEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DISTANCE,
    ATTR_DISTANCE_ADJUSTMENTS,
    ATTR_DISTANCE_BIKING,
    ATTR_DISTANCE_DRIVING,
    ATTR_DISTANCE_WALKING,
    ATTR_GPS_ACCURACY,
    ATTR_MODE_OF_TRANSIT,
    ATTR_SPEED,
    ATTR_UPDATE_COUNT,
    DOMAIN,
    MAX_RESTORE_HISTORY,
    MAX_RESTORE_TRANSITION,
)
from .coordinator import MovementUpdateCoordinator
from .types import (
    HistoryEntry,
    ModeOfTransit,
    MovementConfigEntry,
    MovementData,
    TransitionEntry,
    TypedMovementData,
)

_LOGGER = logging.getLogger(__name__)


class TrackedEntityDescriptor(NamedTuple):
    """Descriptor of a tracked entity."""

    entity_id: str
    identifier: str


@dataclass(frozen=True, kw_only=True)
class MovementSensorDescription(SensorEntityDescription):
    """Class describing Movement sensor entities."""

    value_fn: Callable[
        [MovementData, MovementUpdateCoordinator], str | int | float | None
    ]
    attrs_fn: Callable[
        [MovementData, MovementUpdateCoordinator], dict[str, Any] | None
    ] = lambda _, __: None

    restore_data_fn: Callable[
        [MovementData, MovementUpdateCoordinator], dict[str, Any] | None
    ] = lambda _, __: None

    restore_fn: Callable[[MovementUpdateCoordinator, dict[str, Any]], None] = (
        lambda _, __: None
    )


def _set_coordinator_data(
    coordinator: MovementUpdateCoordinator, data: dict[str, Any]
) -> None:
    history = data.pop("history", [])
    transition = data.pop("transition", None)
    coordinator.inject_data(
        MovementData.from_dict(data),
        history=[*map(HistoryEntry.from_dict, history)],
        transition=transition and [*map(TransitionEntry.from_dict, transition)],
    )


def _set_coordinator_typed_movement_data(
    coordinator: MovementUpdateCoordinator,
    movement_type: ModeOfTransit,
    data: TypedMovementData,
) -> None:
    coordinator.inject_typed_movement_data(movement_type, data)


SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    MovementSensorDescription(
        key=ATTR_DISTANCE,
        translation_key=ATTR_DISTANCE,
        value_fn=lambda data, _: data.distance,
        attrs_fn=lambda data, coordinator: (
            {
                "adjustments": data.adjustments,
                "speed": data.speed,
                "mode_of_transit": data.mode_of_transit,
                "ignore_count": data.ignore_count,
                "update_rate": coordinator.statistics.update_rate.value * 60
                if coordinator.statistics.update_rate.value
                else None,
            }
        ),
        restore_data_fn=lambda data, coordinator: (
            {
                **data.as_dict(),
                "history": [
                    item.as_dict()
                    for item in coordinator.history.items[:MAX_RESTORE_HISTORY]
                ],
                "transition": [
                    item.as_dict()
                    for item in coordinator.transition.items[:MAX_RESTORE_TRANSITION]
                ]
                if coordinator.transition.items is not None
                else None,
            }
        ),
        restore_fn=_set_coordinator_data,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=3,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-distance",
    ),
    MovementSensorDescription(
        key=ATTR_DISTANCE_ADJUSTMENTS,
        translation_key=ATTR_DISTANCE_ADJUSTMENTS,
        value_fn=lambda data, _: data.adjustments,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=3,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-plus",
    ),
    MovementSensorDescription(
        key=ATTR_DISTANCE_WALKING,
        translation_key=ATTR_DISTANCE_WALKING,
        value_fn=lambda _, coordinator: coordinator.walking_movement_data.distance,
        attrs_fn=lambda _, coordinator: (
            {
                "trip_start": coordinator.walking_movement_data.trip_start,
                "trip_distance": coordinator.walking_movement_data.trip_distance,
                "trip_adjustments": coordinator.walking_movement_data.trip_adjustments,
            }
        ),
        restore_data_fn=lambda _,
        coordinator: coordinator.walking_movement_data.as_dict(),
        restore_fn=lambda coordinator, data: _set_coordinator_typed_movement_data(
            coordinator, ModeOfTransit.WALKING, TypedMovementData.from_dict(data)
        ),
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=3,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:walk",
    ),
    MovementSensorDescription(
        key=ATTR_DISTANCE_BIKING,
        translation_key=ATTR_DISTANCE_BIKING,
        value_fn=lambda _, coordinator: coordinator.biking_movement_data.distance,
        attrs_fn=lambda _, coordinator: (
            {
                "trip_start": coordinator.biking_movement_data.trip_start,
                "trip_distance": coordinator.biking_movement_data.trip_distance,
                "trip_adjustments": coordinator.biking_movement_data.trip_adjustments,
            }
        ),
        restore_data_fn=lambda _,
        coordinator: coordinator.biking_movement_data.as_dict(),
        restore_fn=lambda coordinator, data: _set_coordinator_typed_movement_data(
            coordinator, ModeOfTransit.BIKING, TypedMovementData.from_dict(data)
        ),
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=3,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:bike",
    ),
    MovementSensorDescription(
        key=ATTR_DISTANCE_DRIVING,
        translation_key=ATTR_DISTANCE_DRIVING,
        value_fn=lambda _, coordinator: coordinator.driving_movement_data.distance,
        attrs_fn=lambda _, coordinator: (
            {
                "trip_start": coordinator.driving_movement_data.trip_start,
                "trip_distance": coordinator.driving_movement_data.trip_distance,
                "trip_adjustments": coordinator.driving_movement_data.trip_adjustments,
            }
        ),
        restore_data_fn=lambda _,
        coordinator: coordinator.driving_movement_data.as_dict(),
        restore_fn=lambda coordinator, data: _set_coordinator_typed_movement_data(
            coordinator, ModeOfTransit.DRIVING, TypedMovementData.from_dict(data)
        ),
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=3,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:car-convertible",
    ),
    MovementSensorDescription(
        key=ATTR_SPEED,
        translation_key=ATTR_SPEED,
        value_fn=lambda data, _: data.speed,
        attrs_fn=lambda data, coordinator: (
            {
                "speed_recent_avg": coordinator.statistics.speed_recent_avg.value,
                "speed_recent_max": coordinator.statistics.speed_recent_max.value,
            }
        ),
        device_class=SensorDeviceClass.SPEED,
        suggested_display_precision=3,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        icon="mdi:routes-clock",
    ),
    MovementSensorDescription(
        key=ATTR_MODE_OF_TRANSIT,
        translation_key=ATTR_MODE_OF_TRANSIT,
        value_fn=lambda data, _: data.mode_of_transit,
        attrs_fn=lambda data, coordinator: (
            {
                "transitioning": bool(coordinator.transition.items),
            }
        ),
        device_class=SensorDeviceClass.ENUM,
        options=list(ModeOfTransit),
        icon="mdi:walk",
    ),
    MovementSensorDescription(
        key=ATTR_GPS_ACCURACY,
        translation_key=ATTR_GPS_ACCURACY,
        value_fn=lambda data, coordinator: (
            (
                (items := coordinator.history.items)
                and (item := items[0] if len(items) else None)
                and (accuracy := item.accuracy)
                and (accuracy if accuracy < HistoryEntry.NO_ACCURACY else None)
            )
            or None
        ),
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=3,
        native_unit_of_measurement=UnitOfLength.METERS,
        icon="mdi:cellphone-marker",
    ),
    MovementSensorDescription(
        key=ATTR_UPDATE_COUNT,
        translation_key=ATTR_UPDATE_COUNT,
        value_fn=lambda data, _: data.change_count,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:numeric-positive-1",
    ),
)


def _device_info(coordinator: MovementUpdateCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name=coordinator.config_entry.title,
        entry_type=DeviceEntryType.SERVICE,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MovementConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Movement sensor entities based on a config entry."""
    coordinator = entry.runtime_data.coordinator
    tracked_entity_descriptor: TrackedEntityDescriptor | None = None
    tracked_entity_id = coordinator.tracked_entity
    tracked_entity_descriptor = TrackedEntityDescriptor(
        entity_id=tracked_entity_id,
        identifier=tracked_entity_id,
    )

    _LOGGER.debug(
        "Sensor tracked entity descriptor: %s for %s",
        tracked_entity_descriptor,
        coordinator.config_entry.entry_id,
    )

    entities: list[MovementSensor] = [
        MovementSensor(description, coordinator, tracked_entity_descriptor)
        for description in SENSOR_TYPES
    ]

    async_add_entities(entities)


class MovementSensor(
    CoordinatorEntity[MovementUpdateCoordinator], SensorEntity, RestoreEntity
):
    """Movement sensor."""

    _attr_has_entity_name = True
    entity_description: MovementSensorDescription

    def __init__(
        self,
        description: MovementSensorDescription,
        coordinator: MovementUpdateCoordinator,
        tracked_entity_descriptor: TrackedEntityDescriptor,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self.entity_description = description
        self.tracked_entity_id = tracked_entity_descriptor.entity_id

        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{tracked_entity_descriptor.identifier}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    async def async_added_to_hass(self) -> None:
        """Restore state."""
        await super().async_added_to_hass()

        if (
            (last_state := await self.async_get_last_state()) is not None
            and last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            and (extra_data := await self.async_get_last_extra_data()) is not None
        ):
            self.entity_description.restore_fn(self.coordinator, extra_data.as_dict())

    @property
    def extra_restore_state_data(self) -> ExtraStoredData | None:
        data = self.entity_description.restore_data_fn(self.data, self.coordinator)
        return RestoredExtraData(data) if data is not None else None

    @property
    def data(self) -> MovementData:
        """Get data from coordinator."""
        data: MovementData = self.coordinator.data
        return data

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.change_count >= 0
        )

    @property
    def native_value(self) -> str | float | None:
        """Return native sensor value."""
        return self.entity_description.value_fn(self.data, self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        return self.entity_description.attrs_fn(self.data, self.coordinator)
