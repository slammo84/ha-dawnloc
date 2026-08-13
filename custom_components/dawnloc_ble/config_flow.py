from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

from .const import CONF_TOPIC, DEFAULT_TOPIC, DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, str] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="DAWNLoc BLE Bridge", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Optional(CONF_TOPIC, default=DEFAULT_TOPIC): str}),
        )
