"""Sends one report per minute and keeps the outcome for the entities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    CannotConnectError,
    InvalidTokenError,
    RateLimitedError,
    ReportRejectedError,
    WabenwattClient,
)
from .const import (
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SENSOR,
    CONF_PV_SENSORS,
    DOMAIN,
    REPORT_INTERVAL,
)
from .readings import (
    PlantReading,
    SensorNotPowerError,
    SensorUnavailableError,
    read_plant,
)

_LOGGER = logging.getLogger(__name__)

# How long a pending report (see stash_first_report) stays valid. Generous on
# purpose: it only guards against an unusually slow setup, not against the
# normal case, where it is picked up within milliseconds.
_PENDING_REPORT_MAX_AGE = timedelta(minutes=1)
_PENDING_REPORTS = "wabenwatt_pending_reports"

STATUS_OK = "ok"
STATUS_SENSOR_UNAVAILABLE = "sensor_unavailable"
STATUS_ERROR = "error"
STATUSES = [STATUS_OK, STATUS_SENSOR_UNAVAILABLE, STATUS_ERROR]

ERROR_SENSOR_NOT_POWER = "SENSOR_NOT_POWER"
ERROR_RATE_LIMITED = "RATE_LIMITED"
ERROR_CANNOT_CONNECT = "CANNOT_CONNECT"


@dataclass(frozen=True)
class ReportError:
    """The most recent failure. Cleared by the next successful report, same
    as the server's own report:lasterror key (docs/04-reporting.md) — a
    sticky error would misreport a one-off blip (e.g. the setup collision
    below) as an ongoing problem forever."""

    code: str
    message: str
    at: datetime


@dataclass(frozen=True)
class ReporterState:
    """Outcome of the last attempt plus the last successful report."""

    status: str = STATUS_OK
    last_report_at: datetime | None = None
    last_reading: PlantReading | None = None
    last_error: ReportError | None = None
    # Entity that blocked the last attempt (unavailable or not a power sensor).
    blocking_entity: str | None = None


def stash_first_report(
    hass: HomeAssistant, unique_id: str, reading: PlantReading, at: datetime
) -> None:
    """Remember a report the config/options flow already sent as its
    validation, so setup can seed the coordinator from it instead of sending
    a second one. The server rejects two reports for the same plant within
    REPORT_MIN_INTERVAL_SECONDS (25s, docs/04-reporting.md) with
    RATE_LIMITED — without this, a plain config_entry_first_refresh() right
    after the flow's own report hit that gate on essentially every setup and
    every sensor change."""
    hass.data.setdefault(_PENDING_REPORTS, {})[unique_id] = (reading, at)


def pop_pending_report(
    hass: HomeAssistant, unique_id: str | None
) -> tuple[PlantReading, datetime] | None:
    """Take back a stashed report, if any and not stale."""
    if unique_id is None:
        return None
    pending = hass.data.get(_PENDING_REPORTS, {}).pop(unique_id, None)
    if pending is None:
        return None
    _reading, at = pending
    if dt_util.utcnow() - at > _PENDING_REPORT_MAX_AGE:
        return None
    return pending


class WabenwattCoordinator(DataUpdateCoordinator[ReporterState]):
    """Reads the configured sensors every minute and reports them."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=REPORT_INTERVAL,
        )
        self.client = WabenwattClient(
            async_get_clientsession(hass), entry.data[CONF_API_TOKEN]
        )

    @property
    def pv_sensors(self) -> list[str]:
        return list(self.config_entry.options[CONF_PV_SENSORS])

    @property
    def battery_sensor(self) -> str | None:
        return self.config_entry.options.get(CONF_BATTERY_SENSOR) or None

    @property
    def battery_invert(self) -> bool:
        return bool(self.config_entry.options.get(CONF_BATTERY_INVERT, False))

    async def _async_update_data(self) -> ReporterState:
        previous = self.data or ReporterState()
        now = dt_util.utcnow()

        try:
            reading = read_plant(
                self.hass, self.pv_sensors, self.battery_sensor, self.battery_invert
            )
        except SensorUnavailableError as err:
            _LOGGER.debug("%s: skipping report, %s", self.name, err)
            return replace(
                previous,
                status=STATUS_SENSOR_UNAVAILABLE,
                blocking_entity=err.entity_id,
            )
        except SensorNotPowerError as err:
            return self._failed(
                previous, ERROR_SENSOR_NOT_POWER, str(err), now, blocking=err.entity_id
            )

        try:
            await self.client.report(
                pv_power_w=reading.pv_power_w, battery_power_w=reading.battery_power_w
            )
        except InvalidTokenError as err:
            raise ConfigEntryAuthFailed("plant token unknown or revoked") from err
        except RateLimitedError:
            return self._failed(previous, ERROR_RATE_LIMITED, "too many reports", now)
        except ReportRejectedError as err:
            return self._failed(previous, err.code, err.message, now)
        except CannotConnectError as err:
            return self._failed(previous, ERROR_CANNOT_CONNECT, str(err), now)

        return ReporterState(status=STATUS_OK, last_report_at=now, last_reading=reading)

    def _failed(
        self,
        previous: ReporterState,
        code: str,
        message: str,
        now: datetime,
        blocking: str | None = None,
    ) -> ReporterState:
        # Warn once per outage; the status entity carries the ongoing state.
        log = _LOGGER.warning if previous.status != STATUS_ERROR else _LOGGER.debug
        log("%s: report failed with %s: %s", self.name, code, message)
        return replace(
            previous,
            status=STATUS_ERROR,
            last_error=ReportError(code=code, message=message, at=now),
            blocking_entity=blocking,
        )
