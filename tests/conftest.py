"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_API_TOKEN, CONF_NAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wabenwatt.config_flow import token_unique_id
from custom_components.wabenwatt.const import (
    CONF_BATTERY_INVERT,
    CONF_PV_SENSORS,
    CONF_SOURCE_TYPE,
    DOMAIN,
    SOURCE_TYPE_PV,
)

pytest_plugins = "pytest_homeassistant_custom_component"

TOKEN = "plant-token-123"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make the custom_components directory visible to the loader."""


@pytest.fixture
def mock_report() -> Generator[AsyncMock]:
    """Replace the HTTP call; the default is a successful 204."""
    with patch(
        "custom_components.wabenwatt.api.WabenwattClient.report",
        new_callable=AsyncMock,
    ) as report:
        yield report


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
            CONF_NAME: "Test plant",
            CONF_API_TOKEN: TOKEN,
        },
        options={
            CONF_PV_SENSORS: ["sensor.pv_string_1", "sensor.pv_string_2"],
            CONF_BATTERY_INVERT: False,
        },
    )
    entry.add_to_hass(hass)
    return entry
