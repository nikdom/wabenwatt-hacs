"""Home battery: one signed sensor OR separate charge and discharge sensors."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wabenwatt.const import (
    CONF_BATTERY_CHARGE_SENSOR,
    CONF_BATTERY_DISCHARGE_SENSOR,
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SENSOR,
    CONF_SOC_SENSOR,
    DOMAIN,
    SOURCE_TYPE_BATTERY,
)
from custom_components.wabenwatt.readings import (
    BatteryReading,
    SensorUnavailableError,
    read_battery,
)

from .conftest import BATTERY, BATTERY_TOKEN


@pytest.fixture(autouse=True)
def _whoami_answers_battery(mock_whoami: AsyncMock) -> None:
    mock_whoami.return_value = BATTERY


@pytest.fixture
def split_states(hass: HomeAssistant) -> None:
    """A battery charging with 1.2 kW, reported on two sensors."""
    hass.states.async_set("sensor.charge_power", "1.2", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.discharge_power", "0", {"unit_of_measurement": "W"})


async def _submit(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> config_entries.ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_TYPE_BATTERY}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )
    await hass.async_block_till_done()
    return result


def _read(hass: HomeAssistant, **overrides: Any) -> BatteryReading:
    kwargs: dict[str, Any] = {
        "battery_sensor": None,
        "battery_invert": False,
        "charge_sensor": "sensor.charge_power",
        "discharge_sensor": "sensor.discharge_power",
        "soc_sensor": None,
    }
    return read_battery(hass, **(kwargs | overrides))


@pytest.mark.parametrize(
    ("charge", "discharge", "expected"),
    [
        ("1200", "0", -1200),
        ("0", "800", 800),
        # Some integrations keep charge power negative; the field names the
        # direction, so only the absolute value counts.
        ("-1200", "0", -1200),
        ("0", "-800", 800),
        ("0", "0", 0),
    ],
)
def test_pair_is_discharge_minus_charge_in_absolute_values(
    hass: HomeAssistant, charge: str, discharge: str, expected: int
) -> None:
    hass.states.async_set("sensor.charge_power", charge, {"unit_of_measurement": "W"})
    hass.states.async_set(
        "sensor.discharge_power", discharge, {"unit_of_measurement": "W"}
    )

    assert _read(hass).battery_power_w == expected


def test_sign_option_does_not_touch_the_pair(
    hass: HomeAssistant, split_states: None
) -> None:
    """A stale invert flag from the single-sensor form must not flip the pair."""
    assert _read(hass, battery_invert=True).battery_power_w == -1200


def test_one_missing_half_means_no_report(
    hass: HomeAssistant, split_states: None
) -> None:
    hass.states.async_set("sensor.discharge_power", "unavailable")

    with pytest.raises(SensorUnavailableError):
        _read(hass)


def test_single_sensor_still_honours_the_sign_option(
    hass: HomeAssistant, battery_states: None
) -> None:
    reading = _read(
        hass,
        battery_sensor="sensor.battery_power",
        battery_invert=True,
        charge_sensor=None,
        discharge_sensor=None,
        soc_sensor="sensor.battery_soc",
    )

    assert reading == BatteryReading(battery_power_w=-350, soc_percent=62)


async def test_flow_with_two_sensors(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    split_states: None,
    battery_states: None,
) -> None:
    result = await _submit(
        hass,
        {
            CONF_API_TOKEN: BATTERY_TOKEN,
            CONF_BATTERY_INVERT: True,
            CONF_BATTERY_CHARGE_SENSOR: "sensor.charge_power",
            CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge_power",
            CONF_SOC_SENSOR: "sensor.battery_soc",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The sign option belongs to the single sensor and is not stored here.
    assert result["options"] == {
        CONF_BATTERY_CHARGE_SENSOR: "sensor.charge_power",
        CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge_power",
        CONF_SOC_SENSOR: "sensor.battery_soc",
    }
    assert mock_report_battery.call_args_list[0].kwargs == {
        "battery_power_w": -1200,
        "soc_percent": 62,
    }


@pytest.mark.parametrize(
    "power_fields",
    [
        {},
        {CONF_BATTERY_CHARGE_SENSOR: "sensor.charge_power"},
        {CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge_power"},
        {
            CONF_BATTERY_SENSOR: "sensor.battery_power",
            CONF_BATTERY_CHARGE_SENSOR: "sensor.charge_power",
        },
        {
            CONF_BATTERY_SENSOR: "sensor.battery_power",
            CONF_BATTERY_CHARGE_SENSOR: "sensor.charge_power",
            CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge_power",
        },
    ],
)
async def test_exactly_one_battery_power_form_is_required(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    mock_whoami: AsyncMock,
    split_states: None,
    battery_states: None,
    power_fields: dict[str, str],
) -> None:
    result = await _submit(hass, {CONF_API_TOKEN: BATTERY_TOKEN, **power_fields})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "battery_power_form"}
    mock_whoami.assert_not_called()
    mock_report_battery.assert_not_called()


async def test_existing_entry_keeps_reporting_unchanged(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    battery_states: None,
    battery_entry: MockConfigEntry,
) -> None:
    """Entries from before 0.6.0 hold only battery_sensor: no migration."""
    assert await hass.config_entries.async_setup(battery_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_report_battery.call_args.kwargs == {
        "battery_power_w": 350,
        "soc_percent": 62,
    }


async def test_options_flow_switches_to_two_sensors(
    hass: HomeAssistant,
    mock_report_battery: AsyncMock,
    battery_states: None,
    split_states: None,
    battery_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(battery_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(battery_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_BATTERY_CHARGE_SENSOR: "sensor.charge_power",
            CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge_power",
            CONF_SOC_SENSOR: "sensor.battery_soc",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert battery_entry.options == {
        CONF_BATTERY_CHARGE_SENSOR: "sensor.charge_power",
        CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge_power",
        CONF_SOC_SENSOR: "sensor.battery_soc",
    }
    assert mock_report_battery.call_args.kwargs == {
        "battery_power_w": -1200,
        "soc_percent": 62,
    }
