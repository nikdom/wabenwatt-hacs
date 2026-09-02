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
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SENSOR,
    CONF_PLANT_ID,
    CONF_PV_SENSORS,
    CONF_SOURCE_TYPE,
    DEFAULT_NAME,
    DOMAIN,
    SOURCE_TYPE_PV,
)

from .conftest import PLANT, PLANT_ID, TOKEN

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


async def test_user_step_skips_type_menu_and_creates_entry(
    hass: HomeAssistant, mock_report: AsyncMock, pv_states: None
) -> None:
    result = await _start_flow(hass)
    assert result["type"] is FlowResultType.FORM
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
    assert result["options"] == {
        CONF_PV_SENSORS: ["sensor.pv_string_1", "sensor.pv_string_2"],
        CONF_BATTERY_INVERT: False,
    }
    assert result["result"].unique_id == token_unique_id(TOKEN)
    # The flow's validation report carries the summed, unit-converted value.
    assert mock_report.call_args_list[0].kwargs == {
        "pv_power_w": 1242,
        "battery_power_w": None,
    }


async def test_whoami_unavailable_falls_back_to_default_name(
    hass: HomeAssistant, mock_report: AsyncMock, mock_whoami: AsyncMock, pv_states: None
) -> None:
    mock_whoami.side_effect = CannotConnectError("404")
    result = await _start_flow(hass)
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
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_TOKEN: "invalid_token"}
    mock_report.assert_not_called()


async def test_battery_sensor_is_sent_with_inverted_sign(
    hass: HomeAssistant, mock_report: AsyncMock, pv_states: None
) -> None:
    hass.states.async_set("sensor.battery", "300", {"unit_of_measurement": "W"})
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            **PV_INPUT,
            CONF_BATTERY_SENSOR: "sensor.battery",
            CONF_BATTERY_INVERT: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_BATTERY_SENSOR] == "sensor.battery"
    assert mock_report.call_args_list[0].kwargs == {
        "pv_power_w": 1242,
        "battery_power_w": -300,
    }


async def test_battery_sensor_is_refused_before_the_report_when_plant_cannot_take_it(
    hass: HomeAssistant, mock_report: AsyncMock, mock_whoami: AsyncMock, pv_states: None
) -> None:
    mock_whoami.return_value = replace(PLANT, reports_battery_separately=False)
    hass.states.async_set("sensor.battery", "300", {"unit_of_measurement": "W"})
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={**PV_INPUT, CONF_BATTERY_SENSOR: "sensor.battery"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_BATTERY_SENSOR: "battery_not_supported"}
    mock_report.assert_not_called()


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
        (
            ReportRejectedError(422, "BATTERY_NOT_SUPPORTED", "no"),
            CONF_BATTERY_SENSOR,
            "battery_not_supported",
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
    result = await _start_flow(hass)
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
    result = await _start_flow(hass)
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
    result = await _start_flow(hass)
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
    result = await _start_flow(hass)
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
    assert config_entry.options == {
        CONF_PV_SENSORS: ["sensor.pv_total"],
        CONF_BATTERY_INVERT: False,
    }
    assert mock_report.call_args.kwargs == {"pv_power_w": 1200, "battery_power_w": None}


async def test_reauth_stores_the_new_token_and_renames_along(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    mock_whoami: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_whoami.return_value = replace(PLANT, plant_id="other-id", name="Dach")

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
