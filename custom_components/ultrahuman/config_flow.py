"""Set up independent Ultrahuman daily accounts and Home devices."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import (
    UltrahumanApiClient,
    UltrahumanApiError,
    UltrahumanAuthError,
    UltrahumanRateLimitError,
)
from .const import (
    CONF_API_KEY,
    CONF_DEVICE_TYPE,
    CONF_EMAIL,
    CONF_MAC_ADDRESS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_HOME_UPDATE_INTERVAL,
    DEVICE_TYPE_DAILY,
    DEVICE_TYPE_HOME,
    DOMAIN,
    HOME_METRICS,
    MAX_HOME_UPDATE_INTERVAL,
    MIN_HOME_UPDATE_INTERVAL,
    normalize_mac_address,
)
from .models import MetricsSnapshot
from .parser import parse_daily_metrics, parse_home_metrics

_LOGGER = logging.getLogger(__name__)
_TOKEN_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


def _schema(device_type: str, defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    fields: dict[Any, Any] = {vol.Required(CONF_API_KEY): _TOKEN_SELECTOR}
    if device_type == DEVICE_TYPE_DAILY:
        fields[vol.Required(CONF_EMAIL, default=defaults.get(CONF_EMAIL, ""))] = str
    else:
        fields[
            vol.Required(CONF_MAC_ADDRESS, default=defaults.get(CONF_MAC_ADDRESS, ""))
        ] = str
        fields[vol.Optional(CONF_EMAIL, default=defaults.get(CONF_EMAIL, ""))] = str
    return vol.Schema(fields)


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> MetricsSnapshot:
    """Validate the selected source, including valid responses with no readings."""
    client = UltrahumanApiClient(
        async_get_clientsession(hass), data[CONF_API_KEY], data.get(CONF_EMAIL)
    )
    if data[CONF_DEVICE_TYPE] == DEVICE_TYPE_HOME:
        end_epoch = int(dt_util.utcnow().timestamp())
        start_epoch = end_epoch - int(timedelta(days=1).total_seconds())
        response = await client.async_get_home_metrics(
            data[CONF_MAC_ADDRESS], HOME_METRICS, start_epoch, end_epoch
        )
        return parse_home_metrics(
            response, data[CONF_MAC_ADDRESS], start_epoch, end_epoch
        )
    query_date = dt_util.now().date()
    response = await client.async_get_daily_metrics(query_date)
    return parse_daily_metrics(response, query_date)


class UltrahumanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one daily-health account or one Home device."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UltrahumanOptionsFlow()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["daily", "home"])

    async def async_step_daily(self, user_input=None) -> ConfigFlowResult:
        return await self._async_step_source(DEVICE_TYPE_DAILY, user_input)

    async def async_step_home(self, user_input=None) -> ConfigFlowResult:
        return await self._async_step_source(DEVICE_TYPE_HOME, user_input)

    async def _async_step_source(
        self, device_type: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**user_input, CONF_DEVICE_TYPE: device_type}
            data[CONF_API_KEY] = data[CONF_API_KEY].strip()
            email = data.get(CONF_EMAIL, "").strip().lower()
            data[CONF_EMAIL] = email
            if not data[CONF_API_KEY]:
                errors["base"] = "invalid_auth"
            if email:
                try:
                    vol.Email()(email)
                except vol.Invalid:
                    errors[CONF_EMAIL] = "invalid_email"
            elif device_type == DEVICE_TYPE_DAILY:
                errors[CONF_EMAIL] = "invalid_email"

            if device_type == DEVICE_TYPE_HOME:
                try:
                    data[CONF_MAC_ADDRESS] = normalize_mac_address(
                        data[CONF_MAC_ADDRESS]
                    )
                except ValueError:
                    errors[CONF_MAC_ADDRESS] = "invalid_mac"
                unique_id = f"home:{data[CONF_MAC_ADDRESS]}"
            else:
                unique_id = f"daily:{email}"

            if not errors:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                try:
                    snapshot = await _validate(self.hass, data)
                except UltrahumanAuthError:
                    errors["base"] = "invalid_auth"
                except UltrahumanRateLimitError:
                    errors["base"] = "rate_limited"
                except UltrahumanApiError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected exception during Ultrahuman setup")
                    errors["base"] = "unknown"
                else:
                    if device_type == DEVICE_TYPE_HOME:
                        title = f"Ultrahuman Home ({snapshot.device_name or data[CONF_MAC_ADDRESS]})"
                    else:
                        title = f"Ultrahuman ({email})"
                    return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id=device_type,
            data_schema=_schema(device_type, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        """Replace the token for this existing source."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                if not api_key:
                    raise UltrahumanAuthError("Empty API token")
                await _validate(self.hass, {**entry.data, CONF_API_KEY: api_key})
            except UltrahumanAuthError:
                errors["base"] = "invalid_auth"
            except UltrahumanRateLimitError:
                errors["base"] = "rate_limited"
            except UltrahumanApiError:
                errors["base"] = "cannot_connect"
            else:
                # Loaded entries reload via their data-change listener. Entries whose
                # first setup failed have no listener and need a scheduled reload here.
                needs_reload = not entry.update_listeners
                result = self.async_update_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )
                if needs_reload:
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return result
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _TOKEN_SELECTOR}),
            errors=errors,
        )


class UltrahumanOptionsFlow(OptionsFlow):
    """Change a Home device's refresh interval without rebuilding its entities."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HOME:
            return self.async_abort(reason="no_options")
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_HOME_UPDATE_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_HOME_UPDATE_INTERVAL, max=MAX_HOME_UPDATE_INTERVAL
                        ),
                    ),
                }
            ),
        )
