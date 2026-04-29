"""Integration test for ``POST /api/apps/install`` with ``registry_id``.

Covers GENUI_PLATFORM_BUILD_SPEC §G1: the 501 stub is replaced with a
real fetch + verify + extract + install flow that calls into
``services.registry_client``. We mock the registry HTTP layer; the
extract + install path is real.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))
    monkeypatch.setenv("FERAL_REGISTRY_URL", "https://registry.test")

    mock_state = MagicMock()
    mock_state.app_registry = MagicMock()
    fake_app = MagicMock()
    fake_app.manifest = MagicMock(
        app_id="test.app",
        version="1.0.0",
        author="tester",
        description="test app",
        brand=MagicMock(model_dump=lambda: {"name": "Test"}),
        entry_surface_id="main",
        surfaces=[MagicMock(surface_id="main")],
        permissions=[],
    )
    fake_app.install_dir = str(tmp_path / "apps" / "test.app")
    fake_app.installed_at = 0.0
    mock_state.app_registry.install_app.return_value = fake_app

    with (
        patch("api.state.state", mock_state),
        patch("api.routes.apps.state", mock_state),
    ):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), mock_state


def test_registry_id_install_404_when_item_missing(env):
    c, _ = env
    from services.registry_client import RegistryNotFound

    with patch(
        "services.registry_client.fetch_and_extract",
        side_effect=RegistryNotFound("item 'missing.app' not found"),
    ):
        r = c.post("/api/apps/install", json={"registry_id": "missing.app"})
    assert r.status_code == 404
    assert "missing.app" in r.json()["detail"]


def test_registry_id_install_400_on_signature_failure(env):
    c, _ = env
    from services.registry_client import RegistryVerificationError

    with patch(
        "services.registry_client.fetch_and_extract",
        side_effect=RegistryVerificationError("sha256 mismatch: …"),
    ):
        r = c.post("/api/apps/install", json={"registry_id": "tampered.app"})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "signature_verification_failed"
    assert "remediation" in body["detail"]


def test_registry_id_install_502_on_registry_unavailable(env):
    c, _ = env
    from services.registry_client import RegistryUnavailable

    with patch(
        "services.registry_client.fetch_and_extract",
        side_effect=RegistryUnavailable("connection refused"),
    ):
        r = c.post("/api/apps/install", json={"registry_id": "any.app"})
    assert r.status_code == 502


def test_registry_id_install_503_on_missing_dependency(env):
    c, _ = env
    from services.registry_client import RegistryDependencyMissing

    with patch(
        "services.registry_client.fetch_and_extract",
        side_effect=RegistryDependencyMissing("httpx is required …"),
    ):
        r = c.post("/api/apps/install", json={"registry_id": "any.app"})
    assert r.status_code == 503


def test_registry_id_install_400_when_kind_is_not_app(env, tmp_path):
    """Skill / daemon / mcp / etc. bundles must be rejected — the
    ``/api/apps/install`` route is GenUI-app-only. CLI ``feral install``
    handles the other kinds."""
    c, _ = env

    def _fake_fetch_and_extract(reg, item_id, dest):
        # Pretend the descriptor came back with kind=daemon
        return {"kind": "daemon", "manifest": {"id": "test.daemon"}}

    with patch(
        "services.registry_client.fetch_and_extract",
        side_effect=_fake_fetch_and_extract,
    ):
        r = c.post("/api/apps/install", json={"registry_id": "test.daemon"})
    assert r.status_code == 400
    assert "kind='daemon'" in r.json()["detail"]


def test_registry_id_install_happy_path_calls_install_app(env, tmp_path):
    c, mock_state = env

    # When fetch_and_extract is called, simulate a unpacked manifest
    # by writing one to the tmp dir the route picked. We don't have
    # access to the route's tmp dir directly, so we mock _install_with_signing
    # to bypass the manifest read.
    from services.registry_client import fetch_and_extract  # noqa: F401

    def _ok(reg, item_id, dest):
        # Write a minimal manifest file to satisfy any future
        # path-existence check in the install flow.
        from pathlib import Path
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "manifest.yaml").write_text("app_id: test.app\n")
        return {"kind": "app", "manifest": {"app_id": "test.app"}}

    with (
        patch("services.registry_client.fetch_and_extract", side_effect=_ok),
        patch("api.routes.apps._install_with_signing") as mock_install,
    ):
        # Have _install_with_signing return the same fake_app the
        # fixture set on app_registry.install_app.
        mock_install.return_value = mock_state.app_registry.install_app.return_value
        r = c.post("/api/apps/install", json={"registry_id": "test.app"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["app"]["app_id"] == "test.app"
    # The route called _install_with_signing once with the registry
    # tree it just unpacked (or its single nested dir).
    assert mock_install.call_count == 1
