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
BATTERY_PAGE_URL: Final = "https://wabenwatt.de/app/batteries/{battery_id}"
APP_URL: Final = "https://wabenwatt.de/app"
REPORT_INTERVAL: Final = timedelta(seconds=60)
REQUEST_TIMEOUT_SECONDS: Final = 15

CONF_SOURCE_TYPE: Final = "source_type"
# Known when whoami answered at setup; only used to link the device page, never
# sent with a report (the token identifies the device).
CONF_PLANT_ID: Final = "plant_id"
CONF_BATTERY_ID: Final = "battery_id"
CONF_PV_SENSORS: Final = "pv_sensors"
# Battery device (source type "battery"): its power sensor, the sign option, and
# the optional state of charge.
CONF_BATTERY_SENSOR: Final = "battery_sensor"
CONF_BATTERY_INVERT: Final = "battery_invert"
CONF_SOC_SENSOR: Final = "soc_sensor"

SOURCE_TYPE_PV: Final = "pv"
SOURCE_TYPE_BATTERY: Final = "battery"
# The type step of the config flow is skipped while there is exactly one type.
# Every entry stores its type, so adding one never migrates existing entries.
SOURCE_TYPES: Final[tuple[str, ...]] = (SOURCE_TYPE_PV, SOURCE_TYPE_BATTERY)

# whoami's deviceType is NOT the same vocabulary as the source types above: the
# API calls a PV plant "plant" (docs/03-api.md), while the config flow's step is
# "pv". Comparing them directly made every plant token look like neither type,
# so both forms rejected it with opposite explanations (user report 2026-09-02).
# Unknown values stay unmapped on purpose — a token whose type we cannot name
# must not silently pass a type check.
DEVICE_TYPE_BY_API_VALUE: Final[dict[str, str]] = {
    "plant": SOURCE_TYPE_PV,
    "battery": SOURCE_TYPE_BATTERY,
}

DEFAULT_NAME: Final = "Wabenwatt"

# API error codes the integration reacts to by name (docs/04-reporting.md).
ERROR_BATTERY_NOT_SUPPORTED: Final = "BATTERY_NOT_SUPPORTED"

# Percent, for the optional state-of-charge sensor of a battery device.
PERCENT_UNITS: Final[frozenset[str]] = frozenset({"%"})
