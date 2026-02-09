"""Customizations for Syrupy."""

from typing import Any

from homeassistant.core import Event
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.syrupy import (
    ANY,
    HomeAssistantSnapshotExtension,
    HomeAssistantSnapshotSerializer,
)
from syrupy.extensions.amber import AmberDataSerializer
from syrupy.filters import props
from syrupy.types import (
    PropertyFilter,
    PropertyMatcher,
    PropertyName,
    PropertyPath,
    SerializableData,
)


class MovementSnapshotSerializer(HomeAssistantSnapshotSerializer):
    @classmethod
    def _serialize(
        cls,
        data: SerializableData,
        *,
        depth: int = 0,
        exclude: PropertyFilter | None = None,
        include: PropertyFilter | None = None,
        matcher: PropertyMatcher | None = None,
        path: PropertyPath = (),
        visited: set[Any] | None = None,
    ) -> str:
        if isinstance(data, Event):
            serializable_data = cls._serializable_event(data)
        else:
            serializable_data = data

        if isinstance(data, er.RegistryEntry):
            base_exclude = exclude
            exclude_props = props(
                # compat for HA DeviceRegistryEntrySnapshot <2025.9.0 and >=2026.2.0
                "object_id_base",
            )

            def combined_exclude(*, prop: PropertyName, path: PropertyPath) -> bool:
                if base_exclude and base_exclude(prop=prop, path=path):
                    return True
                return bool(exclude_props(prop=prop, path=path))

            exclude = combined_exclude

        serialized: str = super()._serialize(
            serializable_data,
            depth=depth,
            exclude=exclude,
            include=include,
            matcher=matcher,
            path=path,
            visited=visited,
        )

        return serialized

    @classmethod
    def _serializable_event(cls, data: Event) -> SerializableData:
        """Prepare a Home Assistant event for serialization."""
        return EventSnapshot(
            data.as_dict() | {"id": ANY, "time_fired": ANY, "context": ANY},
        )


class MovementSnapshotExtension(HomeAssistantSnapshotExtension):
    serializer_class: type[AmberDataSerializer] = MovementSnapshotSerializer


class EventSnapshot(dict):  # noqa: FURB189
    """Tiny wrapper to represent an event in snapshots."""
