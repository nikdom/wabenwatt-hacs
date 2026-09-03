"""Minimal client for the Wabenwatt report endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    DEVICE_TYPE_BY_API_VALUE,
    REPORT_URL,
    REQUEST_TIMEOUT_SECONDS,
    SOURCE_TYPE_BATTERY,
    WHOAMI_URL,
)


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
class DeviceInfo:
    """What the token implies about its device; the API sends nothing else.

    Since batteries became their own device, whoami answers with a
    `deviceType` and either a plantId or a batteryId. An older API answers
    without the field — treated as a plant, which is what it was.

    `device_type` is already translated into the integration's own vocabulary
    (SOURCE_TYPE_*), never the raw API value — see DEVICE_TYPE_BY_API_VALUE.
    """

    device_type: str
    device_id: str
    name: str


class WabenwattClient:
    """Talks to the API on behalf of one device token."""

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

    async def report(self, *, pv_power_w: int) -> None:
        """Send one PV report; raises a WabenwattError subclass on failure."""
        await self._post({"powerW": pv_power_w})

    async def report_battery(
        self, *, battery_power_w: int, soc_percent: int | None = None
    ) -> None:
        """Send one battery report (negative power = charging)."""
        payload: dict[str, int | None] = {"batteryPowerW": battery_power_w}
        if soc_percent is not None:
            payload["socPercent"] = soc_percent
        await self._post(payload)

    async def _post(self, payload: dict[str, Any]) -> None:
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

    async def whoami(self) -> DeviceInfo:
        """Return the device this token reports for.

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
        # Checked, not assumed: the old code reached straight into the mapping
        # and let TypeError stand in for "not an object". Reading deviceType
        # with .get() first would raise AttributeError instead, which is not
        # caught below — so the shape is verified up front.
        if not isinstance(body, dict):
            raise CannotConnectError("malformed whoami response")
        try:
            # deviceType is absent on an API from before batteries existed;
            # such a token can only be a plant.
            api_value = str(body.get("deviceType") or "plant")
            device_type = DEVICE_TYPE_BY_API_VALUE.get(api_value)
            if device_type is None:
                # A device type this version does not know about. Reporting it
                # as "some other type" is the honest answer; guessing would put
                # the wrong sensors on it.
                raise CannotConnectError(f"unknown device type {api_value!r}")
            device_id = (
                str(body["batteryId"])
                if device_type == SOURCE_TYPE_BATTERY
                else str(body["plantId"])
            )
            return DeviceInfo(
                device_type=device_type,
                device_id=device_id,
                name=str(body["name"]),
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
