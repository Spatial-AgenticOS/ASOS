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


def test_funnel_enable_modern_syntax_happy_path(monkeypatch):
    """Tailscale 1.66+ syntax: ``tailscale funnel --bg <port>``.

    Verifies the ``--bg`` flag is passed (without it the CLI blocks
    forever foreground — the bug the live test surfaced).
    """
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "funnel" in cmd and "--bg" in cmd:
            return _fake_proc(0)
        if "status" in cmd and "--json" in cmd:
            return _fake_proc(0, stdout=SAMPLE_STATUS_JSON)
        return _fake_proc(0)

    with patch.object(tailscale.subprocess, "run", side_effect=fake_run):
        result = tailscale.funnel_enable(9090)
    assert result["enabled"] is True
    assert result["url"] == "https://omars-macbook-air-2.tail035783.ts.net"
    # First call MUST use the modern --bg <port> form.
    enable_calls = [c for c in calls if "funnel" in c and "--bg" in c]
    assert enable_calls, f"expected funnel --bg call, got: {calls}"
    assert "9090" in enable_calls[0]


def test_funnel_enable_falls_back_to_legacy_for_old_daemons(monkeypatch):
    """If `funnel --bg` is not recognised (theoretical pre-1.66 daemon),
    fall back to the legacy ``funnel <port> on`` form."""
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    def fake_run(cmd, **kwargs):
        if "--bg" in cmd:
            return _fake_proc(1, stderr="Error: unknown flag: --bg")
        if "on" in cmd and "9090" in cmd:
            return _fake_proc(0)
        if "status" in cmd and "--json" in cmd:
            return _fake_proc(0, stdout=SAMPLE_STATUS_JSON)
        return _fake_proc(0)

    with patch.object(tailscale.subprocess, "run", side_effect=fake_run):
        result = tailscale.funnel_enable(9090)
    assert result["enabled"] is True


def test_funnel_enable_funnel_disabled_in_tailnet(monkeypatch):
    """The modern (1.66+) error format includes a per-node enable URL —
    we MUST surface that URL in the exception so the operator can
    one-click enable Funnel for their tailnet."""
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(
            1,
            stderr=(
                "Funnel is not enabled on your tailnet.\n"
                "To enable, visit:\n\n"
                "         https://login.tailscale.com/f/funnel?node=nuxis4cNFg11CNTRL\n"
            ),
        ),
    ):
        with pytest.raises(tailscale.TailscaleFunnelDisabledInTailnet) as exc:
            tailscale.funnel_enable(9090)
    msg = str(exc.value)
    assert "https://login.tailscale.com/f/funnel?node=" in msg, (
        f"per-node enable URL must be surfaced; got: {msg}"
    )


def test_funnel_disable_uses_funnel_reset(monkeypatch):
    """Tailscale 1.66+: disable is `funnel reset` not `funnel <port> off`."""
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _fake_proc(0)

    with patch.object(tailscale.subprocess, "run", side_effect=fake_run):
        result = tailscale.funnel_disable(9090)
    assert result["enabled"] is False
    assert any("reset" in c for c in calls), (
        f"expected funnel reset; got calls: {calls}"
    )


def test_funnel_disable_idempotent_when_already_off(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale
    # Both reset and legacy off return non-zero "no serve config".
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(1, stderr="no serve config"),
    ):
        result = tailscale.funnel_disable(9090)
    assert result["enabled"] is False


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
