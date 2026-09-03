"""HTTP client: the whoami lookup against a fake endpoint."""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from custom_components.wabenwatt.api import (
    CannotConnectError,
    DeviceInfo,
    InvalidTokenError,
    RateLimitedError,
    WabenwattClient,
)
from custom_components.wabenwatt.const import SOURCE_TYPE_BATTERY, SOURCE_TYPE_PV

# The HA test plugin blocks sockets; these tests talk to a local fake server.
pytestmark = pytest.mark.usefixtures("socket_enabled")

# The API's deviceType vocabulary is NOT the integration's: a PV plant is
# "plant" on the wire and SOURCE_TYPE_PV ("pv") in the config flow. These tests
# assert the translated value on purpose — pinning the raw wire value here is
# what let the config flow compare "plant" against its own "pv" step, so a
# plant token was rejected by BOTH forms with opposite explanations
# (user report 2026-09-02).

PLANT_BODY = {
    "deviceType": "plant",
    "plantId": "5b7e1c3a-1234-4c9d-8e2f-0a1b2c3d4e5f",
    "name": "Balkon Süd",
    "reportsBatterySeparately": True,
}
BATTERY_BODY = {
    "deviceType": "battery",
    "batteryId": "7c8f2d4b-2345-4d0e-9f30-1b2c3d4e5f60",
    "name": "Hausakku",
}


class FakeWhoami:
    """Answers GET /whoami with a configurable status and body."""

    def __init__(self) -> None:
        self.status = 200
        self.body: object = PLANT_BODY
        self.authorization: str | None = None

    async def handle(self, request: web.Request) -> web.Response:
        self.authorization = request.headers.get("Authorization")
        if self.body is None:
            return web.Response(status=self.status)
        return web.json_response(self.body, status=self.status)


@pytest.fixture
async def endpoint() -> tuple[FakeWhoami, TestClient]:
    fake = FakeWhoami()
    app = web.Application()
    app.router.add_get("/whoami", fake.handle)
    async with TestClient(TestServer(app)) as client:
        yield fake, client


def _client(client: TestClient) -> WabenwattClient:
    return WabenwattClient(
        client.session, "tok", whoami_url=str(client.make_url("/whoami"))
    )


async def test_returns_the_plant(endpoint: tuple[FakeWhoami, TestClient]) -> None:
    fake, client = endpoint

    device = await _client(client).whoami()

    assert device == DeviceInfo(
        device_type=SOURCE_TYPE_PV,
        device_id="5b7e1c3a-1234-4c9d-8e2f-0a1b2c3d4e5f",
        name="Balkon Süd",
    )
    assert fake.authorization == "Bearer tok"


async def test_returns_the_battery(endpoint: tuple[FakeWhoami, TestClient]) -> None:
    fake, client = endpoint
    fake.body = BATTERY_BODY

    assert await _client(client).whoami() == DeviceInfo(
        device_type=SOURCE_TYPE_BATTERY,
        device_id="7c8f2d4b-2345-4d0e-9f30-1b2c3d4e5f60",
        name="Hausakku",
    )


# An API from before batteries existed answers without deviceType. Such a
# token can only be a plant, and reading it as one keeps that API usable.
async def test_missing_device_type_is_a_plant(
    endpoint: tuple[FakeWhoami, TestClient],
) -> None:
    fake, client = endpoint
    fake.body = {"plantId": "5b7e1c3a-1234-4c9d-8e2f-0a1b2c3d4e5f", "name": "Balkon"}

    device = await _client(client).whoami()

    assert device.device_type == SOURCE_TYPE_PV
    assert device.device_id == "5b7e1c3a-1234-4c9d-8e2f-0a1b2c3d4e5f"


async def test_an_unknown_device_type_is_refused(
    endpoint: tuple[FakeWhoami, TestClient],
) -> None:
    """A device type from a newer server must not be guessed into an existing
    one — the wrong sensors would be attached to it."""
    fake, client = endpoint
    fake.body = {"deviceType": "wallbox", "wallboxId": "w-1", "name": "Garage"}

    with pytest.raises(CannotConnectError):
        await _client(client).whoami()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": {"code": "PLANT_TOKEN_INVALID"}}, InvalidTokenError),
        (429, None, RateLimitedError),
        # An API that does not have the endpoint yet must not look like a bad token.
        (404, None, CannotConnectError),
        (500, None, CannotConnectError),
    ],
)
async def test_status_codes_map_to_errors(
    endpoint: tuple[FakeWhoami, TestClient],
    status: int,
    body: dict | None,
    expected: type[Exception],
) -> None:
    fake, client = endpoint
    fake.status, fake.body = status, body

    with pytest.raises(expected):
        await _client(client).whoami()


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x"},
        [],
        "text",
        {"plantId": None},
        # A battery answer without its id is as unusable as a plant one.
        {"deviceType": "battery", "name": "x"},
    ],
)
async def test_malformed_body_is_a_connection_error(
    endpoint: tuple[FakeWhoami, TestClient], body: object
) -> None:
    fake, client = endpoint
    fake.body = body

    with pytest.raises(CannotConnectError):
        await _client(client).whoami()
