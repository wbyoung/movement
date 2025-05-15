"""Test transition."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.movement.transition import TransitionRegistry
from custom_components.movement.types import MovementData


async def test_prior_attribute_availability(
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that the prior attribute is unavailble."""

    transition = TransitionRegistry(mock_config_entry)

    # after init, we should get an attribute error.
    with pytest.raises(AttributeError):
        transition.prior

    # use the `update_pending` context manager with `noop_update_on_exit`, then
    # access should work fine, but during, it should not.
    with transition.update_pending(noop_update_on_exit=True):
        with pytest.raises(AttributeError):
            transition.prior
    transition.prior

    # reset, and we should get an attribute. error again
    transition.reset([])
    with pytest.raises(AttributeError):
        transition.prior

    # after  `process_update`, access should work fine.
    transition.process_update(
        MovementData(
            distance=0,
            adjustments=0,
            speed=0,
            mode_of_transit=None,
            change_count=0,
            ignore_count=0,
        ),
        transitioning=False,
    )
    transition.prior

    # use the `update_pending` context manager, and we should get an attribute
    # error during and after.
    with transition.update_pending():
        with pytest.raises(AttributeError):
            transition.prior
    with pytest.raises(AttributeError):
        transition.prior
