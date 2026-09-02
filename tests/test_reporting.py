"""Periodic reporting and the entities that expose it."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.wabenwatt.api import InvalidTokenError, RateLimitedError
from custom_components.wabenwatt.const import DOMAIN


async def _tick(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()


async def test_setup_reports_immediately_and_exposes_entities(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    mock_report.assert_awaited_once_with(pv_power_w=1242, battery_power_w=None)
    assert hass.states.get("sensor.test_plant_status").state == "ok"
    assert hass.states.get("sensor.test_plant_reported_power").state == "1242"
    assert hass.states.get("sensor.test_plant_last_report").state != "unknown"
    assert hass.states.get("sensor.test_plant_last_error").state == "unknown"
    # No battery configured, so no battery entity.
    assert hass.states.get("sensor.test_plant_reported_battery_power") is None


async def test_unavailable_sensor_skips_the_report(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set("sensor.pv_string_2", "unavailable")

    await _tick(hass)

    assert mock_report.await_count == 1
    status = hass.states.get("sensor.test_plant_status")
    assert status.state == "sensor_unavailable"
    assert status.attributes["blocking_entity"] == "sensor.pv_string_2"
    # The last successful value stays visible together with its timestamp.
    assert hass.states.get("sensor.test_plant_reported_power").state == "1242"


async def test_negative_standby_draw_is_reported_as_zero(
    hass: HomeAssistant, mock_report: AsyncMock, config_entry: MockConfigEntry
) -> None:
    hass.states.async_set("sensor.pv_string_1", "-2.4", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.pv_string_2", "0", {"unit_of_measurement": "W"})

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_report.assert_awaited_once_with(pv_power_w=0, battery_power_w=None)


async def test_server_error_shows_up_and_clears_on_recovery(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_report.side_effect = RateLimitedError()
    await _tick(hass)
    assert hass.states.get("sensor.test_plant_status").state == "error"
    last_error = hass.states.get("sensor.test_plant_last_error")
    assert last_error.state == "RATE_LIMITED"
    assert "at" in last_error.attributes

    mock_report.side_effect = None
    await _tick(hass)
    assert hass.states.get("sensor.test_plant_status").state == "ok"
    # Cleared on the next successful report, mirroring the server's own
    # report:lasterror key (docs/04-reporting.md) — a sticky error would
    # misrepresent a one-off blip as an ongoing problem forever.
    assert hass.states.get("sensor.test_plant_last_error").state == "unknown"


async def test_revoked_token_starts_reauth(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_report.side_effect = InvalidTokenError()
    await _tick(hass)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_unload(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    pv_states: None,
    config_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("sensor.test_plant_status").state == "unavailable"
