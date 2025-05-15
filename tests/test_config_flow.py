"""Test Movement config flow."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, selector
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.movement.config_flow import SECTION_ADVANCED_OPTIONS
from custom_components.movement.const import (
    CONF_DEPENDENT_ENTITIES,
    CONF_HIGHWAY,
    CONF_LOCAL,
    CONF_MULTIPLIERS,
    CONF_NEIGHBORHOOD,
    CONF_TRACKED_ENTITY,
    CONF_TRIP_ADDITION,
    DOMAIN,
)


@pytest.mark.parametrize(
    ("user_input", "expected_result"),
    [
        (
            {
                CONF_TRACKED_ENTITY: "person.akio_toyoda",
                CONF_MULTIPLIERS: {},
            },
            {
                CONF_TRACKED_ENTITY: "person.akio_toyoda",
                CONF_TRIP_ADDITION: 0,
                CONF_MULTIPLIERS: {
                    CONF_NEIGHBORHOOD: 1,
                    CONF_LOCAL: 1,
                    CONF_HIGHWAY: 1,
                },
            },
        ),
        (
            {
                CONF_TRACKED_ENTITY: "person.akio_toyoda",
                CONF_TRIP_ADDITION: 1.43,
                CONF_MULTIPLIERS: {
                    CONF_NEIGHBORHOOD: 1.15,
                    CONF_LOCAL: 0.98,
                    CONF_HIGHWAY: 1.2,
                },
            },
            {
                CONF_TRACKED_ENTITY: "person.akio_toyoda",
                CONF_TRIP_ADDITION: 1.43,
                CONF_MULTIPLIERS: {
                    CONF_NEIGHBORHOOD: 1.15,
                    CONF_LOCAL: 0.98,
                    CONF_HIGHWAY: 1.2,
                },
            },
        ),
    ],
)
async def test_user_flow(
    hass: HomeAssistant, user_input: dict, expected_result: dict
) -> None:
    """Test starting a flow by user."""

    hass.states.async_set(
        "person.akio_toyoda",
        "home",
        {"name": "Akio Toyoda", "latitude": 2.1, "longitude": 1.1},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.movement.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=user_input,
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == expected_result

        zone = hass.states.get(user_input[CONF_TRACKED_ENTITY])
        assert result["title"] == zone.name

        await hass.async_block_till_done()

    assert mock_setup_entry.called


async def test_options_flow(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test options flow."""

    mock_config = MockConfigEntry(
        domain=DOMAIN,
        title="home",
        data={
            CONF_TRACKED_ENTITY: "person.akio_toyoda",
            CONF_TRIP_ADDITION: 1.43,
            CONF_MULTIPLIERS: {
                CONF_NEIGHBORHOOD: 1.15,
                CONF_LOCAL: 0.98,
                CONF_HIGHWAY: 1.2,
            },
        },
        unique_id=f"{DOMAIN}_home",
    )
    mock_config.add_to_hass(hass)

    entity_registry.async_get_or_create(
        "sensor",
        "template",
        "shared_vehicle_template",
        suggested_object_id="shared_vehicle_template",
        unit_of_measurement="km",
        capabilities={"state_class": "total_increasing"},
    )
    entity_registry.async_get_or_create(
        "sensor",
        "template",
        "not_a_total_increasing",
        suggested_object_id="not_a_total_increasing",
        unit_of_measurement="km",
    )
    entity_registry.async_get_or_create(
        "sensor",
        "template",
        "not_a_km_measurement",
        suggested_object_id="not_a_km_measurement",
        capabilities={"state_class": "total_increasing"},
    )

    with patch(
        "custom_components.movement.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        await hass.config_entries.async_setup(mock_config.entry_id)
        await hass.async_block_till_done()
        assert mock_setup_entry.called

        result = await hass.config_entries.options.async_init(mock_config.entry_id)

    schema = result["data_schema"].schema
    advanced_options_section = schema[SECTION_ADVANCED_OPTIONS]
    advanced_options_schema = advanced_options_section.schema.schema
    dependent_entities = advanced_options_schema[CONF_DEPENDENT_ENTITIES]

    assert isinstance(dependent_entities, selector.EntitySelector)
    assert dependent_entities.config["include_entities"] == [
        "sensor.shared_vehicle_template",
    ]

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_TRACKED_ENTITY: "person.akio_toyoda",
            CONF_TRIP_ADDITION: 1.43,
            CONF_MULTIPLIERS: {
                CONF_NEIGHBORHOOD: 1,
                CONF_LOCAL: 0.98,
                CONF_HIGHWAY: 1.25,
            },
            SECTION_ADVANCED_OPTIONS: {
                CONF_DEPENDENT_ENTITIES: ["sensor.shared_vehicle_template"],
            },
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config.data == {
        CONF_TRACKED_ENTITY: "person.akio_toyoda",
        CONF_TRIP_ADDITION: 1.43,
        CONF_MULTIPLIERS: {
            CONF_NEIGHBORHOOD: 1,
            CONF_LOCAL: 0.98,
            CONF_HIGHWAY: 1.25,
        },
        CONF_DEPENDENT_ENTITIES: ["sensor.shared_vehicle_template"],
    }


async def test_abort_duplicated_entry(
    hass: HomeAssistant,
) -> None:
    """Test if we abort on duplicate user input data."""
    DATA = {
        CONF_TRACKED_ENTITY: "person.akio_toyoda",
        CONF_TRIP_ADDITION: 0,
        CONF_MULTIPLIERS: {
            CONF_NEIGHBORHOOD: 1,
            CONF_LOCAL: 1,
            CONF_HIGHWAY: 1,
        },
    }
    mock_config = MockConfigEntry(
        domain=DOMAIN,
        title="akio_toyoda",
        data=DATA,
        unique_id=f"{DOMAIN}_akio_toyoda",
    )
    mock_config.add_to_hass(hass)

    hass.states.async_set(
        "person.akio_toyoda",
        "home",
        {"name": "Akio Toyoda", "latitude": 2.1, "longitude": 1.1},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch("custom_components.movement.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=DATA,
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

        await hass.async_block_till_done()


async def test_avoid_duplicated_title(hass: HomeAssistant) -> None:
    """Test if we avoid duplicate titles."""
    MockConfigEntry(
        domain=DOMAIN,
        title="Akio Toyoda",
        data={
            CONF_TRACKED_ENTITY: "person.akio_toyoda1",
            CONF_TRIP_ADDITION: 0,
            CONF_MULTIPLIERS: {
                CONF_NEIGHBORHOOD: 1,
                CONF_LOCAL: 1,
                CONF_HIGHWAY: 1,
            },
        },
        unique_id=f"{DOMAIN}_akio_toyoda1",
    ).add_to_hass(hass)

    MockConfigEntry(
        domain=DOMAIN,
        title="Akio Toyoda 3",
        data={
            CONF_TRACKED_ENTITY: "person.akio_toyoda3",
            CONF_TRIP_ADDITION: 0,
            CONF_MULTIPLIERS: {
                CONF_NEIGHBORHOOD: 1,
                CONF_LOCAL: 1,
                CONF_HIGHWAY: 1,
            },
        },
        unique_id=f"{DOMAIN}_akio_toyoda_3",
    ).add_to_hass(hass)

    for i in range(0, 4):
        hass.states.async_set(
            f"person.akio_toyoda{i + 1}",
            "home",
            {"friendly_name": "Akio Toyoda", "latitude": 2.1, "longitude": 1.1},
        )

    with patch("custom_components.movement.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_TRACKED_ENTITY: "person.akio_toyoda2",
                CONF_TRIP_ADDITION: 0,
                CONF_MULTIPLIERS: {
                    CONF_NEIGHBORHOOD: 1,
                    CONF_LOCAL: 1,
                    CONF_HIGHWAY: 1,
                },
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Akio Toyoda 2"

        await hass.async_block_till_done()

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_TRACKED_ENTITY: "person.akio_toyoda4",
                CONF_TRIP_ADDITION: 0,
                CONF_MULTIPLIERS: {
                    CONF_NEIGHBORHOOD: 1,
                    CONF_LOCAL: 1,
                    CONF_HIGHWAY: 1,
                },
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Akio Toyoda 4"

        await hass.async_block_till_done()
