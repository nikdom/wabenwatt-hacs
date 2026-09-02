"""Constants for the Wabenwatt integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "wabenwatt"

# Public ingest host; the endpoint answers 204 without a body on success.
REPORT_URL: Final = "https://reports.wabenwatt.de/v1"
# The plant behind a token. Deliberately on the general API host: the ingest
# host is the path that scales with the fleet and may move, a one-off setup
# lookup does not belong there.
WHOAMI_URL: Final = "https://api.wabenwatt.de/api/v1/report/whoami"
PLANT_PAGE_URL: Final = "https://wabenwatt.de/app/plants/{plant_id}"
APP_URL: Final = "https://wabenwatt.de/app"
REPORT_INTERVAL: Final = timedelta(seconds=60)
REQUEST_TIMEOUT_SECONDS: Final = 15

CONF_SOURCE_TYPE: Final = "source_type"
# Known when whoami answered at setup; only used to link the plant page, never
# sent with a report (the token identifies the plant).
CONF_PLANT_ID: Final = "plant_id"
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
