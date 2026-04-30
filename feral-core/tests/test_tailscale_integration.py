"""Tests for the Tailscale integration module + REST routes.

Subprocess calls are mocked; we verify the contract our integration
expects from ``tailscale`` CLI output (status JSON shape, funnel
output parsing, error classification).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


# ── Fixtures ──────────────────────────────────────────────────────


def _fake_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


SAMPLE_STATUS_JSON = json.dumps({
    "Self": {
        "DNSName": "omars-macbook-air-2.tail035783.ts.net.",
        "TailscaleIPs": ["100.70.219.88", "fd7a:115c:a1e0::2b3a:db58"],
    },
    "CurrentTailnet": {"Name": "tail035783.ts.net"},
})


# ── integrations.tailscale unit tests ────────────────────────────


def test_is_installed_true(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    assert tailscale.is_installed() is True


def test_is_installed_false(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    from integrations import tailscale
    assert tailscale.is_installed() is False


def test_status_when_not_installed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    from integrations import tailscale
    snap = tailscale.status()
    assert snap.installed is False
    assert snap.running is False
    assert snap.error == "tailscale_not_installed"


def test_status_happy_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(0, stdout=SAMPLE_STATUS_JSON),
    ):
        snap = tailscale.status()
    assert snap.installed is True
    assert snap.running is True
    assert snap.logged_in is True
    assert snap.dns_name == "omars-macbook-air-2.tail035783.ts.net"
    assert snap.ipv4 == "100.70.219.88"
    assert snap.tailnet_name == "tail035783.ts.net"
    assert snap.error == ""


def test_status_daemon_unreachable(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(
            1,
            stderr="error: failed to connect to tailscaled.sock: no such file or directory",
        ),
    ):
        snap = tailscale.status()
    assert snap.installed is True
    assert snap.running is False
    assert snap.error == "daemon_unreachable"


def test_status_not_logged_in(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(1, stderr="error: not logged in. run `tailscale up`"),
    ):
        snap = tailscale.status()
    assert snap.installed is True
    assert snap.error == "not_logged_in"


def test_funnel_url_composes_https(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(0, stdout=SAMPLE_STATUS_JSON),
    ):
        url = tailscale.funnel_url(9090)
    assert url == "https://omars-macbook-air-2.tail035783.ts.net"


def test_funnel_enable_happy_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "funnel" in cmd and "on" in cmd:
            return _fake_proc(0, stdout="Available on the internet:\nhttps://example.ts.net\n")
        if "status" in cmd and "--json" in cmd:
            return _fake_proc(0, stdout=SAMPLE_STATUS_JSON)
        return _fake_proc(0)

    with patch.object(tailscale.subprocess, "run", side_effect=fake_run):
        result = tailscale.funnel_enable(9090)
    assert result["enabled"] is True
    assert result["url"] == "https://omars-macbook-air-2.tail035783.ts.net"
    # Verify the first attempt used "<port> on" syntax
    assert any("on" in c and "9090" in c for c in calls)


def test_funnel_enable_funnel_disabled_in_tailnet(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(
            1,
            stderr="error: Funnel is not enabled in your tailnet. enable Funnel in admin",
        ),
    ):
        with pytest.raises(tailscale.TailscaleFunnelDisabledInTailnet) as exc:
            tailscale.funnel_enable(9090)
    assert "tailscale.com/admin" in str(exc.value)


def test_funnel_disable_idempotent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(0),
    ):
        result = tailscale.funnel_disable(9090)
    assert result["enabled"] is False
    assert result["port"] == 9090


# ── REST endpoint tests ──────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))
    from config.loader import ConfigLoader
    config = ConfigLoader(project_dir=str(tmp_path))
    config.discover()

    mock_state = MagicMock()
    mock_state.config = config
    with (
        patch("api.state.state", mock_state),
        patch("api.routes.access.state", mock_state),
    ):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=True), config


def test_access_status_when_tailscale_absent(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    r = c.get("/api/access/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pairing_mode"] in {"localhost", "local", "remote"}
    assert body["tailscale"]["installed"] is False
    assert body["tailscale"]["error"] == "tailscale_not_installed"


def test_access_status_with_tailscale_logged_in(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        side_effect=[
            _fake_proc(0, stdout=SAMPLE_STATUS_JSON),  # status --json
            _fake_proc(0, stdout=""),                   # funnel status
        ],
    ):
        r = c.get("/api/access/status")
    body = r.json()
    assert body["tailscale"]["installed"] is True
    assert body["tailscale"]["running"] is True
    assert body["tailscale"]["dns_name"] == "omars-macbook-air-2.tail035783.ts.net"


def test_access_remote_up_fails_when_not_installed(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    r = c.post("/api/access/remote-up")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "tailscale_not_installed"


def test_access_remote_up_persists_url_on_success(client, monkeypatch):
    c, config = client
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    def fake_run(cmd, **kwargs):
        if "funnel" in cmd and "on" in cmd:
            return _fake_proc(0)
        if "status" in cmd and "--json" in cmd:
            return _fake_proc(0, stdout=SAMPLE_STATUS_JSON)
        return _fake_proc(0)

    with patch.object(tailscale.subprocess, "run", side_effect=fake_run):
        r = c.post("/api/access/remote-up")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pairing_mode"] == "remote"
    assert body["remote_url"] == "https://omars-macbook-air-2.tail035783.ts.net"

    # Settings persisted.
    config.discover()
    assert config.access_pairing_mode == "remote"
    assert config.access_remote_url == "https://omars-macbook-air-2.tail035783.ts.net"


def test_access_remote_down_clears_url(client, monkeypatch):
    c, config = client
    config.update_settings("access", "pairing_mode", "remote")
    config.update_settings(
        "access", "tailscale",
        {"funnel": True, "tailnet_url": "https://example.ts.net"},
    )
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(0),
    ):
        r = c.post("/api/access/remote-down")
    assert r.status_code == 200, r.text
    assert r.json()["pairing_mode"] == "localhost"
    config.discover()
    assert config.access_pairing_mode == "localhost"
    assert config.access_remote_url == ""
