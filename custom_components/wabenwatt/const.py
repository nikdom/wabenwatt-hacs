"""Constants for the Wabenwatt integration."""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Final

DOMAIN: Final = "wabenwatt"

# Sent as the X-Wabenwatt-Client header so the platform can tell which release
# is installed out there. Home Assistant's own User-Agent stays untouched — it
# carries the HA core version, which is a different and equally useful number.
# Kept in step with manifest.json by test_client_marker.py.
INTEGRATION_VERSION: Final = "0.5.0"
CLIENT_HEADER: Final = "X-Wabenwatt-Client"
CLIENT_MARKER: Final = f"wabenwatt-homeassistant/{INTEGRATION_VERSION}"

# Public ingest host; the endpoint answers 204 without a body on success.
REPORT_URL: Final = "https://reports.wabenwatt.de/v1"
# The plant behind a token. Deliberately on the general API host: the ingest
# host is the path that scales with the fleet and may move, a one-off setup
# lookup does not belong there.
WHOAMI_URL: Final = "https://api.wabenwatt.de/api/v1/report/whoami"
PLANT_PAGE_URL: Final = "https://wabenwatt.de/app/plants/{plant_id}"
BATTERY_PAGE_URL: Final = "https://wabenwatt.de/app/batteries/{battery_id}"
METER_PAGE_URL: Final = "https://wabenwatt.de/app/meters/{meter_id}"
APP_URL: Final = "https://wabenwatt.de/app"
REPORT_INTERVAL: Final = timedelta(seconds=60)
REQUEST_TIMEOUT_SECONDS: Final = 15

CONF_SOURCE_TYPE: Final = "source_type"
# Known when whoami answered at setup; only used to link the device page, never
# sent with a report (the token identifies the device).
CONF_PLANT_ID: Final = "plant_id"
CONF_BATTERY_ID: Final = "battery_id"
CONF_METER_ID: Final = "meter_id"
# The household the device belongs to. Stored for every type as soon as whoami
# names it, so grouping the entries of one site later needs no migration.
CONF_SITE_ID: Final = "site_id"
CONF_PV_SENSORS: Final = "pv_sensors"
# Battery device (source type "battery"): its power sensor, the sign option, and
# the optional state of charge.
CONF_BATTERY_SENSOR: Final = "battery_sensor"
CONF_BATTERY_INVERT: Final = "battery_invert"
CONF_SOC_SENSOR: Final = "soc_sensor"
# Grid meter (source type "meter"): EITHER one signed power sensor (positive =
# import) with its sign option, OR two non-negative sensors for import and
# export power. The register readings (1.8.0/2.8.0) are optional.
CONF_GRID_SENSOR: Final = "grid_sensor"
CONF_GRID_INVERT: Final = "grid_invert"
CONF_GRID_IMPORT_SENSOR: Final = "grid_import_sensor"
CONF_GRID_EXPORT_SENSOR: Final = "grid_export_sensor"
CONF_IMPORT_ENERGY_SENSOR: Final = "import_energy_sensor"
CONF_EXPORT_ENERGY_SENSOR: Final = "export_energy_sensor"

SOURCE_TYPE_PV: Final = "pv"
SOURCE_TYPE_BATTERY: Final = "battery"
SOURCE_TYPE_METER: Final = "meter"
# The type step of the config flow is skipped while there is exactly one type.
# Every entry stores its type, so adding one never migrates existing entries.
SOURCE_TYPES: Final[tuple[str, ...]] = (
    SOURCE_TYPE_PV,
    SOURCE_TYPE_BATTERY,
    SOURCE_TYPE_METER,
)
# What whoami calls a site token. Never a source type: a site token reports
# nothing, it only names a household for the grid signal. Known by name so the
# flow can refuse it with a clear message instead of "unknown device type".
DEVICE_TYPE_SITE: Final = "site"

# whoami's deviceType is NOT the same vocabulary as the source types above: the
# API calls a PV plant "plant" (docs/03-api.md), while the config flow's step is
# "pv". Comparing them directly made every plant token look like neither type,
# so both forms rejected it with opposite explanations (user report 2026-09-02).
# Unknown values stay unmapped on purpose — a token whose type we cannot name
# must not silently pass a type check.
DEVICE_TYPE_BY_API_VALUE: Final[dict[str, str]] = {
    "plant": SOURCE_TYPE_PV,
    "battery": SOURCE_TYPE_BATTERY,
    "meter": SOURCE_TYPE_METER,
    "site": DEVICE_TYPE_SITE,
}

# Where each type keeps its wabenwatt id in the entry data.
DEVICE_ID_CONF_BY_TYPE: Final[dict[str, str]] = {
    SOURCE_TYPE_PV: CONF_PLANT_ID,
    SOURCE_TYPE_BATTERY: CONF_BATTERY_ID,
    SOURCE_TYPE_METER: CONF_METER_ID,
}

DEFAULT_NAME: Final = "Wabenwatt"

# API error codes the integration reacts to by name (docs/04-reporting.md).
ERROR_BATTERY_NOT_SUPPORTED: Final = "BATTERY_NOT_SUPPORTED"

# Percent, for the optional state-of-charge sensor of a battery device.
PERCENT_UNITS: Final[frozenset[str]] = frozenset({"%"})


class NotConfigured(Enum):
    """Marks an optional meter register that has no sensor at all — omitted
    from the report, unlike a configured one without a value (sent as null)."""

    NOT_CONFIGURED = "not_configured"


NOT_CONFIGURED: Final = NotConfigured.NOT_CONFIGURED
