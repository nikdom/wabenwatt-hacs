"""Config, options and reauth flow."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wabenwatt.api import (
    CannotConnectError,
    InvalidTokenError,
    RateLimitedError,
    ReportRejectedError,
)
from custom_components.wabenwatt.config_flow import token_unique_id
from custom_components.wabenwatt.const import (
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
)

from .conftest import BATTERY, BATTERY_ID, BATTERY_TOKEN, PLANT, PLANT_ID, TOKEN

PV_INPUT = {
    CONF_API_TOKEN: f"  {TOKEN}  ",
    CONF_PV_SENSORS: ["sensor.pv_string_1", "sensor.pv_string_2"],
}


@pytest.fixture(autouse=True)
def _whoami_answers(mock_whoami: AsyncMock) -> None:
    """Every flow here talks to whoami; tests that care request the mock."""


async def _start_flow(hass: HomeAssistant) -> config_entries.ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _start_pv_flow(hass: HomeAssistant) -> config_entries.ConfigFlowResult:
    """Open the flow and pick the PV type — the menu step most tests skip past."""
    result = await _start_flow(hass)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_TYPE_PV}
    )


async def test_user_step_offers_the_device_types(
    hass: HomeAssistant, mock_report: AsyncMock, pv_states: None
) -> None:
    """Two device types, so the menu appears instead of jumping into the form."""
    result = await _start_flow(hass)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {SOURCE_TYPE_PV, SOURCE_TYPE_BATTERY}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_TYPE_PV}
    )
    assert result["step_id"] == "pv"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Named after the plant on wabenwatt, nothing typed by the user.
    assert result["title"] == "Balkon"
    assert result["data"] == {
        CONF_SOURCE_TYPE: SOURCE_TYPE_PV,
        CONF_API_TOKEN: TOKEN,
        CONF_PLANT_ID: PLANT_ID,
    }
    # A PV entry stores its sensors and nothing else: the battery fields are
    # gone from this form (docs/41-sites-and-batteries.md).
    assert result["options"] == {
        CONF_PV_SENSORS: ["sensor.pv_string_1", "sensor.pv_string_2"],
    }
    assert result["result"].unique_id == token_unique_id(TOKEN)
    # The flow's validation report carries the summed, unit-converted value.
    assert mock_report.call_args_list[0].kwargs == {"pv_power_w": 1242}


async def test_whoami_unavailable_falls_back_to_default_name(
    hass: HomeAssistant, mock_report: AsyncMock, mock_whoami: AsyncMock, pv_states: None
) -> None:
    mock_whoami.side_effect = CannotConnectError("404")
    result = await _start_pv_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert CONF_PLANT_ID not in result["data"]
    # The report still validated the token.
    assert mock_report.await_count >= 1


async def test_whoami_rejecting_the_token_stops_before_any_report(
    hass: HomeAssistant, mock_report: AsyncMock, mock_whoami: AsyncMock, pv_states: None
) -> None:
    mock_whoami.side_effect = InvalidTokenError()
    result = await _start_pv_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_TOKEN: "invalid_token"}
    mock_report.assert_not_called()


async def test_battery_device_creates_its_own_entry(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    mock_whoami: AsyncMock,
    battery_states: None,
) -> None:
    """A home battery is its own entry with its own token."""
    mock_whoami.return_value = BATTERY
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_TYPE_BATTERY}
    )
    assert result["step_id"] == "battery"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_API_TOKEN: BATTERY_TOKEN,
            CONF_BATTERY_SENSOR: "sensor.battery_power",
            CONF_SOC_SENSOR: "sensor.battery_soc",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hausakku"
    assert result["data"] == {
        CONF_SOURCE_TYPE: SOURCE_TYPE_BATTERY,
        CONF_API_TOKEN: BATTERY_TOKEN,
        CONF_BATTERY_ID: BATTERY_ID,
    }
    assert result["options"] == {
        CONF_BATTERY_SENSOR: "sensor.battery_power",
        CONF_BATTERY_INVERT: False,
        CONF_SOC_SENSOR: "sensor.battery_soc",
    }
    assert mock_report_battery.call_args_list[0].kwargs == {
        "battery_power_w": 350,
        "soc_percent": 62,
    }


async def test_a_battery_token_on_the_pv_form_is_caught(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    mock_whoami: AsyncMock,
    pv_states: None,
) -> None:
    """Otherwise the form accepts it and every report afterwards fails."""
    mock_whoami.return_value = BATTERY
    result = await _start_pv_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_TOKEN: "wrong_token_pv"}
    mock_report.assert_not_called()


async def test_a_non_percent_soc_sensor_is_refused(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    mock_whoami: AsyncMock,
    battery_states: None,
) -> None:
    """A state of charge in kWh is a wrongly picked entity, not a unit to convert."""
    mock_whoami.return_value = BATTERY
    hass.states.async_set("sensor.wrong_soc", "8", {"unit_of_measurement": "kWh"})
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_TYPE_BATTERY}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_API_TOKEN: BATTERY_TOKEN,
            CONF_BATTERY_SENSOR: "sensor.battery_power",
            CONF_SOC_SENSOR: "sensor.wrong_soc",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SOC_SENSOR: "sensor_not_percent"}
    mock_report_battery.assert_not_called()


@pytest.mark.parametrize(
    ("side_effect", "field", "error"),
    [
        (InvalidTokenError(), CONF_API_TOKEN, "invalid_token"),
        (RateLimitedError(), "base", "rate_limited"),
        (CannotConnectError("boom"), "base", "cannot_connect"),
        (
            ReportRejectedError(422, "REPORT_REJECTED", "too high"),
            "base",
            "report_rejected",
        ),
    ],
)
async def test_server_errors_are_shown_on_the_form(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    side_effect: Exception,
    field: str,
    error: str,
) -> None:
    mock_report.side_effect = side_effect
    result = await _start_pv_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}

    # Recovering from the error finishes the flow.
    mock_report.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_unavailable_sensor_blocks_setup(
    hass: HomeAssistant, mock_report: AsyncMock
) -> None:
    hass.states.async_set("sensor.pv_string_1", "742", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.pv_string_2", "unavailable")
    result = await _start_pv_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "sensor_unavailable"}
    assert result["description_placeholders"] == {"entity_id": "sensor.pv_string_2"}
    mock_report.assert_not_called()


async def test_non_power_sensor_blocks_setup(
    hass: HomeAssistant, mock_report: AsyncMock
) -> None:
    hass.states.async_set("sensor.pv_string_1", "742", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.pv_string_2", "55", {"unit_of_measurement": "%"})
    result = await _start_pv_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "sensor_not_power"}
    assert result["description_placeholders"] == {
        "entity_id": "sensor.pv_string_2",
        "unit": "%",
    }
    mock_report.assert_not_called()


async def test_same_token_twice_aborts(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    result = await _start_pv_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_replaces_sensors(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set("sensor.pv_total", "1.2", {"unit_of_measurement": "kW"})

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_PV_SENSORS: ["sensor.pv_total"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_PV_SENSORS: ["sensor.pv_total"]}
    assert mock_report.call_args.kwargs == {"pv_power_w": 1200}


async def test_reauth_stores_the_new_token_and_renames_along(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    mock_whoami: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_whoami.return_value = replace(PLANT, device_id="other-id", name="Dach")

    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_API_TOKEN: "new-token"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_TOKEN] == "new-token"
    assert config_entry.data[CONF_PLANT_ID] == "other-id"
    assert config_entry.unique_id == token_unique_id("new-token")
    assert config_entry.title == "Dach"
