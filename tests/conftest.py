"""Fixtures for testing."""

import logging
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml.loader import parse_yaml
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from syrupy.assertion import SnapshotAssertion

from custom_components.movement.const import (
    CONF_HIGHWAY,
    CONF_LOCAL,
    CONF_MULTIPLIERS,
    CONF_NEIGHBORHOOD,
    CONF_TRACKED_ENTITY,
    CONF_TRIP_ADDITION,
    DOMAIN,
)

from . import MOCK_UTC_NOW, MockNow, setup_integration
from .syrupy import MovementSnapshotExtension

_LOGGER = logging.getLogger(__name__)


def pytest_configure(config) -> None:
    is_capturing = config.getoption("capture") != "no"

    if not is_capturing and config.pluginmanager.hasplugin("logging"):
        _LOGGER.warning(
            "pytest run with `-s/--capture=no` and the logging plugin enabled "
            "run with `-p no:logging` to disable all sources of log capturing.",
        )

    # `pytest_homeassistant_custom_component` calls `logging.basicConfig` which
    # creates the `stderr` stream handler. in most cases that will result in
    # logs being duplicated, reported in the "stderr" and "logging" capture
    # sections. force reconfiguration, removing handlers when not running with
    # the `-s/--capture=no` flag.
    if is_capturing:
        logging.basicConfig(level=logging.INFO, handlers=[], force=True)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return snapshot assertion fixture with the Home Assistant extension."""
    return snapshot.use_extension(MovementSnapshotExtension)


@pytest.fixture
def mock_now(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> MockNow:
    """Return a mock now & utcnow datetime."""
    freezer.move_to(MOCK_UTC_NOW)

    return MockNow(hass, freezer)


_scenarios_validated = False

SCENARIOS = [
    "from_home_to_park_in_15_min",
    "from_home_to_park_in_4_min",
    "from_home_to_park_in_1_min",
    "person_without_gps",
    "movement_along_highway",
    "from_home_to_park_after_updates_stalled_3hr",
    "from_park_to_home_after_updates_resumed",
    "from_home_to_park_after_updates_resumed_update2",
    "ord_to_sea",
    "from_home_to_park_in_15_min_while_driving_slowly",
    "recent_speed_max_or_avg_dropping_to_walking_pace",
    "recent_speed_max_or_avg_higher_after_driving",
    "driving_after_slow_start_categorized_as_biking",
    "recent_speed_max_or_avg_dropping_to_biking_pace",
    "biking_after_driving_but_threshold_not_overcome",
    "biking_after_driving_but_threshold_is_overcome",
    "recent_speed_max_or_avg_expired",
    "distance_updates_lagging",
    "location_update_has_moderate_gps_accuracy",
    "location_update_has_moderate_gps_accuracy_and_worse_history",
    "location_update_has_moderate_gps_accuracy_and_expired_history",
    "location_update_while_driving_has_moderate_gps_accuracy_and_worse_history",
    "location_update_has_poor_gps_accuracy",
    "location_update_has_improved_gps_accuracy",
    "location_update_has_improved_gps_accuracy_but_state_lacks_history",
    "rapid_updates_entering_home_zone_after_being_at_neighbors_30_min_ago",
    "nearly_immediate_location_update_has_improved_gps_accuracy",
    "frequent_updates_recently_while_driving",
    "small_distance_changes_walking_after_driving",
    "clustered_updates_due_to_app_race_condition_1",
    "clustered_updates_due_to_app_race_condition_2",
    "clustered_updates_due_to_app_race_condition_a_minute_ago",
    "event_for_manual_adjust",
    "event_for_manual_adjust_while_in_transition",
    "reset",
    "type_walking_walking",
    "type_walking_walking_to_biking",
    "type_walking_walking_to_driving",
    "type_walking_walking_0_0_reset",
    "type_walking_walking_0_reset",
    "type_walking_trigger_transition_walking",
    "type_walking_trigger_transition_walking_2",
    "type_walking_trigger_transition_walking_3",
    "type_walking_trigger_transition_driving",
    "type_walking_trigger_transition_walking_4",
    "type_biking_walking",
    "type_biking_walking_to_biking",
    "type_biking_trigger_transition_biking",
    "type_biking_trigger_transition_biking_2",
    "type_biking_trigger_transition_driving",
    "type_biking_trigger_transition_biking_3",
    "type_driving_walking",
    "type_driving_walking_to_driving",
    "type_driving_trigger_transition_walking_to_driving",
    "type_driving_driving_to_walking",
    "type_driving_trigger_transition_driving",
    "type_driving_trigger_transition_driving_2",
    "type_driving_trigger_transition_driving_3",
    "type_driving_trigger_transition_driving_4",
    "type_walking_trigger_id_reset",
    "simple_distance_traveled_changed_trigger",
    "distance_traveled_changed_with_continuing_transition_but_old_state_value",
    "distance_traveled_changed_with_continuing_transition",
    "distance_traveled_changed_with_continuing_transition_while_unavailable",
]


@pytest.fixture(params=SCENARIOS)
def scenario_fixture(request: pytest.FixtureRequest) -> str:
    """Return every scenario."""
    global _scenarios_validated
    if not _scenarios_validated and (_scenarios_validated := True):
        scenarios_dir = Path(__file__).parent / "fixtures" / "scenarios"
        scenarios = {child.stem for child in scenarios_dir.iterdir()}
        expected = set(SCENARIOS) | {"_anchors"}
        missing = scenarios - expected
        extra = expected - scenarios

        assert not missing, f"Missing in SCENARIOS: {missing}"
        assert not extra, f"Extra values in SCENARIOS: {extra}"
    return str(request.param)


@pytest.fixture
def scenario(scenario_fixture: str) -> dict:
    """Return a specific scenario as an object."""
    anchors_str = load_fixture("scenarios/_anchors.yaml", DOMAIN)
    fixture_str = load_fixture(f"scenarios/{scenario_fixture}.yaml", DOMAIN)

    return dict(parse_yaml(f"{anchors_str}\n{fixture_str}"))


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the default mocked config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="mock-entry-id",
        data={
            CONF_TRACKED_ENTITY: "person.akio_toyoda",
            CONF_TRIP_ADDITION: 0,
            CONF_MULTIPLIERS: {
                CONF_NEIGHBORHOOD: 1,
                CONF_LOCAL: 1,
                CONF_HIGHWAY: 1,
            },
        },
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the Movement integration for testing."""
    await setup_integration(hass, mock_config_entry)

    return mock_config_entry
