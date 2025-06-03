"""Movement dataclasses and typing."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, fields
import datetime as dt
from enum import Flag, StrEnum, auto
from typing import Any, Self, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import State
from homeassistant.exceptions import IntegrationError
from homeassistant.util import dt as dt_util

from . import coordinator as cdn, statistics as sts

type MovementConfigEntry = ConfigEntry[cdn.MovementUpdateCoordinator]


class MisconfigurationError(IntegrationError):
    """Error to indicate that the integration is misconfigured."""


class EntityMissingError(IntegrationError):
    """Error to indicate that a tracked/dependent entity is missing."""

    def __init__(self, entity_id: str) -> None:
        """Initialize."""

        super().__init__(f"Entity could not be found for {entity_id}")


@dataclass
class SkipUpdateCondition(Exception):
    """Error condition to indicate that an update should be skipped."""

    reason: str


@dataclass
class TransitionRequiredCondition(Exception):
    """Error condition to indicate that a transition should begin."""

    reason: str


@dataclass
class MovementConfigEntryRuntimeData:
    """Runtime data definition."""

    coordinator: cdn.MovementUpdateCoordinator


class AbsentFalse(Flag):
    """Absent class with singleton for `False` value."""

    _singleton = False


class AbsentNone(Flag):
    """Absent class with singleton for `None` value."""

    _singleton = None


ABSENT_FALSE = AbsentFalse._singleton  # noqa: SLF001
ABSENT_NONE = AbsentNone._singleton  # noqa: SLF001


class ModeOfTransit(StrEnum):
    """ModeOfTransit class."""

    WALKING = auto()
    BIKING = auto()
    DRIVING = auto()


@dataclass(frozen=True, kw_only=True)
class StatisticGroup:
    """StatisticGroup class."""

    update_rate: sts.Statistic
    speed_recent_avg: sts.Statistic
    speed_recent_max: sts.Statistic

    def __iter__(self) -> Generator[sts.Statistic]:
        for field in fields(self):
            yield getattr(self, field.name)

    def items(self) -> Generator[tuple[str, sts.Statistic]]:
        for field in fields(self):
            yield (field.name, getattr(self, field.name))


class RecalculationRequest:
    """RecalculationRequest base class."""


@dataclass
class StateChangedData(RecalculationRequest):
    """StateChangedData class."""

    old_state: State
    new_state: State


@dataclass
class ServiceAdjustment(RecalculationRequest):
    """ServiceAdjustment class."""

    distance: float = 0
    adjustments: float = 0
    mode_of_transit: ModeOfTransit | None = None


@dataclass
class ResetRequest(RecalculationRequest):
    """ResetRequest class."""


@dataclass
class SpeedStaleIndicator(RecalculationRequest):
    """SpeedStaleIndicator class."""


@dataclass
class UpdatesStalledIndicator(RecalculationRequest):
    """UpdatesStalledIndicator class."""


@dataclass
class Location:
    """Location class for GPS location."""

    latitude: float
    longitude: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            latitude=data["latitude"],
            longitude=data["longitude"],
        )


@dataclass
class HistoryEntry:
    """HistoryEntry class."""

    NO_ACCURACY = float("inf")  # noqa: RUF045

    at: dt.datetime
    location: Location | AbsentNone
    accuracy: float
    ignore: str | AbsentNone = ABSENT_NONE
    debounce: bool | AbsentFalse = ABSENT_FALSE

    def as_dict(self) -> dict[str, Any]:
        result = {
            "at": self.at.isoformat(sep=" "),
            "accuracy": self.accuracy,
        }

        if self.location != ABSENT_NONE:
            result["location"] = self.location.as_dict() if self.location else None

        if self.ignore != ABSENT_NONE:
            result["ignore"] = self.ignore or None

        if self.debounce != ABSENT_FALSE:
            result["debounce"] = self.debounce or None

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        location = data.get("location", ABSENT_NONE)

        if location:
            location = Location.from_dict(location)

        return cls(
            at=dt_util.parse_datetime(data["at"]),
            location=location,
            accuracy=data.get("accuracy", HistoryEntry.NO_ACCURACY),
            ignore=data.get("ignore", ABSENT_NONE),
            debounce=data.get("debounce", ABSENT_FALSE),
        )


@dataclass
class TransitionEntry:
    """TransitionEntry class."""

    distance: float
    adjustments: float | AbsentNone = ABSENT_NONE

    def as_dict(self) -> dict[str, Any]:
        result = {
            "distance": self.distance,
        }

        if self.adjustments != ABSENT_NONE:
            result["adjustments"] = self.adjustments

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            distance=data["distance"],
            adjustments=data.get("adjustments", ABSENT_NONE),
        )


@dataclass
class TypedMovementData:
    """TypedMovementData class."""

    distance: float
    trip_distance: float | None
    trip_adjustments: float | None
    trip_start: dt.datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "distance": self.distance,
            "trip_distance": self.trip_distance,
            "trip_adjustments": self.trip_adjustments,
            "trip_start": self.trip_start.isoformat(sep=" ")
            if self.trip_start
            else None,
        }

    def as_state_dict(self) -> dict[str, Any]:
        return {
            "state": str(self.distance),
            "attributes": {
                "trip_distance": self.trip_distance,
                "trip_adjustments": self.trip_adjustments,
                "trip_start": self.trip_start.isoformat(sep=" ")
                if self.trip_start
                else None,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            distance=data["distance"],
            trip_distance=data.get("trip_distance"),
            trip_adjustments=data.get("trip_adjustments"),
            trip_start=dt_util.parse_datetime(data["trip_start"])
            if data.get("trip_start")
            else None,
        )


@dataclass
class MovementData:
    """MovementData class."""

    distance: float
    adjustments: float
    speed: float | None
    mode_of_transit: ModeOfTransit | None
    change_count: int  # changes to distance
    ignore_count: int  # ignored updates due to accuracy/debounce

    def as_dict(self) -> dict[str, Any]:
        return {
            "distance": self.distance,
            "adjustments": self.adjustments,
            "speed": self.speed,
            "mode_of_transit": self.mode_of_transit,
            "change_count": self.change_count,
            "ignore_count": self.ignore_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            distance=data.get("distance", 0),
            adjustments=data.get("adjustments", 0),
            speed=data.get("speed"),
            mode_of_transit=cast("ModeOfTransit", data.get("mode_of_transit")),
            change_count=data.get("change_count", 0),
            ignore_count=data.get("ignore_count", 0),
        )
