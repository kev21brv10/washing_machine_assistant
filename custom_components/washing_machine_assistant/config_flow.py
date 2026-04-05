from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_DOOR_SENSOR,
    CONF_FINISH_GRACE_MINUTES,
    CONF_HIGH_POWER_W,
    CONF_NAME,
    CONF_POWER_SENSOR,
    CONF_RESET_FINISHED_MINUTES,
    CONF_START_POWER_W,
    CONF_STOP_POWER_W,
    CONF_UPDATE_INTERVAL_SECONDS,
    CONF_VIBRATION_SENSOR,
    DEFAULT_FINISH_GRACE_MINUTES,
    DEFAULT_HIGH_POWER_W,
    DEFAULT_NAME,
    DEFAULT_RESET_FINISHED_MINUTES,
    DEFAULT_START_POWER_W,
    DEFAULT_STOP_POWER_W,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
)


def _d(value):
    return value if value is not None else vol.UNDEFINED


def build_basic_schema(current: dict | None = None) -> vol.Schema:
    current = current or {}
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=_d(current.get(CONF_NAME, DEFAULT_NAME))): selector.TextSelector(),
            vol.Required(CONF_POWER_SENSOR, default=_d(current.get(CONF_POWER_SENSOR))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_VIBRATION_SENSOR, default=_d(current.get(CONF_VIBRATION_SENSOR))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(CONF_DOOR_SENSOR, default=_d(current.get(CONF_DOOR_SENSOR))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
        }
    )


def build_advanced_schema(current: dict | None = None) -> vol.Schema:
    current = current or {}
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=_d(current.get(CONF_NAME, DEFAULT_NAME))): selector.TextSelector(),
            vol.Required(CONF_POWER_SENSOR, default=_d(current.get(CONF_POWER_SENSOR))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_VIBRATION_SENSOR, default=_d(current.get(CONF_VIBRATION_SENSOR))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(CONF_DOOR_SENSOR, default=_d(current.get(CONF_DOOR_SENSOR))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Required(
                CONF_START_POWER_W,
                default=_d(current.get(CONF_START_POWER_W, DEFAULT_START_POWER_W)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=2500, step=1, unit_of_measurement="W")
            ),
            vol.Required(
                CONF_STOP_POWER_W,
                default=_d(current.get(CONF_STOP_POWER_W, DEFAULT_STOP_POWER_W)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=500, step=0.5, unit_of_measurement="W")
            ),
            vol.Required(
                CONF_HIGH_POWER_W,
                default=_d(current.get(CONF_HIGH_POWER_W, DEFAULT_HIGH_POWER_W)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=100, max=3500, step=10, unit_of_measurement="W")
            ),
            vol.Required(
                CONF_FINISH_GRACE_MINUTES,
                default=_d(current.get(CONF_FINISH_GRACE_MINUTES, DEFAULT_FINISH_GRACE_MINUTES)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=30, step=1, unit_of_measurement="min")
            ),
            vol.Required(
                CONF_RESET_FINISHED_MINUTES,
                default=_d(current.get(CONF_RESET_FINISHED_MINUTES, DEFAULT_RESET_FINISHED_MINUTES)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=720, step=5, unit_of_measurement="min")
            ),
            vol.Required(
                CONF_UPDATE_INTERVAL_SECONDS,
                default=_d(current.get(CONF_UPDATE_INTERVAL_SECONDS, DEFAULT_UPDATE_INTERVAL_SECONDS)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=10, max=300, step=5, unit_of_measurement="s")
            ),
        }
    )


class WashingMachineConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            power_sensor = user_input[CONF_POWER_SENSOR]
            await self.async_set_unique_id(power_sensor)
            self._abort_if_unique_id_configured()
            title = user_input.get(CONF_NAME) or DEFAULT_NAME
            return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(step_id="user", data_schema=build_basic_schema())

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        current = {**entry.data, **entry.options}
        if user_input is not None:
            return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(step_id="reconfigure", data_schema=build_basic_schema(current))

    @staticmethod
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return WashingMachineOptionsFlow(entry)


class WashingMachineOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        current = {**self.entry.data, **self.entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=build_advanced_schema(current))
