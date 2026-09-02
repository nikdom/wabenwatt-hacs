"""Config flow: source type, plant form, options for the sensors, reauth."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_TOKEN
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
    PlantInfo,
    RateLimitedError,
    ReportRejectedError,
    WabenwattClient,
)
from .const import (
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SENSOR,
    CONF_PLANT_ID,
    CONF_PV_SENSORS,
    CONF_SOURCE_TYPE,
    DEFAULT_NAME,
    DOMAIN,
    ERROR_BATTERY_NOT_SUPPORTED,
    SOURCE_TYPE_PV,
    SOURCE_TYPES,
)
from .readings import SensorNotPowerError, SensorUnavailableError, read_plant

_LOGGER = logging.getLogger(__name__)

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

type FlowErrors = dict[str, str]
type Placeholders = dict[str, str]


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


async def _validate(
    hass: HomeAssistant, token: str, options: Mapping[str, Any]
) -> tuple[FlowErrors, Placeholders, PlantInfo | None]:
    """Check token and sensors against the real API.

    Order: whoami (token, plant name, battery flag), then the sensors, then one
    real report — which doubles as the first data point, so the plant shows up
    as active right after setup. whoami is a convenience: an API without it
    must not block setup, the report validates the token just as well.
    """
    client = WabenwattClient(async_get_clientsession(hass), token)
    plant: PlantInfo | None
    try:
        plant = await client.whoami()
    except InvalidTokenError:
        return {CONF_API_TOKEN: "invalid_token"}, {}, None
    except RateLimitedError:
        return {"base": "rate_limited"}, {}, None
    except CannotConnectError as err:
        _LOGGER.debug("whoami unavailable, continuing without plant name: %s", err)
        plant = None

    if (
        plant is not None
        and options.get(CONF_BATTERY_SENSOR)
        and not plant.reports_battery_separately
    ):
        return {CONF_BATTERY_SENSOR: "battery_not_supported"}, {}, plant

    try:
        reading = read_plant(
            hass,
            options[CONF_PV_SENSORS],
            options.get(CONF_BATTERY_SENSOR),
            options.get(CONF_BATTERY_INVERT, False),
        )
    except SensorUnavailableError as err:
        return {"base": "sensor_unavailable"}, {"entity_id": err.entity_id}, plant
    except SensorNotPowerError as err:
        return (
            {"base": "sensor_not_power"},
            {"entity_id": err.entity_id, "unit": err.unit or "—"},
            plant,
        )

    try:
        await client.report(
            pv_power_w=reading.pv_power_w, battery_power_w=reading.battery_power_w
        )
    except InvalidTokenError:
        return {CONF_API_TOKEN: "invalid_token"}, {}, plant
    except RateLimitedError:
        return {"base": "rate_limited"}, {}, plant
    except ReportRejectedError as err:
        if err.code == ERROR_BATTERY_NOT_SUPPORTED:
            return {CONF_BATTERY_SENSOR: "battery_not_supported"}, {}, plant
        return (
            {"base": "report_rejected"},
            {"code": err.code, "message": err.message},
            plant,
        )
    except CannotConnectError:
        return {"base": "cannot_connect"}, {}, plant
    return {}, {}, plant


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
        """Set up a PV plant; the entry is named after the plant on wabenwatt."""
        errors: FlowErrors = {}
        placeholders: Placeholders = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            await self.async_set_unique_id(token_unique_id(token))
            self._abort_if_unique_id_configured()
            options = _options_from(user_input)
            errors, placeholders, plant = await _validate(self.hass, token, options)
            if not errors:
                data: dict[str, Any] = {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_PV,
                    CONF_API_TOKEN: token,
                }
                if plant is not None:
                    data[CONF_PLANT_ID] = plant.plant_id
                return self.async_create_entry(
                    title=plant.name if plant is not None else DEFAULT_NAME,
                    data=data,
                    options=options,
                )

        schema = vol.Schema(
            {vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR, **SENSOR_SCHEMA}
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
        errors: FlowErrors = {}
        placeholders: Placeholders = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            unique_id = token_unique_id(token)
            other = self.hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, unique_id
            )
            if other is not None and other.entry_id != entry.entry_id:
                return self.async_abort(reason="already_configured")
            errors, placeholders, plant = await _validate(
                self.hass, token, entry.options
            )
            if not errors:
                data_updates: dict[str, Any] = {CONF_API_TOKEN: token}
                if plant is None:
                    return self.async_update_reload_and_abort(
                        entry, unique_id=unique_id, data_updates=data_updates
                    )
                # A rotated token may belong to another plant: rename along.
                data_updates[CONF_PLANT_ID] = plant.plant_id
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=plant.name,
                    data_updates=data_updates,
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
        errors: FlowErrors = {}
        placeholders: Placeholders = {}
        if user_input is not None:
            options = _options_from(user_input)
            errors, placeholders, _ = await _validate(
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
