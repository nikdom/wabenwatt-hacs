"""Minimal client for the Wabenwatt report endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import REPORT_URL, REQUEST_TIMEOUT_SECONDS, WHOAMI_URL


class WabenwattError(Exception):
    """Base class for report failures."""


class CannotConnectError(WabenwattError):
    """Network failure, timeout or an unexpected server response."""


class InvalidTokenError(WabenwattError):
    """401: the plant token is unknown or revoked."""


class RateLimitedError(WabenwattError):
    """429: too many requests for this plant."""


class ReportRejectedError(WabenwattError):
    """A 4xx answer carrying an API error code (REPORT_REJECTED, ...)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlantInfo:
    """What the token implies about its plant; the API sends nothing else."""

    plant_id: str
    name: str
    reports_battery_separately: bool


class WabenwattClient:
    """Talks to the API on behalf of one plant token."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        url: str = REPORT_URL,
        whoami_url: str = WHOAMI_URL,
    ) -> None:
        self._session = session
        self._token = token
        self._url = url
        self._whoami_url = whoami_url

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def report(
        self, *, pv_power_w: int, battery_power_w: int | None = None
    ) -> None:
        """Send one report; raises a WabenwattError subclass on failure."""
        payload: dict[str, int]
        if battery_power_w is None:
            payload = {"powerW": pv_power_w}
        else:
            payload = {"pvPowerW": pv_power_w, "batteryPowerW": battery_power_w}

        try:
            async with self._session.post(
                self._url,
                json=payload,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                if response.status == 204:
                    return
                if response.status == 401:
                    raise InvalidTokenError
                if response.status == 429:
                    raise RateLimitedError
                code, message = await _read_error(response)
                if 400 <= response.status < 500:
                    raise ReportRejectedError(response.status, code, message)
                raise CannotConnectError(f"unexpected status {response.status} {code}")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnectError(str(err) or type(err).__name__) from err

    async def whoami(self) -> PlantInfo:
        """Return the plant this token reports for.

        Lives on the general API host, not the ingest host; an API without the
        endpoint answers 404, which surfaces as CannotConnectError so callers
        can treat the lookup as optional.
        """
        try:
            async with self._session.get(
                self._whoami_url,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                if response.status == 401:
                    raise InvalidTokenError
                if response.status == 429:
                    raise RateLimitedError
                if response.status != 200:
                    raise CannotConnectError(f"unexpected status {response.status}")
                body: Any = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise CannotConnectError(str(err) or type(err).__name__) from err
        try:
            return PlantInfo(
                plant_id=str(body["plantId"]),
                name=str(body["name"]),
                reports_battery_separately=bool(body["reportsBatterySeparately"]),
            )
        except (KeyError, TypeError) as err:
            raise CannotConnectError("malformed whoami response") from err


async def _read_error(response: aiohttp.ClientResponse) -> tuple[str, str]:
    """Extract code/message from the API's error envelope, tolerating any body."""
    try:
        body: Any = await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        return "UNKNOWN", ""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "UNKNOWN", ""
    return str(error.get("code") or "UNKNOWN"), str(error.get("message") or "")
