"""A4 — Device-pairing HTTP policy (non-loopback).

The pairing flow hinges on a phone on the LAN being able to load
``GET /pair?t=<token>`` and its hashed asset bundle *without* an API
key — that phone only has the one-time pairing token, which is
validated later on the ``/v1/node`` WebSocket handshake.

These tests pin the middleware policy that makes that possible:

* ``GET /pair`` and ``GET /v2/pair`` return 200 HTML from a
  non-loopback client.
* ``GET /assets/…`` returns 200 (existing file) or 404 (missing
  file) — never 401.
* Unrelated API surface (``GET /api/config``) still returns 401
  without a Bearer token from the same non-loopback client — no
  regression in API-key protection.
* The ``POST /pair`` verb stays locked: the allowlist is GET-only.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def non_loopback_client(monkeypatch):
    """Starlette TestClient reports ``client.host == "testclient"``. The
    repo-wide conftest monkeypatches ``is_localhost`` so tests don't
    need Bearer headers; for these tests we want to exercise the
    *non*-loopback branch, so we override the override back to the
    strict definition.
    """
    from security import session_auth as _sa

    def _strict_is_localhost(host):
        return host in ("127.0.0.1", "::1", "localhost")

    monkeypatch.setattr(_sa, "is_localhost", _strict_is_localhost)
    try:
        import api.server as _server
        monkeypatch.setattr(_server, "is_localhost", _strict_is_localhost, raising=False)
    except Exception:
        pass

    from api.server import app
    return TestClient(app, raise_server_exceptions=False)


def test_get_pair_allowed_off_loopback(non_loopback_client):
    r = non_loopback_client.get("/pair")
    assert r.status_code == 200, r.text


def test_get_pair_with_token_allowed_off_loopback(non_loopback_client):
    r = non_loopback_client.get("/pair?t=abc12345deadbeef")
    assert r.status_code == 200, r.text


def test_get_v2_pair_allowed_off_loopback(non_loopback_client):
    r = non_loopback_client.get("/v2/pair?t=abc")
    # Either the v2 alias serves it, or the SPA catch-all handles it —
    # either way it must not 401.
    assert r.status_code != 401, r.text


def test_get_assets_not_blocked_off_loopback(non_loopback_client):
    # The asset bundle may or may not be built in the test tree; the
    # contract here is "middleware does not 401", not "file exists".
    r = non_loopback_client.get("/assets/definitely-missing-hash.js")
    assert r.status_code != 401, r.text
    assert r.status_code in (200, 404), r.text


def test_post_pair_is_not_open_off_loopback(non_loopback_client):
    # POST /pair is not in the GET-only allowlist; it must still 401
    # without a Bearer token.
    r = non_loopback_client.post("/pair", json={})
    assert r.status_code == 401, r.text


def test_api_config_still_protected_off_loopback(non_loopback_client):
    # Regression: the narrow pairing allowlist must NOT leak into the
    # authenticated API surface.
    r = non_loopback_client.get("/api/config")
    assert r.status_code == 401, r.text


def test_api_devices_paired_still_protected_off_loopback(non_loopback_client):
    r = non_loopback_client.get("/api/devices/paired")
    assert r.status_code == 401, r.text
