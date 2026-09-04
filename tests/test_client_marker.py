"""The client marker sent with every request (docs/43-integrations-telemetry.md)."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.wabenwatt.api import WabenwattClient
from custom_components.wabenwatt.const import (
    CLIENT_HEADER,
    CLIENT_MARKER,
    INTEGRATION_VERSION,
)

MANIFEST = (
    Path(__file__).parent.parent / "custom_components" / "wabenwatt" / "manifest.json"
)


def test_version_matches_manifest() -> None:
    """The constant is what we send; the manifest is what HACS installs.

    They are two files, so they can drift — and a wrong number here would
    silently misreport the installed version for the whole fleet.
    """
    assert json.loads(MANIFEST.read_text())["version"] == INTEGRATION_VERSION


def test_every_request_carries_the_marker() -> None:
    client = WabenwattClient(session=None, token="wbw_test")  # type: ignore[arg-type]
    headers = client._headers  # noqa: SLF001

    assert headers[CLIENT_HEADER] == f"wabenwatt-homeassistant/{INTEGRATION_VERSION}"
    assert headers[CLIENT_HEADER] == CLIENT_MARKER
    # The Authorization header must survive next to it.
    assert headers["Authorization"] == "Bearer wbw_test"
    # User-Agent stays untouched: HA's session sets it, and it carries the core
    # version we want to keep seeing.
    assert "User-Agent" not in headers
