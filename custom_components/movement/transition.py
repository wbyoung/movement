"""Helper to manage transition."""

from collections.abc import Generator
from contextlib import contextmanager
import logging

from . import calculations as calc
from .types import ABSENT_NONE, MovementConfigEntry, MovementData, TransitionEntry

TRANSITION_ENTRIES_MAX = 1000


_LOGGER = logging.getLogger(__name__)
_TRACE = 5


class TransitionRegistry:
    """TransitionRegistry class."""

    def __init__(  # noqa: D417
        self,
        *args,  # noqa: ANN002
        **kwargs,  # noqa: ANN003
    ) -> None:
        """Create a transition registry.

        Args:
            config_entry: The config entry to access configuration data.
            items: The items of the registry.
            prior: The prior items of the registry. When the argument is given,
                this will also make the `prior` property available without
                needing to first perform an update.
        """
        super().__init__()

        def spread(
            config_entry: MovementConfigEntry,
            items: list[TransitionEntry] | None = None,
            prior: list[TransitionEntry] | None = None,
        ) -> None:
            self._items: list[TransitionEntry] | None = items
            self._prior: list[TransitionEntry] | None = prior
            self._prior_valid: bool = "prior" in kwargs or len(args) >= 3
            self._config_entry = config_entry

        spread(*args, **kwargs)

    @property
    def items(self) -> list[TransitionEntry] | None:
        return self._items

    @property
    def prior(self) -> list[TransitionEntry] | None:
        if not self._prior_valid:
            msg = "prior items unavailable: registry was (re-)initialized and has had no update"
            raise AttributeError(msg)

        return self._prior

    def reset(self, items: list[TransitionEntry] | None) -> None:
        self._items = items
        self._prior = None
        self._prior_valid = False

    @contextmanager
    def update_pending(self, *, noop_update_on_exit: bool = False) -> Generator[None]:
        self._pre_update()
        try:
            yield
        finally:
            if noop_update_on_exit:
                self._post_update()

    def process_update(
        self,
        update: MovementData,
        *,
        transitioning: bool,
    ) -> float:
        """Update transition objects.

        Returns:
          The new total adjustments for the update.
        """
        self._clear_adjusted_entries()

        if transitioning:
            self._add_new_pending_entry(update)
        else:
            self._finalize_pending_entries(update)

        result = self._calculate_adjustments(update)
        _LOGGER.debug("adjustments calculated as %s", result)
        _LOGGER.debug("transition calculated as %s", self._items)

        self._items = self._items and self._items[:TRANSITION_ENTRIES_MAX]
        self._post_update()

        return result

    def _clear_adjusted_entries(self) -> None:
        """Clear out completed transition entries.

        These are the entries that have the `adjustments` attribute (from the
        previous update calculation).
        """
        entries = self._items

        if entries:
            entries = [item for item in entries if item.adjustments == ABSENT_NONE]

            if not len(entries):
                entries = None

        _LOGGER.debug(
            "transition entries cleared of completed items to length %d",
            len(entries) if entries else 0,
        )

        self._items = entries

    def _add_new_pending_entry(self, update: MovementData) -> None:
        """Store the update distance in a pending entry.

        When transitioning, this allows waiting to calculate adjustments until
        the speed/mode is known. Entries without an `adjustments` attribute (set
        as `ABSENT_NONE`) are considered to be in a pending state.
        """
        self._items = self._items or []

        if update.distance > 0:
            self._items.append(TransitionEntry(distance=update.distance))

    def _finalize_pending_entries(self, update: MovementData) -> None:
        """Finalize pending entries.

        When the speed/mode is known, the existing entries can be finalized by
        calculating the adjustments and adding the `adjustments` attribute to
        the entry.
        """
        speed = update.speed
        mode = update.mode_of_transit
        entries = self._items

        if mode and entries:
            new_entries: list[TransitionEntry] = []
            for transition_entry in entries or []:
                new_adjustments = calc.calculate_distance_adjustments(
                    distance=transition_entry.distance,
                    speed=speed,
                    mode_of_transit=mode,
                    prior_mode_of_transit=mode,
                    transitioning=False,
                    config_entry=self._config_entry,
                )

                new_entries.append(
                    TransitionEntry(
                        distance=transition_entry.distance + new_adjustments,
                        adjustments=new_adjustments,
                    ),
                )
            entries = new_entries

        self._items = entries

    def _calculate_adjustments(self, update: MovementData) -> float:
        """Calculate new adjustments for the update.

        Returns:
            The new adjustments.
        """
        return update.adjustments + sum(
            item.adjustments
            for item in (self._items or [])
            if item.adjustments != ABSENT_NONE
        )

    def _pre_update(self) -> None:
        """Prepare for a pending update."""
        self._prior_valid = False

    def _post_update(self) -> None:
        """Update items post-update if needed not already done."""
        if not self._prior_valid:
            self._prior = self._items
            self._prior_valid = True
