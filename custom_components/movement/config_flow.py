"""Config flow for Movement integration."""

from __future__ import annotations

from typing import Any, Final, cast

from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorStateClass
from homeassistant.components.template import DOMAIN as TEMPLATE_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import State, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
from homeassistant.helpers.typing import VolDictType
from homeassistant.util import slugify
import voluptuous as vol

from .const import (
    CONF_DEPENDENT_ENTITIES,
    CONF_HIGHWAY,
    CONF_LOCAL,
    CONF_MULTIPLIERS,
    CONF_NEIGHBORHOOD,
    CONF_TRACKED_ENTITY,
    CONF_TRIP_ADDITION,
    DOMAIN,
)

SECTION_ADVANCED_OPTIONS: Final = "advanced_options"


def _base_schema(user_input: dict[str, Any]) -> VolDictType:
    return {
        vol.Required(
            CONF_TRACKED_ENTITY, default=user_input.get(CONF_TRACKED_ENTITY, [])
        ): EntitySelector(
            EntitySelectorConfig(domain=[DEVICE_TRACKER_DOMAIN, PERSON_DOMAIN]),
        ),
        vol.Required(
            CONF_TRIP_ADDITION,
            default=user_input.get(CONF_TRIP_ADDITION, 0),
        ): NumberSelector(
            NumberSelectorConfig(
                min=0, max=100, step=0.01, unit_of_measurement=UnitOfLength.KILOMETERS
            ),
        ),
        vol.Required(CONF_MULTIPLIERS): section(
            vol.Schema(
                {
                    vol.Required(
                        CONF_NEIGHBORHOOD,
                        default=user_input.get(CONF_MULTIPLIERS, {}).get(
                            CONF_NEIGHBORHOOD, 1
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, step=0.01, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_LOCAL,
                        default=user_input.get(CONF_MULTIPLIERS, {}).get(CONF_LOCAL, 1),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, step=0.01, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_HIGHWAY,
                        default=user_input.get(CONF_MULTIPLIERS, {}).get(
                            CONF_HIGHWAY, 1
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, step=0.01, mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
            {"collapsed": True},
        ),
    }


class MovementConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a Movement config flow."""

    VERSION = 1

    def _user_form_schema(self) -> vol.Schema:
        return vol.Schema(_base_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return MovementOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self._async_abort_entries_match(user_input)

            title = cast(
                State, self.hass.states.get(user_input[CONF_TRACKED_ENTITY])
            ).name

            slugified_existing_entry_titles = [
                slugify(e.title) for e in self._async_current_entries()
            ]

            possible_title = title
            tries = 1
            while slugify(possible_title) in slugified_existing_entry_titles:
                tries += 1
                possible_title = f"{title} {tries}"

            return self.async_create_entry(title=possible_title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_form_schema(),
        )


class MovementOptionsFlow(OptionsFlow):
    """Handle a option flow."""

    def _user_form_schema(self, user_input: dict[str, Any]) -> vol.Schema:
        entity_registry = er.async_get(self.hass)
        return vol.Schema(
            {
                **_base_schema(user_input),
                vol.Required(SECTION_ADVANCED_OPTIONS): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_DEPENDENT_ENTITIES,
                                default=user_input.get(CONF_DEPENDENT_ENTITIES, []),
                            ): EntitySelector(
                                EntitySelectorConfig(
                                    integration=TEMPLATE_DOMAIN,
                                    domain=[SENSOR_DOMAIN],
                                    include_entities=[
                                        entity_id
                                        for entity_id in entity_registry.entities.keys()
                                        if _is_total_increasing_and_kilometers(
                                            entity_registry, entity_id
                                        )
                                    ],
                                    multiple=True,
                                ),
                            )
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            advanced_options = user_input.pop(SECTION_ADVANCED_OPTIONS)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **user_input, **advanced_options},
            )
            return self.async_create_entry(title=self.config_entry.title, data={})

        return self.async_show_form(
            step_id="init",
            data_schema=self._user_form_schema(dict(self.config_entry.data)),
        )


def _is_total_increasing_and_kilometers(
    entity_registry: er.EntityRegistry,
    entity_id: str,
) -> bool:
    """Determine if an entity_id represents an entity with a `state_class` of
    `total_increasing` and a `unit_of_measurement` of `km`."""
    return bool(
        (entry := entity_registry.async_get(entity_id))
        and (
            entry.capabilities
            and entry.capabilities.get("state_class")
            == SensorStateClass.TOTAL_INCREASING
            and entry.unit_of_measurement == UnitOfLength.KILOMETERS
        )
    )
