"""Phase 3 / C3.1 — honest 404s for unknown ``/api/...`` paths.

Before this fix the SPA catch-all at ``feral-core/api/server.py``
returned 200 SPA HTML for any GET to a path that no router matched.
SDKs polling missing endpoints (e.g. the SDK pair-code flow's
historical ``GET /api/devices/pair/status``) silently failed:
``json.loads("<!DOCTYPE html>")`` raised, the SDK swallowed the
exception, the operator saw an indefinite spinner.

The new behavior: paths starting with ``api/``, ``v1/``, or ``v2/api/``
that don't match a registered route return a structured JSON 404 with
``code: "no_such_route"``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))
    from config.loader import ConfigLoader
    from security.device_pairing import DevicePairingStore
    config = ConfigLoader(project_dir=str(tmp_path))
    config.discover()
    store = DevicePairingStore(db_path=str(tmp_path / "pairs.db"))

    mock_state = MagicMock()
    mock_state.config = config
    mock_state.device_pairing_store = store

    with (
        patch("api.state.state", mock_state),
        patch("api.routes.devices.state", mock_state),
    ):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False)


def test_unknown_api_path_returns_json_404(client):
    r = client.get("/api/devices/pair/status_typo")
    assert r.status_code == 404
    assert r.headers.get("content-type", "").startswith("application/json")
    body = r.json()
    assert body["detail"]["code"] == "no_such_route"
    assert body["detail"]["path"] == "/api/devices/pair/status_typo"


def test_unknown_v1_path_returns_json_404(client):
    r = client.get("/v1/something/that/does/not/exist")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["code"] == "no_such_route"


def test_known_spa_path_still_returns_html_or_index(client):
    """``/some-spa-route`` (depth-1) is NOT in the api/v1/v2-api set, so
    the catch-all should still serve the SPA shell. We don't assert
    the body content because the bundle may or may not be present in
    the test environment, but the status must not be 404."""
    r = client.get("/some-spa-route-that-does-not-exist")
    # Either the SPA index or the FALLBACK_HTML — both are 200.
    assert r.status_code == 200


def test_health_still_works(client):
    """Sanity: the 404 honesty must not break ``/health`` (which is
    open-listed and not under the api/ prefix)."""
    r = client.get("/health")
    assert r.status_code == 200
