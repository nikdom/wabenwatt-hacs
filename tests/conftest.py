"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wabenwatt.api import DeviceInfo
from custom_components.wabenwatt.config_flow import token_unique_id
from custom_components.wabenwatt.const import (
    CONF_BATTERY_ID,
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SENSOR,
    CONF_EXPORT_ENERGY_SENSOR,
    CONF_GRID_INVERT,
    CONF_GRID_SENSOR,
    CONF_IMPORT_ENERGY_SENSOR,
    CONF_METER_ID,
    CONF_PLANT_ID,
    CONF_PV_SENSORS,
    CONF_SOC_SENSOR,
    CONF_SOURCE_TYPE,
    DOMAIN,
    SOURCE_TYPE_BATTERY,
    SOURCE_TYPE_METER,
    SOURCE_TYPE_PV,
)

pytest_plugins = "pytest_homeassistant_custom_component"

TOKEN = "plant-token-123"
PLANT_ID = "5b7e1c3a-1234-4c9d-8e2f-0a1b2c3d4e5f"
PLANT = DeviceInfo(device_type=SOURCE_TYPE_PV, device_id=PLANT_ID, name="Balkon")

BATTERY_TOKEN = "battery-token-456"
BATTERY_ID = "7c8f2d4b-2345-4d0e-9f30-1b2c3d4e5f60"
BATTERY = DeviceInfo(
    device_type=SOURCE_TYPE_BATTERY, device_id=BATTERY_ID, name="Hausakku"
)

SITE_ID = "3a9d7e21-5678-4b1c-8d2e-2c3d4e5f6071"
METER_TOKEN = "meter-token-789"
METER_ID = "9e1a4f6c-3456-4e1f-a041-2c3d4e5f6071"
METER = DeviceInfo(
    device_type=SOURCE_TYPE_METER,
    device_id=METER_ID,
    name="Hausanschluss",
    site_id=SITE_ID,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make the custom_components directory visible to the loader."""


@pytest.fixture
def mock_report() -> Generator[AsyncMock]:
    """Replace the report call; the default is a successful 204."""
    with patch(
        "custom_components.wabenwatt.api.WabenwattClient.report",
        new_callable=AsyncMock,
    ) as report:
        yield report


@pytest.fixture
def mock_report_battery() -> Generator[AsyncMock]:
    """Replace the battery report call; the default is a successful 204."""
    with patch(
        "custom_components.wabenwatt.api.WabenwattClient.report_battery",
        new_callable=AsyncMock,
    ) as report:
        yield report


@pytest.fixture
def mock_report_meter() -> Generator[AsyncMock]:
    """Replace the meter report call; the default is a successful 204."""
    with patch(
        "custom_components.wabenwatt.api.WabenwattClient.report_meter",
        new_callable=AsyncMock,
    ) as report:
        yield report


@pytest.fixture
def mock_whoami() -> Generator[AsyncMock]:
    """Replace the whoami lookup; the default answers with PLANT."""
    with patch(
        "custom_components.wabenwatt.api.WabenwattClient.whoami",
        new_callable=AsyncMock,
        return_value=PLANT,
    ) as whoami:
        yield whoami


@pytest.fixture
def pv_states(hass: HomeAssistant) -> None:
    """Two string sensors, one in W and one in kW: 742 W + 500 W."""
    hass.states.async_set("sensor.pv_string_1", "742", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.pv_string_2", "0.5", {"unit_of_measurement": "kW"})


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A configured plant, not yet set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test plant",
        unique_id=token_unique_id(TOKEN),
        data={
            CONF_SOURCE_TYPE: SOURCE_TYPE_PV,
            CONF_API_TOKEN: TOKEN,
            CONF_PLANT_ID: PLANT_ID,
        },
        options={
            CONF_PV_SENSORS: ["sensor.pv_string_1", "sensor.pv_string_2"],
            CONF_BATTERY_INVERT: False,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def battery_states(hass: HomeAssistant) -> None:
    """A discharging battery at 62 %."""
    hass.states.async_set("sensor.battery_power", "350", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.battery_soc", "62", {"unit_of_measurement": "%"})


@pytest.fixture
def battery_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A configured home battery, not yet set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hausakku",
        unique_id=token_unique_id(BATTERY_TOKEN),
        data={
            CONF_SOURCE_TYPE: SOURCE_TYPE_BATTERY,
            CONF_API_TOKEN: BATTERY_TOKEN,
            CONF_BATTERY_ID: BATTERY_ID,
        },
        options={
            CONF_BATTERY_SENSOR: "sensor.battery_power",
            CONF_BATTERY_INVERT: False,
            CONF_SOC_SENSOR: "sensor.battery_soc",
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def meter_states(hass: HomeAssistant) -> None:
    """A household exporting 1.2 kW, with both registers in kWh."""
    hass.states.async_set("sensor.grid_power", "-1234.4", {"unit_of_measurement": "W"})
    hass.states.async_set(
        "sensor.grid_import_total", "4567.891", {"unit_of_measurement": "kWh"}
    )
    hass.states.async_set(
        "sensor.grid_export_total", "1234.5", {"unit_of_measurement": "kWh"}
    )


@pytest.fixture
def meter_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A configured grid meter (one signed sensor), not yet set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hausanschluss",
        unique_id=token_unique_id(METER_TOKEN),
        data={
            CONF_SOURCE_TYPE: SOURCE_TYPE_METER,
            CONF_API_TOKEN: METER_TOKEN,
            CONF_METER_ID: METER_ID,
        },
        options={
            CONF_GRID_SENSOR: "sensor.grid_power",
            CONF_GRID_INVERT: False,
            CONF_IMPORT_ENERGY_SENSOR: "sensor.grid_import_total",
            CONF_EXPORT_ENERGY_SENSOR: "sensor.grid_export_total",
        },
    )
    entry.add_to_hass(hass)
    return entry
