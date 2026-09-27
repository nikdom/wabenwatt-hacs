"""Grid meter: flow, reading rules and the reporting cycle (0.5.0)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.wabenwatt.const import (
    CONF_EXPORT_ENERGY_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_GRID_INVERT,
    CONF_GRID_SENSOR,
    CONF_IMPORT_ENERGY_SENSOR,
    CONF_METER_ID,
    CONF_SITE_ID,
    CONF_SOURCE_TYPE,
    DOMAIN,
    NOT_CONFIGURED,
    SOURCE_TYPE_METER,
)
from custom_components.wabenwatt.readings import (
    MeterReading,
    SensorNotEnergyError,
    SensorNotPowerError,
    SensorUnavailableError,
    read_meter,
)

from .conftest import BATTERY, METER, METER_ID, METER_TOKEN, PLANT, SITE_ID

SINGLE_INPUT: dict[str, Any] = {
    CONF_API_TOKEN: METER_TOKEN,
    CONF_GRID_SENSOR: "sensor.grid_power",
    CONF_IMPORT_ENERGY_SENSOR: "sensor.grid_import_total",
    CONF_EXPORT_ENERGY_SENSOR: "sensor.grid_export_total",
}


@pytest.fixture(autouse=True)
def _whoami_answers_meter(mock_whoami: AsyncMock) -> None:
    mock_whoami.return_value = METER


async def _start_meter_flow(hass: HomeAssistant) -> config_entries.ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_TYPE_METER}
    )


async def _submit(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> config_entries.ConfigFlowResult:
    result = await _start_meter_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )
    await hass.async_block_till_done()
    return result


def _read(hass: HomeAssistant, **overrides: Any) -> MeterReading:
    kwargs: dict[str, Any] = {
        "grid_sensor": "sensor.grid_power",
        "grid_invert": False,
        "import_sensor": None,
        "export_sensor": None,
        "import_energy_sensor": None,
        "export_energy_sensor": None,
    }
    return read_meter(hass, **(kwargs | overrides))


# --- config flow -----------------------------------------------------------


async def test_meter_with_one_signed_sensor_creates_its_entry(
    hass: HomeAssistant, mock_report_meter: AsyncMock, meter_states: None
) -> None:
    result = await _start_meter_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "meter"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=SINGLE_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hausanschluss"
    assert result["data"] == {
        CONF_SOURCE_TYPE: SOURCE_TYPE_METER,
        CONF_API_TOKEN: METER_TOKEN,
        CONF_METER_ID: METER_ID,
        CONF_SITE_ID: SITE_ID,
    }
    assert result["options"] == {
        CONF_GRID_SENSOR: "sensor.grid_power",
        CONF_GRID_INVERT: False,
        CONF_IMPORT_ENERGY_SENSOR: "sensor.grid_import_total",
        CONF_EXPORT_ENERGY_SENSOR: "sensor.grid_export_total",
    }
    # Negative stays negative (export), registers converted from kWh to Wh.
    assert mock_report_meter.call_args_list[0].kwargs == {
        "grid_power_w": -1234,
        "import_energy_wh": 4567891,
        "export_energy_wh": 1234500,
    }
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    # The flow's own report seeds the coordinator; no second one.
    assert mock_report_meter.await_count == 1


async def test_meter_with_import_and_export_sensors(
    hass: HomeAssistant, mock_report_meter: AsyncMock
) -> None:
    """Form 2: two non-negative sensors, reported as import minus export."""
    hass.states.async_set("sensor.import_power", "0.25", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.export_power", "0", {"unit_of_measurement": "W"})

    result = await _submit(
        hass,
        {
            CONF_API_TOKEN: METER_TOKEN,
            CONF_GRID_IMPORT_SENSOR: "sensor.import_power",
            CONF_GRID_EXPORT_SENSOR: "sensor.export_power",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # No sign option in this form; its direction lives in the field names.
    assert result["options"] == {
        CONF_GRID_IMPORT_SENSOR: "sensor.import_power",
        CONF_GRID_EXPORT_SENSOR: "sensor.export_power",
    }
    assert mock_report_meter.call_args_list[0].kwargs == {
        "grid_power_w": 250,
        "import_energy_wh": NOT_CONFIGURED,
        "export_energy_wh": NOT_CONFIGURED,
    }


@pytest.mark.parametrize(
    "power_fields",
    [
        {},
        {CONF_GRID_IMPORT_SENSOR: "sensor.grid_power"},
        {CONF_GRID_EXPORT_SENSOR: "sensor.grid_power"},
        {
            CONF_GRID_SENSOR: "sensor.grid_power",
            CONF_GRID_IMPORT_SENSOR: "sensor.grid_power",
        },
        {
            CONF_GRID_SENSOR: "sensor.grid_power",
            CONF_GRID_IMPORT_SENSOR: "sensor.grid_power",
            CONF_GRID_EXPORT_SENSOR: "sensor.grid_power",
        },
    ],
)
async def test_exactly_one_grid_power_form_is_required(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    mock_whoami: AsyncMock,
    meter_states: None,
    power_fields: dict[str, str],
) -> None:
    result = await _submit(hass, {CONF_API_TOKEN: METER_TOKEN, **power_fields})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "grid_power_form"}
    # Checked locally, before anything goes over the network.
    mock_whoami.assert_not_called()
    mock_report_meter.assert_not_called()


@pytest.mark.parametrize("device", [PLANT, BATTERY])
async def test_other_device_tokens_on_the_meter_form_are_caught(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    mock_whoami: AsyncMock,
    meter_states: None,
    device: Any,
) -> None:
    mock_whoami.return_value = device
    result = await _submit(hass, SINGLE_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_TOKEN: f"token_is_{device.device_type}"}
    mock_report_meter.assert_not_called()


@pytest.mark.parametrize("unit", ["%", "kWh", "A"])
async def test_non_power_grid_sensor_is_refused(
    hass: HomeAssistant, mock_report_meter: AsyncMock, unit: str
) -> None:
    hass.states.async_set("sensor.grid_power", "12", {"unit_of_measurement": unit})
    result = await _submit(
        hass, {CONF_API_TOKEN: METER_TOKEN, CONF_GRID_SENSOR: "sensor.grid_power"}
    )

    assert result["errors"] == {"base": "sensor_not_power"}
    assert result["description_placeholders"] == {
        "entity_id": "sensor.grid_power",
        "unit": unit,
    }
    mock_report_meter.assert_not_called()


@pytest.mark.parametrize(
    ("field", "unit", "shown"),
    [
        (CONF_IMPORT_ENERGY_SENSOR, "W", "W"),
        (CONF_EXPORT_ENERGY_SENSOR, None, "—"),
    ],
)
async def test_non_energy_register_is_refused_on_its_field(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    meter_states: None,
    field: str,
    unit: str | None,
    shown: str,
) -> None:
    attributes = {} if unit is None else {"unit_of_measurement": unit}
    hass.states.async_set("sensor.wrong_register", "1000", attributes)
    result = await _submit(hass, {**SINGLE_INPUT, field: "sensor.wrong_register"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: "sensor_not_energy"}
    assert result["description_placeholders"] == {
        "entity_id": "sensor.wrong_register",
        "unit": shown,
    }
    mock_report_meter.assert_not_called()


async def test_unavailable_register_blocks_setup(
    hass: HomeAssistant, mock_report_meter: AsyncMock, meter_states: None
) -> None:
    """At runtime it would only become null — at setup it is the one chance to
    catch a wrongly picked entity."""
    hass.states.async_set("sensor.grid_import_total", "unavailable")
    result = await _submit(hass, SINGLE_INPUT)

    assert result["errors"] == {"base": "sensor_unavailable"}
    assert result["description_placeholders"] == {
        "entity_id": "sensor.grid_import_total"
    }
    mock_report_meter.assert_not_called()


async def test_options_flow_switches_to_two_sensors(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    meter_states: None,
    meter_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(meter_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set("sensor.import_power", "100", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.export_power", "600", {"unit_of_measurement": "W"})

    result = await hass.config_entries.options.async_init(meter_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_GRID_IMPORT_SENSOR: "sensor.import_power",
            CONF_GRID_EXPORT_SENSOR: "sensor.export_power",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert meter_entry.options == {
        CONF_GRID_IMPORT_SENSOR: "sensor.import_power",
        CONF_GRID_EXPORT_SENSOR: "sensor.export_power",
    }
    assert mock_report_meter.call_args.kwargs == {
        "grid_power_w": -500,
        "import_energy_wh": NOT_CONFIGURED,
        "export_energy_wh": NOT_CONFIGURED,
    }
    assert hass.states.get("sensor.hausanschluss_reported_grid_power").state == "-500"


async def test_reauth_keeps_the_meter_and_its_site(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    meter_states: None,
    meter_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(meter_entry.entry_id)
    await hass.async_block_till_done()

    result = await meter_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_API_TOKEN: "new-meter-token"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert meter_entry.data[CONF_API_TOKEN] == "new-meter-token"
    assert meter_entry.data[CONF_METER_ID] == METER_ID
    assert meter_entry.data[CONF_SITE_ID] == SITE_ID
    assert meter_entry.data[CONF_SOURCE_TYPE] == SOURCE_TYPE_METER


# --- reading rules ---------------------------------------------------------


async def test_signed_value_keeps_its_sign(hass: HomeAssistant) -> None:
    """Unlike PV, negative is a measurement (export), never clamped."""
    hass.states.async_set("sensor.grid_power", "-0.8", {"unit_of_measurement": "kW"})
    assert _read(hass).grid_power_w == -800

    hass.states.async_set("sensor.grid_power", "412.6", {"unit_of_measurement": "W"})
    assert _read(hass).grid_power_w == 413


async def test_zero_is_a_real_value(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.grid_power", "0", {"unit_of_measurement": "W"})
    assert _read(hass).grid_power_w == 0


async def test_unitless_power_is_watts(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.grid_power", "-37")
    assert _read(hass).grid_power_w == -37


async def test_invert_flips_the_sign(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.grid_power", "700", {"unit_of_measurement": "W"})
    assert _read(hass, grid_invert=True).grid_power_w == -700


async def test_two_sensors_report_the_difference(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.import_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.export_power", "1.5", {"unit_of_measurement": "kW"})
    reading = _read(
        hass,
        grid_sensor=None,
        import_sensor="sensor.import_power",
        export_sensor="sensor.export_power",
    )
    assert reading.grid_power_w == -1500


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
async def test_unavailable_power_sensor_means_no_reading(
    hass: HomeAssistant, state: str
) -> None:
    hass.states.async_set("sensor.import_power", "200", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.export_power", state)
    with pytest.raises(SensorUnavailableError) as excinfo:
        _read(
            hass,
            grid_sensor=None,
            import_sensor="sensor.import_power",
            export_sensor="sensor.export_power",
        )
    assert excinfo.value.entity_id == "sensor.export_power"


async def test_energy_power_unit_on_the_grid_sensor_is_refused(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set("sensor.grid_power", "5", {"unit_of_measurement": "kWh"})
    with pytest.raises(SensorNotPowerError):
        _read(hass)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("812345", "Wh", 812345),
        ("812.3456", "kWh", 812346),
        ("0.5", "MWh", 500000),
        ("0", "kWh", 0),
    ],
)
async def test_registers_are_converted_to_watt_hours(
    hass: HomeAssistant, value: str, unit: str, expected: int
) -> None:
    hass.states.async_set("sensor.grid_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.register", value, {"unit_of_measurement": unit})
    reading = _read(hass, import_energy_sensor="sensor.register")
    assert reading.import_energy_wh == expected
    assert reading.export_energy_wh is NOT_CONFIGURED


@pytest.mark.parametrize(
    ("state", "unit"),
    [("unavailable", "kWh"), ("unknown", "kWh"), ("-3", "kWh"), ("nan", "kWh")],
)
async def test_register_without_a_value_becomes_null(
    hass: HomeAssistant, state: str, unit: str
) -> None:
    """The power value carries the report; a missing register does not stop it."""
    hass.states.async_set("sensor.grid_power", "-20", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.register", state, {"unit_of_measurement": unit})
    reading = _read(
        hass,
        import_energy_sensor="sensor.register",
        export_energy_sensor="sensor.missing_entity",
    )
    assert reading == MeterReading(
        grid_power_w=-20, import_energy_wh=None, export_energy_wh=None
    )


async def test_register_in_the_wrong_unit_is_an_error(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.grid_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.register", "100", {"unit_of_measurement": "W"})
    with pytest.raises(SensorNotEnergyError):
        _read(hass, import_energy_sensor="sensor.register")


# --- reporting cycle -------------------------------------------------------


async def _tick(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()


async def test_meter_reports_and_exposes_grid_power(
    hass: HomeAssistant,
    mock_report: AsyncMock,
    mock_report_meter: AsyncMock,
    meter_states: None,
    meter_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(meter_entry.entry_id)
    await hass.async_block_till_done()

    assert meter_entry.state is ConfigEntryState.LOADED
    mock_report_meter.assert_awaited_once_with(
        grid_power_w=-1234, import_energy_wh=4567891, export_energy_wh=1234500
    )
    mock_report.assert_not_called()
    grid = hass.states.get("sensor.hausanschluss_reported_grid_power")
    assert grid.state == "-1234"
    assert grid.attributes["device_class"] == "power"
    assert grid.attributes["unit_of_measurement"] == "W"
    assert hass.states.get("sensor.hausanschluss_status").state == "ok"
    assert hass.states.get("sensor.hausanschluss_last_report").state != "unknown"
    assert hass.states.get("sensor.hausanschluss_last_error").state == "unknown"
    # Nothing of the other types.
    assert hass.states.get("sensor.hausanschluss_reported_power") is None
    assert hass.states.get("sensor.hausanschluss_reported_battery_power") is None


async def test_missing_register_is_reported_as_null(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    meter_states: None,
    meter_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(meter_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set("sensor.grid_export_total", "unavailable")

    await _tick(hass)

    assert mock_report_meter.call_args.kwargs == {
        "grid_power_w": -1234,
        "import_energy_wh": 4567891,
        "export_energy_wh": None,
    }
    assert hass.states.get("sensor.hausanschluss_status").state == "ok"


async def test_unavailable_grid_sensor_skips_the_report(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    meter_states: None,
    meter_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(meter_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set("sensor.grid_power", "unknown")

    await _tick(hass)

    assert mock_report_meter.await_count == 1
    status = hass.states.get("sensor.hausanschluss_status")
    assert status.state == "sensor_unavailable"
    assert status.attributes["blocking_entity"] == "sensor.grid_power"


async def test_meter_device_links_to_its_page(
    hass: HomeAssistant,
    mock_report_meter: AsyncMock,
    meter_states: None,
    meter_entry: MockConfigEntry,
) -> None:
    assert await hass.config_entries.async_setup(meter_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, meter_entry.entry_id), meter_entry.entry_id
    )
    assert device is not None
    assert device.configuration_url == f"https://wabenwatt.de/app/meters/{METER_ID}"
    assert device.model == SOURCE_TYPE_METER.upper()
