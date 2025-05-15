"""Test statistics."""

from collections import deque

from homeassistant.core import HomeAssistant
import pytest

from custom_components.movement.statistics import (
    STAT_AVERAGE_LINEAR,
    STAT_CHANGE_SECOND,
    STAT_VALUE_MAX,
    Statistic,
)


@pytest.mark.parametrize(
    ("state_characteristic", "args", "result"),
    [
        (STAT_AVERAGE_LINEAR, ([5], [1]), 5),
        (STAT_AVERAGE_LINEAR, ([1, 2], [0, 1]), 1.5),
        (STAT_AVERAGE_LINEAR, ([], []), None),
        (STAT_CHANGE_SECOND, ([1, 2], [0, 1]), 1),
        (STAT_CHANGE_SECOND, ([4, 2], [1, 1]), None),
        (STAT_CHANGE_SECOND, ([], []), None),
        (STAT_VALUE_MAX, ([1, 2], [0, 1]), 2),
        (STAT_VALUE_MAX, ([], []), None),
    ],
    ids=[
        "avg of {5}",
        "avg of {1,2}",
        "avg of {}",
        "change/s of {1,2} over 1s",
        "change/s of {4,2} over 0s",
        "change/s of {}",
        "max of {1,2}",
        "max of {}",
    ],
)
async def test_statistics(
    hass: HomeAssistant,
    state_characteristic: str,
    args: tuple[deque[float], deque[float]],
    result: float | None,
) -> None:
    """Test statistics functions."""

    stat = Statistic(
        state_characteristic=state_characteristic,
        samples_max_buffer_size=None,
        samples_max_age=None,
    )

    for value, age in zip(*args):
        stat.add_state(value, age)

    assert stat.value == result
