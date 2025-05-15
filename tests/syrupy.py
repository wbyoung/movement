"""Customizations for Syrupy."""

from typing import Any

from homeassistant.core import Event
from pytest_homeassistant_custom_component.syrupy import (
    ANY,
    HomeAssistantSnapshotExtension,
    HomeAssistantSnapshotSerializer,
)
from syrupy.extensions.amber import AmberDataSerializer
from syrupy.types import PropertyFilter, PropertyMatcher, PropertyPath, SerializableData


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
            data.as_dict() | {"id": ANY, "time_fired": ANY, "context": ANY}
        )


class MovementSnapshotExtension(HomeAssistantSnapshotExtension):
    serializer_class: type[AmberDataSerializer] = MovementSnapshotSerializer


class EventSnapshot(dict):
    """Tiny wrapper to represent an event in snapshots."""
