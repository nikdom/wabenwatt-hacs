"""Config flow: source type, per-type form, options for the sensors, reauth."""

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
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import (
    CannotConnectError,
    DeviceInfo,
    InvalidTokenError,
    RateLimitedError,
    ReportRejectedError,
    WabenwattClient,
)
from .const import (
    CONF_BATTERY_ID,
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SENSOR,
    CONF_PLANT_ID,
    CONF_PV_SENSORS,
    CONF_SOC_SENSOR,
    CONF_SOURCE_TYPE,
    DEFAULT_NAME,
    DOMAIN,
    SOURCE_TYPE_BATTERY,
    SOURCE_TYPE_PV,
    SOURCE_TYPES,
)
from .coordinator import DeviceReading, read_device, send_reading, stash_first_report
from .readings import (
    SensorNotPercentError,
    SensorNotPowerError,
    SensorUnavailableError,
)

_LOGGER = logging.getLogger(__name__)

# A PV entry reports solar power and nothing else (0.3.0). The battery sensor
# that used to live here is gone: a home battery is its own device on wabenwatt
# now, with its own token, its own state of charge and its own balance. The
# combined payload it produced still works server-side for devices already
# sending it, but it cannot carry a state of charge — so offering it here would
# steer people into a dead end.
PLANT_SENSOR_SCHEMA: dict[vol.Marker, Any] = {
    vol.Required(CONF_PV_SENSORS): vol.All(
        EntitySelector(EntitySelectorConfig(domain="sensor", multiple=True)),
        vol.Length(min=1),
    ),
}

BATTERY_SENSOR_SCHEMA: dict[vol.Marker, Any] = {
    vol.Required(CONF_BATTERY_SENSOR): EntitySelector(
        EntitySelectorConfig(domain="sensor")
    ),
    vol.Optional(CONF_BATTERY_INVERT, default=False): BooleanSelector(),
    vol.Optional(CONF_SOC_SENSOR): EntitySelector(
        EntitySelectorConfig(domain="sensor")
    ),
}


def sensor_schema(source_type: str) -> dict[vol.Marker, Any]:
    return (
        BATTERY_SENSOR_SCHEMA
        if source_type == SOURCE_TYPE_BATTERY
        else PLANT_SENSOR_SCHEMA
    )


TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

type FlowErrors = dict[str, str]
type Placeholders = dict[str, str]


def token_unique_id(token: str) -> str:
    """Derive the entry's unique id from the token without storing the secret."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def _options_from(source_type: str, user_input: Mapping[str, Any]) -> dict[str, Any]:
    if source_type == SOURCE_TYPE_BATTERY:
        options: dict[str, Any] = {
            CONF_BATTERY_SENSOR: user_input[CONF_BATTERY_SENSOR],
            CONF_BATTERY_INVERT: bool(user_input.get(CONF_BATTERY_INVERT, False)),
        }
        if soc := user_input.get(CONF_SOC_SENSOR):
            options[CONF_SOC_SENSOR] = soc
        return options
    return {CONF_PV_SENSORS: list(user_input[CONF_PV_SENSORS])}


async def _validate(
    hass: HomeAssistant,
    source_type: str,
    token: str,
    options: Mapping[str, Any],
) -> tuple[FlowErrors, Placeholders, DeviceInfo | None, DeviceReading | None]:
    """Check token and sensors against the real API.

    Order: whoami (token, device name and type), then the sensors, then one
    real report — which doubles as the first data point, so the device shows up
    as active right after setup. whoami is a convenience: an API without it
    must not block setup, the report validates the token just as well.

    Returns the sent reading on success so the caller can stash it
    (stash_first_report) for the coordinator to reuse — sending a second
    report immediately after this one would trip the server's minimum report
    interval (see stash_first_report's docstring).
    """
    client = WabenwattClient(async_get_clientsession(hass), token)
    device: DeviceInfo | None
    try:
        device = await client.whoami()
    except InvalidTokenError:
        return {CONF_API_TOKEN: "invalid_token"}, {}, None, None
    except RateLimitedError:
        return {"base": "rate_limited"}, {}, None, None
    except CannotConnectError as err:
        _LOGGER.debug("whoami unavailable, continuing without device name: %s", err)
        device = None

    # A token for the other kind of device would be accepted by the form and
    # then rejected by every single report. Caught here, while the user is
    # still looking at the field they pasted it into.
    if device is not None and device.device_type != source_type:
        return {CONF_API_TOKEN: f"wrong_token_{source_type}"}, {}, device, None

    try:
        reading = read_device(
            hass,
            source_type,
            pv_sensors=list(options.get(CONF_PV_SENSORS, [])),
            battery_sensor=options.get(CONF_BATTERY_SENSOR),
            battery_invert=bool(options.get(CONF_BATTERY_INVERT, False)),
            soc_sensor=options.get(CONF_SOC_SENSOR),
        )
    except SensorUnavailableError as err:
        return (
            {"base": "sensor_unavailable"},
            {"entity_id": err.entity_id},
            device,
            None,
        )
    except SensorNotPowerError as err:
        return (
            {"base": "sensor_not_power"},
            {"entity_id": err.entity_id, "unit": err.unit or "—"},
            device,
            None,
        )
    except SensorNotPercentError as err:
        return (
            {CONF_SOC_SENSOR: "sensor_not_percent"},
            {"entity_id": err.entity_id, "unit": err.unit or "—"},
            device,
            None,
        )

    try:
        await send_reading(client, reading)
    except InvalidTokenError:
        return {CONF_API_TOKEN: "invalid_token"}, {}, device, None
    except RateLimitedError:
        return {"base": "rate_limited"}, {}, device, None
    except ReportRejectedError as err:
        return (
            {"base": "report_rejected"},
            {"code": err.code, "message": err.message},
            device,
            None,
        )
    except CannotConnectError:
        return {"base": "cannot_connect"}, {}, device, None
    return {}, {}, device, reading


class WabenwattConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wabenwatt."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the device type; skipped while there is only one."""
        if len(SOURCE_TYPES) == 1:
            return await self.async_step_pv()
        return self.async_show_menu(step_id="user", menu_options=list(SOURCE_TYPES))

    async def async_step_pv(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up a PV plant; the entry is named after the plant on wabenwatt."""
        return await self._async_step_device(SOURCE_TYPE_PV, user_input)

    async def async_step_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up a home battery; needs its OWN token, not the plant's."""
        return await self._async_step_device(SOURCE_TYPE_BATTERY, user_input)

    async def _async_step_device(
        self, source_type: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Shared body of the per-type steps: token, sensors, one real report."""
        errors: FlowErrors = {}
        placeholders: Placeholders = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            await self.async_set_unique_id(token_unique_id(token))
            self._abort_if_unique_id_configured()
            options = _options_from(source_type, user_input)
            errors, placeholders, device, reading = await _validate(
                self.hass, source_type, token, options
            )
            if not errors:
                if reading is not None:
                    stash_first_report(
                        self.hass, token_unique_id(token), reading, dt_util.utcnow()
                    )
                data: dict[str, Any] = {
                    CONF_SOURCE_TYPE: source_type,
                    CONF_API_TOKEN: token,
                }
                if device is not None:
                    key = (
                        CONF_BATTERY_ID
                        if source_type == SOURCE_TYPE_BATTERY
                        else CONF_PLANT_ID
                    )
                    data[key] = device.device_id
                return self.async_create_entry(
                    title=device.name if device is not None else DEFAULT_NAME,
                    data=data,
                    options=options,
                )

        schema = vol.Schema(
            {vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR, **sensor_schema(source_type)}
        )
        return self.async_show_form(
            step_id=source_type,
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
            source_type = entry.data.get(CONF_SOURCE_TYPE, SOURCE_TYPE_PV)
            errors, placeholders, device, reading = await _validate(
                self.hass, source_type, token, entry.options
            )
            if not errors:
                if reading is not None:
                    stash_first_report(self.hass, unique_id, reading, dt_util.utcnow())
                data_updates: dict[str, Any] = {CONF_API_TOKEN: token}
                if device is None:
                    return self.async_update_reload_and_abort(
                        entry, unique_id=unique_id, data_updates=data_updates
                    )
                # A rotated token may belong to another device: rename along.
                key = (
                    CONF_BATTERY_ID
                    if source_type == SOURCE_TYPE_BATTERY
                    else CONF_PLANT_ID
                )
                data_updates[key] = device.device_id
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=device.name,
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
    """Change the sensors of an existing device."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: FlowErrors = {}
        placeholders: Placeholders = {}
        source_type = self.config_entry.data.get(CONF_SOURCE_TYPE, SOURCE_TYPE_PV)
        if user_input is not None:
            options = _options_from(source_type, user_input)
            token = self.config_entry.data[CONF_API_TOKEN]
            errors, placeholders, _device, reading = await _validate(
                self.hass, source_type, token, options
            )
            if not errors:
                if reading is not None and self.config_entry.unique_id is not None:
                    stash_first_report(
                        self.hass,
                        self.config_entry.unique_id,
                        reading,
                        dt_util.utcnow(),
                    )
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(sensor_schema(source_type)),
                user_input if user_input is not None else self.config_entry.options,
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
