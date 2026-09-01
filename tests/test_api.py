"""HTTP client against a fake report endpoint."""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from custom_components.wabenwatt.api import (
    CannotConnectError,
    InvalidTokenError,
    RateLimitedError,
    ReportRejectedError,
    WabenwattClient,
)

# The HA test plugin blocks sockets; these tests talk to a local fake server.
pytestmark = pytest.mark.usefixtures("socket_enabled")


class FakeEndpoint:
    """Records the last request and answers with a configurable response."""

    def __init__(self) -> None:
        self.status = 204
        self.body: dict | None = None
        self.requests: list[tuple[dict, str | None]] = []

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            (await request.json(), request.headers.get("Authorization"))
        )
        if self.body is None:
            return web.Response(status=self.status)
        return web.json_response(self.body, status=self.status)


@pytest.fixture
async def endpoint() -> tuple[FakeEndpoint, TestClient]:
    fake = FakeEndpoint()
    app = web.Application()
    app.router.add_post("/v1", fake.handle)
    async with TestClient(TestServer(app)) as client:
        yield fake, client


async def test_success_sends_bearer_and_payload(
    endpoint: tuple[FakeEndpoint, TestClient],
) -> None:
    fake, client = endpoint
    api = WabenwattClient(client.session, "tok", url=str(client.make_url("/v1")))

    await api.report(pv_power_w=742)
    await api.report(pv_power_w=742, battery_power_w=-300)

    assert fake.requests == [
        ({"powerW": 742}, "Bearer tok"),
        ({"pvPowerW": 742, "batteryPowerW": -300}, "Bearer tok"),
    ]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            401,
            {"error": {"code": "PLANT_TOKEN_INVALID", "message": "x"}},
            InvalidTokenError,
        ),
        (429, None, RateLimitedError),
        (500, None, CannotConnectError),
    ],
)
async def test_status_codes_map_to_errors(
    endpoint: tuple[FakeEndpoint, TestClient],
    status: int,
    body: dict | None,
    expected: type[Exception],
) -> None:
    fake, client = endpoint
    fake.status, fake.body = status, body
    api = WabenwattClient(client.session, "tok", url=str(client.make_url("/v1")))

    with pytest.raises(expected):
        await api.report(pv_power_w=1)


async def test_rejection_carries_code_and_message(
    endpoint: tuple[FakeEndpoint, TestClient],
) -> None:
    fake, client = endpoint
    fake.status = 422
    fake.body = {"error": {"code": "BATTERY_NOT_SUPPORTED", "message": "nope"}}
    api = WabenwattClient(client.session, "tok", url=str(client.make_url("/v1")))

    with pytest.raises(ReportRejectedError) as excinfo:
        await api.report(pv_power_w=1, battery_power_w=0)

    assert excinfo.value.status == 422
    assert excinfo.value.code == "BATTERY_NOT_SUPPORTED"
    assert excinfo.value.message == "nope"


async def test_rejection_without_envelope(
    endpoint: tuple[FakeEndpoint, TestClient],
) -> None:
    fake, client = endpoint
    fake.status = 400
    api = WabenwattClient(client.session, "tok", url=str(client.make_url("/v1")))

    with pytest.raises(ReportRejectedError) as excinfo:
        await api.report(pv_power_w=1)

    assert excinfo.value.code == "UNKNOWN"


async def test_connection_error() -> None:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        api = WabenwattClient(session, "tok", url="http://127.0.0.1:1/v1")
        with pytest.raises(CannotConnectError):
            await api.report(pv_power_w=1)
