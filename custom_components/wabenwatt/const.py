"""Constants for the Wabenwatt integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "wabenwatt"

# Public ingest host; the endpoint answers 204 without a body on success.
REPORT_URL: Final = "https://reports.wabenwatt.de/v1"
REPORT_INTERVAL: Final = timedelta(seconds=60)
REQUEST_TIMEOUT_SECONDS: Final = 15

CONF_SOURCE_TYPE: Final = "source_type"
CONF_PV_SENSORS: Final = "pv_sensors"
CONF_BATTERY_SENSOR: Final = "battery_sensor"
CONF_BATTERY_INVERT: Final = "battery_invert"

SOURCE_TYPE_PV: Final = "pv"
# The type step of the config flow is skipped while there is exactly one type.
# Adding a type here makes the menu appear; existing entries keep working
# because every entry stores its type.
SOURCE_TYPES: Final[tuple[str, ...]] = (SOURCE_TYPE_PV,)

DEFAULT_NAME: Final = "Wabenwatt"

# API error codes the integration reacts to by name (docs/04-reporting.md).
ERROR_BATTERY_NOT_SUPPORTED: Final = "BATTERY_NOT_SUPPORTED"
