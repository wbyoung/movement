"""Test history."""

from homeassistant.core import State
import pytest

from custom_components.movement.history import HistoryRegistry
from custom_components.movement.types import StateChangedData


def test_prior_attribute_availability() -> None:
    """Test that the prior attribute is unavailable."""
    history = HistoryRegistry()

    # after init, we should get an attribute error
    with pytest.raises(AttributeError):
        history.prior  # noqa: B018

    history.add_entry_from_state_change(
        StateChangedData(
            old_state=State("person.akio_toyoda", {"state": "not_home"}),
            new_state=State("person.akio_toyoda", {"state": "home"}),
        ),
    )

    # with an added item, this should work fine
    history.prior  # noqa: B018

    # reset, and we should get an attribute error again
    history.reset([])
    with pytest.raises(AttributeError):
        history.prior  # noqa: B018
