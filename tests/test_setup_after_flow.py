"""Setup right after the config flow must not send a second report.

The flow's own validation report and the coordinator's first refresh used to
both fire within milliseconds of each other, well inside the server's 25s
minimum report interval (docs/04-reporting.md) — so every fresh setup (and
every sensor change through the options flow) tripped RATE_LIMITED once, and
the "last error" entity showed it forever afterwards (fixed separately in
coordinator.py). This file guards the root cause: __init__.py must seed the
coordinator from the flow's already-successful report instead of sending its
own.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wabenwatt.const import CONF_PV_SENSORS, DOMAIN

from .conftest import TOKEN

PV_INPUT = {
    CONF_API_TOKEN: TOKEN,
    CONF_PV_SENSORS: ["sensor.pv_string_1", "sensor.pv_string_2"],
}


@pytest.fixture(autouse=True)
def _whoami_answers(mock_whoami: AsyncMock) -> None:
    """Every flow here talks to whoami; tests that care request the mock."""


async def test_initial_setup_sends_exactly_one_report(
    hass: HomeAssistant, mock_report: AsyncMock, pv_states: None
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=PV_INPUT
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    entry = result["result"]
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert mock_report.await_count == 1
    slug = entry.title.lower()
    assert hass.states.get(f"sensor.{slug}_status").state == "ok"
    assert hass.states.get(f"sensor.{slug}_last_error").state == "unknown"


async def test_options_change_sends_exactly_one_report(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_report.await_count == 1
    hass.states.async_set("sensor.pv_total", "500", {"unit_of_measurement": "W"})

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_PV_SENSORS: ["sensor.pv_total"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # One for the options flow's own validation, none extra for the reload.
    assert mock_report.await_count == 2
    assert hass.states.get("sensor.test_plant_status").state == "ok"
    assert hass.states.get("sensor.test_plant_reported_power").state == "500"
