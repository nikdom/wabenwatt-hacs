"""HTTP client: the whoami lookup against a fake endpoint."""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from custom_components.wabenwatt.api import (
    CannotConnectError,
    InvalidTokenError,
    PlantInfo,
    RateLimitedError,
    WabenwattClient,
)

# The HA test plugin blocks sockets; these tests talk to a local fake server.
pytestmark = pytest.mark.usefixtures("socket_enabled")

PLANT_BODY = {
    "plantId": "5b7e1c3a-1234-4c9d-8e2f-0a1b2c3d4e5f",
    "name": "Balkon Süd",
    "reportsBatterySeparately": True,
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

    plant = await _client(client).whoami()

    assert plant == PlantInfo(
        plant_id="5b7e1c3a-1234-4c9d-8e2f-0a1b2c3d4e5f",
        name="Balkon Süd",
        reports_battery_separately=True,
    )
    assert fake.authorization == "Bearer tok"


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


@pytest.mark.parametrize("body", [{"name": "x"}, [], "text", {"plantId": None}])
async def test_malformed_body_is_a_connection_error(
    endpoint: tuple[FakeWhoami, TestClient], body: object
) -> None:
    fake, client = endpoint
    fake.body = body

    with pytest.raises(CannotConnectError):
        await _client(client).whoami()
