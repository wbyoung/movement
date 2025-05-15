"""Helper to manage history."""

from dataclasses import replace
import datetime as dt
import logging
from typing import Callable

from homeassistant.core import State
from homeassistant.util import dt as dt_util

from .const import DEBOUNCE_UPDATES_DELTA, HISTORY_EXPIRATION_DELTA, SPEED_USABLE_DELTA
from .types import ABSENT_NONE, AbsentNone, HistoryEntry, Location, StateChangedData

HISTORY_ENTRIES_MAX = 1000


_LOGGER = logging.getLogger(__name__)
_TRACE = 5


class HistoryRegistry:
    """HistoryRegistry class."""

    def __init__(self):
        super().__init__()
        self._items: list[HistoryEntry] = []
        self._prior: list[HistoryEntry] | None = None

    @property
    def items(self) -> list[HistoryEntry]:
        return self._items

    @property
    def prior(self) -> list[HistoryEntry]:
        if self._prior is None:
            raise AttributeError(
                "prior items unavailable: registry was (re-)initialized and has had no new entries added"
            )

        return self._prior

    @property
    def current_entry(self) -> HistoryEntry:
        return self.items[0]

    @property
    def prior_entry(self) -> HistoryEntry:
        return self.prior[0]

    def reset(self, items: list[HistoryEntry]):
        self._items = items
        self._prior = None

    def add_entry_from_state_change(
        self,
        change: StateChangedData,
        unworkable: Callable[[str], None] = lambda reason: None,
    ):
        """
        Update the location history with a new entry at the head of the list.

        Args:
            change: The state changed data from which to derive the new entry.
            unworkable: A callable to invoke if an unworkable data set is
                generated.

        Filter out older and less accurate entries from the remainder of the list
        while keeping all items that are not yet within the usable threshold for
        speed calculations (and one more just beyond that threshold) (see
        consideration #2 in `MovementUpdateCoordinator._calculate_speed` for why
        keeping recent items is important).

        Also, constrain the history to a maximum size.
        """
        _LOGGER.log(_TRACE, "add_entry_from_state_change %s", change)

        # this generally won't happen frequently for users, but could happen if
        # a person entity removes all of their devices that they're using for
        # tracking. but there will be no prior location for many tests cases.
        fallback_entry: HistoryEntry = self._make_fallback_entry(change)
        unworkable_reason: str | None = None

        self._items = self._clean(self._items)
        self._prune_items(change.new_state.attributes.get("gps_accuracy", None))
        self._items.insert(0, self._make_entry(change.new_state))
        self._mark_debounced_items()
        self._items = self._items[:HISTORY_ENTRIES_MAX]  # constrain the history
        self._prior = self._clean(self._items[1:]) or ([fallback_entry])

        # flag to skip updates marked for debounce/inaccuracy
        if self._items[0].debounce:
            unworkable_reason = "first history item marked for debounce"
        elif self._items[0].ignore == "inaccurate":
            unworkable_reason = "poor gps_accuracy"
        elif (ignore := self._prior[0].ignore) and self._prior[0] == fallback_entry:
            unworkable_reason = f"poor details ({ignore}) in `from_state`"

        if unworkable_reason:
            unworkable(unworkable_reason)

    def _make_entry(self, state: State, at: dt.datetime | None = None) -> HistoryEntry:
        attrs = state.attributes
        gps_accuracy = attrs.get("gps_accuracy")
        inaccurate = _default_negative(gps_accuracy) > 1000
        ignore: str | AbsentNone = ABSENT_NONE
        latitude = attrs.get("latitude")
        longitude = attrs.get("longitude")
        location: Location | AbsentNone = Location(
            latitude=latitude,
            longitude=longitude,
        )

        if inaccurate:
            ignore = "inaccurate"
            location = ABSENT_NONE

        if not latitude or not longitude:
            ignore = "no_location"
            location = ABSENT_NONE

        return HistoryEntry(
            at=at or dt_util.utcnow(),
            location=location,
            accuracy=_default_no_accuracy(gps_accuracy),
            ignore=ignore,
        )

    def _make_fallback_entry(self, change: StateChangedData) -> HistoryEntry:
        """Make the fallback history entry."""
        return self._make_entry(change.old_state, at=change.old_state.last_changed)

    def _prune_items(self, gps_accuracy: float | None):
        """Prune items for usability.

        Items are always kept if:

        - Not enough time has passed (SPEED_USABLE_DELTA) to make them usable
          yet for speed calculations

        Otherwise, they're kept if:

        - Have better accuracy than more recent entries and haven't expired
        - They're the first non-expired item that can be used for speed
          calculations even if they have worse accuracy than the given
          `gps_accuracy`.
        """
        current_time = dt_util.utcnow()
        usable_before = current_time - SPEED_USABLE_DELTA
        expire_time = current_time - HISTORY_EXPIRATION_DELTA

        have_one_usable = False
        accuracy_threshold = _default_negative(gps_accuracy)

        result = []

        for index, entry in enumerate(self._items):
            usable = entry.at <= usable_before
            waiting_to_be_usable = not usable
            expired = entry.at <= expire_time
            is_accurate = entry.accuracy < accuracy_threshold
            keep = waiting_to_be_usable or (is_accurate and not expired)

            # always keep the first one that's not expired that can be used for speed
            # calculations
            if usable and not expired and not have_one_usable:
                keep = True
                have_one_usable = True

            if keep:
                result.append(entry)
                accuracy_threshold = min(accuracy_threshold, entry.accuracy)

            _LOGGER.debug(
                f"\n"
                f"  [{index}]\n"
                f"    usable: {usable}\n"
                f"    waiting_to_be_usable: {waiting_to_be_usable}\n"
                f"    expired: {expired}\n"
                f"    is_accurate: {is_accurate}\n"
                f"    have_one_usable: {have_one_usable}\n"
                f"    keep: {keep}"
            )

        self._items = result

    def _mark_debounced_items(self):
        """Mark items that should be debounced.

        Entries that arrive with a very short timeframe of each other are marked
        (and later cleaned out of the working set of items) to work around
        home-assistant/core#126972.
        """
        result: list[HistoryEntry] = []
        prev_entry = None
        for index, entry in enumerate(reversed(self._items)):
            if prev_entry is not None:
                delta = entry.at - prev_entry.at
                _LOGGER.debug("[%s] delta for debounce: %s", index, delta)
                if delta < DEBOUNCE_UPDATES_DELTA:
                    entry = replace(entry, debounce=True)
            result.insert(0, entry)
            prev_entry = entry
        self._items = result

    @staticmethod
    def _clean(items: list[HistoryEntry]) -> list[HistoryEntry]:
        """Filter out entries that may be preserved for context.

        Some entries are left in the registry between updates just for context,
        but no longer provide any useful information. They generally do not
        provide useful information for calculations, but can be helpful in
        debugging.

        Both `ignore` and `debounce` should only be set to truthy values to
        make these filters easier to write.
        """
        return [item for item in items if not (item.ignore or item.debounce)]


def _default_negative(value: float | None) -> float:
    return -1 if value is None else value


def _default_no_accuracy(value: float | None) -> float:
    return HistoryEntry.NO_ACCURACY if value is None else value
