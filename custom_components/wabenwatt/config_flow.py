"""Config flow: source type, plant form, options for the sensors, reauth."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_TOKEN, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    CannotConnectError,
    InvalidTokenError,
    RateLimitedError,
    ReportRejectedError,
    WabenwattClient,
)
from .const import (
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SENSOR,
    CONF_PV_SENSORS,
    CONF_SOURCE_TYPE,
    DEFAULT_NAME,
    DOMAIN,
    ERROR_BATTERY_NOT_SUPPORTED,
    SOURCE_TYPE_PV,
    SOURCE_TYPES,
)
from .readings import SensorNotPowerError, SensorUnavailableError, read_plant

SENSOR_SCHEMA: dict[vol.Marker, Any] = {
    vol.Required(CONF_PV_SENSORS): vol.All(
        EntitySelector(EntitySelectorConfig(domain="sensor", multiple=True)),
        vol.Length(min=1),
    ),
    vol.Optional(CONF_BATTERY_SENSOR): EntitySelector(
        EntitySelectorConfig(domain="sensor")
    ),
    vol.Optional(CONF_BATTERY_INVERT, default=False): BooleanSelector(),
}

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def token_unique_id(token: str) -> str:
    """Derive the entry's unique id from the token without storing the secret."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def _options_from(user_input: Mapping[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {
        CONF_PV_SENSORS: list(user_input[CONF_PV_SENSORS]),
        CONF_BATTERY_INVERT: bool(user_input.get(CONF_BATTERY_INVERT, False)),
    }
    if battery := user_input.get(CONF_BATTERY_SENSOR):
        options[CONF_BATTERY_SENSOR] = battery
    return options


async def _try_report(
    hass: HomeAssistant, token: str, options: Mapping[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    """Send one real report with the current sensor values.

    Returns (errors, description_placeholders); both empty on success. A real
    report validates token and sensors at once and doubles as the first data
    point, so the plant shows up as active right after setup.
    """
    try:
        reading = read_plant(
            hass,
            options[CONF_PV_SENSORS],
            options.get(CONF_BATTERY_SENSOR),
            options.get(CONF_BATTERY_INVERT, False),
        )
    except SensorUnavailableError as err:
        return {"base": "sensor_unavailable"}, {"entity_id": err.entity_id}
    except SensorNotPowerError as err:
        return {"base": "sensor_not_power"}, {
            "entity_id": err.entity_id,
            "unit": err.unit or "—",
        }

    client = WabenwattClient(async_get_clientsession(hass), token)
    try:
        await client.report(
            pv_power_w=reading.pv_power_w, battery_power_w=reading.battery_power_w
        )
    except InvalidTokenError:
        return {CONF_API_TOKEN: "invalid_token"}, {}
    except RateLimitedError:
        return {"base": "rate_limited"}, {}
    except ReportRejectedError as err:
        if err.code == ERROR_BATTERY_NOT_SUPPORTED:
            return {CONF_BATTERY_SENSOR: "battery_not_supported"}, {}
        return {"base": "report_rejected"}, {"code": err.code, "message": err.message}
    except CannotConnectError:
        return {"base": "cannot_connect"}, {}
    return {}, {}


class WabenwattConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wabenwatt."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the source type; skipped while there is only one."""
        if len(SOURCE_TYPES) == 1:
            return await self.async_step_pv()
        return self.async_show_menu(step_id="user", menu_options=list(SOURCE_TYPES))

    async def async_step_pv(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up a PV plant."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            await self.async_set_unique_id(token_unique_id(token))
            self._abort_if_unique_id_configured()
            options = _options_from(user_input)
            errors, placeholders = await _try_report(self.hass, token, options)
            if not errors:
                name = user_input[CONF_NAME].strip() or DEFAULT_NAME
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_SOURCE_TYPE: SOURCE_TYPE_PV,
                        CONF_NAME: name,
                        CONF_API_TOKEN: token,
                    },
                    options=options,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
                vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR,
                **SENSOR_SCHEMA,
            }
        )
        return self.async_show_form(
            step_id="pv",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth after the server rejected the stored token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the current token and verify it with a real report."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            unique_id = token_unique_id(token)
            other = self.hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, unique_id
            )
            if other is not None and other.entry_id != entry.entry_id:
                return self.async_abort(reason="already_configured")
            errors, placeholders = await _try_report(self.hass, token, entry.options)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    data_updates={CONF_API_TOKEN: token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR}),
            errors=errors,
            description_placeholders={"name": entry.title, **placeholders},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WabenwattOptionsFlow:
        return WabenwattOptionsFlow()


class WabenwattOptionsFlow(OptionsFlow):
    """Change the sensors of an existing plant."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            options = _options_from(user_input)
            errors, placeholders = await _try_report(
                self.hass, self.config_entry.data[CONF_API_TOKEN], options
            )
            if not errors:
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(SENSOR_SCHEMA),
                user_input if user_input is not None else self.config_entry.options,
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
