"""Support for statistics for sensor values."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import timedelta
import logging
import time

from homeassistant.core import CALLBACK_TYPE
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def _stat_average_linear(states: deque[float], ages: deque[float]) -> float | None:
    if len(states) == 1:
        return states[0]
    if len(states) >= 2:
        area: float = 0
        for i in range(1, len(states)):
            area += 0.5 * (states[i] + states[i - 1]) * (ages[i] - ages[i - 1])
        age_range_seconds = ages[-1] - ages[0]
        return area / age_range_seconds
    return None


def _stat_change_second(states: deque[float], ages: deque[float]) -> float | None:
    if len(states) > 1:
        age_range_seconds = ages[-1] - ages[0]
        if age_range_seconds > 0:
            return (states[-1] - states[0]) / age_range_seconds
    return None


def _stat_value_max(
    states: deque[float],
    ages: deque[float],  # noqa: ARG001
) -> float | None:
    if len(states) > 0:
        return max(states)
    return None


STAT_AVERAGE_LINEAR = "average_linear"
STAT_CHANGE_SECOND = "change_second"
STAT_VALUE_MAX = "value_max"

STATS_NUMERIC_SUPPORT = {
    STAT_AVERAGE_LINEAR: _stat_average_linear,
    STAT_CHANGE_SECOND: _stat_change_second,
    STAT_VALUE_MAX: _stat_value_max,
}


class Statistic:
    """Representation of a Statistic.

    This is a very stripped down version of the Statistics sensor.
    """

    def __init__(
        self,
        state_characteristic: str,
        samples_max_buffer_size: int | None,
        samples_max_age: timedelta | None,
    ) -> None:
        """Initialize the Statistic."""
        self._state_characteristic: str = state_characteristic
        self._samples_max_age: float | None = (
            samples_max_age.total_seconds() if samples_max_age else None
        )
        self._value: float | None = None

        self.states: deque[float | bool] = deque(maxlen=samples_max_buffer_size)
        self.ages: deque[float] = deque(maxlen=samples_max_buffer_size)

        self._state_characteristic_fn: Callable[
            [deque[float], deque[float]],
            float | None,
        ] = STATS_NUMERIC_SUPPORT[state_characteristic]

        self._update_listener: CALLBACK_TYPE | None = None

    @property
    def value(self) -> float | None:
        return self._value

    def add_state(self, state: float, timestamp: float) -> None:
        """Add the state to the queue."""
        self.states.append(state)
        self.ages.append(timestamp)
        self.update()

    def update(self) -> None:
        """Get the latest value and updates the states."""
        self._async_purge_and_update()

    def next_to_purge_timestamp(self) -> float | None:
        """Find the timestamp when the next purge would occur.

        Returns:
            The next purge timestamp.
        """
        if self.ages and self._samples_max_age:
            # Take the oldest entry from the ages list and add the configured max_age.
            # If executed after purging old states, the result is the next timestamp
            # in the future when the oldest state will expire.
            return self.ages[0] + self._samples_max_age
        return None

    def _purge_old_states(self, max_age: float) -> None:
        """Remove states which are older than a given age."""
        now_timestamp = time.time()
        debug = _LOGGER.isEnabledFor(logging.DEBUG)

        if debug:  # pragma: no branch
            _LOGGER.debug(
                "%s: purging records older than %s(%s)",
                self._state_characteristic,
                dt_util.as_local(dt_util.utc_from_timestamp(now_timestamp - max_age)),
                self._samples_max_age,
            )

        while self.ages and (now_timestamp - self.ages[0]) > max_age:
            if debug:  # pragma: no branch
                _LOGGER.debug(
                    "%s: purging record with datetime %s(%s)",
                    self._state_characteristic,
                    dt_util.as_local(dt_util.utc_from_timestamp(self.ages[0])),
                    dt_util.utc_from_timestamp(now_timestamp - self.ages[0]),
                )
            self.ages.popleft()
            self.states.popleft()

    def _async_purge_and_update(self) -> None:
        """Purge old states and update the value."""
        _LOGGER.debug("%s: updating statistics", self._state_characteristic)
        if self._samples_max_age is not None:
            self._purge_old_states(self._samples_max_age)

        self._update_value()

    def _update_value(self) -> None:
        """Front to call the right statistical characteristics functions.

        One of the _stat_*() functions is represented by self._state_characteristic_fn().
        """
        value = self._state_characteristic_fn(self.states, self.ages)
        _LOGGER.debug(
            "%s: updating value: states: %s, ages: %s => %s",
            self._state_characteristic,
            self.states,
            self.ages,
            value,
        )
        self._value = value
