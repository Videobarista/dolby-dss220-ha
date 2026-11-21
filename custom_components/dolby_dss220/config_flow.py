"""Config flow for the Dolby DSS220 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DSSClient
from .const import (
    CONF_ALLOW_CONTROL,
    CONF_MODEL,
    CONF_SW_VERSION,
    DEFAULT_ALLOW_CONTROL,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
)
from .soap import (
    DSSConnectionError,
    DSSError,
    find_server_component,
    unique_id_from_component,
    validate_host,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)
USER_SCHEMA = CONNECTION_SCHEMA.extend(
    {vol.Required(CONF_ALLOW_CONTROL, default=DEFAULT_ALLOW_CONTROL): bool}
)
OPTIONS_SCHEMA = vol.Schema({vol.Required(CONF_ALLOW_CONTROL, default=DEFAULT_ALLOW_CONTROL): bool})


async def async_get_device_info(hass: HomeAssistant, host: str, port: int) -> dict[str, Any]:
    """Connect to the server and return its identity.

    Raises DSSConnectionError when unreachable and DSSError when the host does
    not answer like a Dolby DSS.
    """
    client = DSSClient(async_get_clientsession(hass), host, port)
    try:
        components = await client.get_device_components()
    except DSSConnectionError:
        raise
    except DSSError as err:
        _LOGGER.debug("Device components not available on %s: %s", host, err)
        components = []
    server = find_server_component(components)
    if server is None:
        # Still verify that this is a DSS SMI endpoint.
        await client.get_system_time()
        return {"unique_id": None, CONF_MODEL: None, CONF_SW_VERSION: None}
    return {
        "unique_id": unique_id_from_component(server),
        CONF_MODEL: server.model,
        CONF_SW_VERSION: server.version,
    }


class DSSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Dolby DSS220."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DSSOptionsFlow:
        """Return the options flow."""
        return DSSOptionsFlow()

    async def _async_try_connect(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate the input and connect; return (info, errors)."""
        try:
            host = validate_host(user_input[CONF_HOST])
        except ValueError:
            return None, {CONF_HOST: "invalid_host"}
        port = user_input[CONF_PORT]
        try:
            info = await async_get_device_info(self.hass, host, port)
        except DSSConnectionError:
            return None, {"base": "cannot_connect"}
        except DSSError:
            return None, {"base": "invalid_response"}
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to %s", host)
            return None, {"base": "unknown"}
        info[CONF_HOST] = host
        info[CONF_PORT] = port
        return info, {}

    @staticmethod
    def _entry_data(info: dict[str, Any]) -> dict[str, Any]:
        """Return the config entry data for a connection result."""
        return {
            CONF_HOST: info[CONF_HOST],
            CONF_PORT: info[CONF_PORT],
            CONF_MODEL: info[CONF_MODEL],
            CONF_SW_VERSION: info[CONF_SW_VERSION],
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._async_try_connect(user_input)
            if info is not None:
                if info["unique_id"] is not None:
                    await self.async_set_unique_id(info["unique_id"])
                    self._abort_if_unique_id_configured(
                        updates={CONF_HOST: info[CONF_HOST], CONF_PORT: info[CONF_PORT]}
                    )
                else:
                    self._async_abort_entries_match(
                        {CONF_HOST: info[CONF_HOST], CONF_PORT: info[CONF_PORT]}
                    )
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data=self._entry_data(info),
                    options={CONF_ALLOW_CONTROL: user_input[CONF_ALLOW_CONTROL]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host or port of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._async_try_connect(user_input)
            if info is not None:
                if info["unique_id"] is not None and entry.unique_id is not None:
                    await self.async_set_unique_id(info["unique_id"])
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates=self._entry_data(info)
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )


class DSSOptionsFlow(OptionsFlow):
    """Handle the options of a Dolby DSS220 entry."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
