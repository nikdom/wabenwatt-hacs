"""Sends one report per minute and keeps the outcome for the entities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
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

STATUS_OK = "ok"
STATUS_SENSOR_UNAVAILABLE = "sensor_unavailable"
STATUS_ERROR = "error"
STATUSES = [STATUS_OK, STATUS_SENSOR_UNAVAILABLE, STATUS_ERROR]

ERROR_SENSOR_NOT_POWER = "SENSOR_NOT_POWER"
ERROR_RATE_LIMITED = "RATE_LIMITED"
ERROR_CANNOT_CONNECT = "CANNOT_CONNECT"


@dataclass(frozen=True)
class ReportError:
    """The most recent failure, kept until the next one replaces it."""

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

        return ReporterState(
            status=STATUS_OK,
            last_report_at=now,
            last_reading=reading,
            last_error=previous.last_error,
        )

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
