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
    mock_report.assert_awaited_once_with(pv_power_w=1242)
    assert hass.states.get("sensor.test_plant_status").state == "ok"
    assert hass.states.get("sensor.test_plant_reported_power").state == "1242"
    assert hass.states.get("sensor.test_plant_last_report").state != "unknown"
    assert hass.states.get("sensor.test_plant_last_error").state == "unknown"
    # A plant reports solar power and nothing else; battery entities belong to
    # a battery device (docs/41-sites-and-batteries.md).
    assert hass.states.get("sensor.test_plant_reported_battery_power") is None
    assert hass.states.get("sensor.test_plant_reported_state_of_charge") is None


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

    mock_report.assert_awaited_once_with(pv_power_w=0)


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


async def test_battery_device_reports_power_and_state_of_charge(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    battery_states: None,
    battery_entry: MockConfigEntry,
) -> None:
    """A battery entry reports through its own endpoint, with its own entities."""
    assert await hass.config_entries.async_setup(battery_entry.entry_id)
    await hass.async_block_till_done()

    assert battery_entry.state is ConfigEntryState.LOADED
    mock_report_battery.assert_awaited_once_with(battery_power_w=350, soc_percent=62)
    assert hass.states.get("sensor.hausakku_reported_battery_power").state == "350"
    assert hass.states.get("sensor.hausakku_reported_state_of_charge").state == "62"
    # A battery has no solar power to report.
    assert hass.states.get("sensor.hausakku_reported_power") is None


async def test_battery_without_soc_sensor_has_no_soc_entity(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    battery_states: None,
    battery_entry: MockConfigEntry,
) -> None:
    """State of charge is optional; without a sensor the entity would sit at
    'unknown' forever, so it is not created at all."""
    hass.config_entries.async_update_entry(
        battery_entry,
        options={
            key: value
            for key, value in battery_entry.options.items()
            if key != "soc_sensor"
        },
    )

    assert await hass.config_entries.async_setup(battery_entry.entry_id)
    await hass.async_block_till_done()

    mock_report_battery.assert_awaited_once_with(battery_power_w=350, soc_percent=None)
    assert hass.states.get("sensor.hausakku_reported_state_of_charge") is None


async def test_battery_sign_can_be_inverted(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    battery_states: None,
    battery_entry: MockConfigEntry,
) -> None:
    """Meters disagree about the direction; wabenwatt wants positive = discharge."""
    hass.config_entries.async_update_entry(
        battery_entry, options={**battery_entry.options, "battery_invert": True}
    )

    assert await hass.config_entries.async_setup(battery_entry.entry_id)
    await hass.async_block_till_done()

    mock_report_battery.assert_awaited_once_with(battery_power_w=-350, soc_percent=62)
