"""Config flow for Culligan (Azure)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CulliganApiClient, CulliganAuthError, CulliganError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL

STEP_USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)


async def _validate(hass, email: str, password: str) -> list[dict[str, Any]]:
    """Log in and return the account's devices, or raise."""
    session = async_get_clientsession(hass)
    client = CulliganApiClient(session, email, password)
    await client.async_login()
    return await client.async_get_devices()


class CulliganConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup and reauthentication."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            try:
                devices = await _validate(self.hass, email, user_input[CONF_PASSWORD])
            except CulliganAuthError:
                errors["base"] = "invalid_auth"
            except CulliganError:
                errors["base"] = "cannot_connect"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    await self.async_set_unique_id(email.lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=email,
                        data={
                            CONF_EMAIL: email,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the coordinator reports the credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            email = entry.data[CONF_EMAIL]
            try:
                await _validate(self.hass, email, user_input[CONF_PASSWORD])
            except CulliganAuthError:
                errors["base"] = "invalid_auth"
            except CulliganError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CulliganOptionsFlow()


class CulliganOptionsFlow(OptionsFlow):
    """Poll interval only.

    Kept deliberately conservative: this is an undocumented third-party API and
    a softener's state changes slowly. There is no reason to hammer it.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional("scan_interval", default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)
                    )
                }
            ),
        )
