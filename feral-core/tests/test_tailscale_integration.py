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


# ── Userspace-tailscaled inspector + migration ───────────────────


def _ps_output(rows: list[tuple[int, int, str]]) -> str:
    """Compose `ps -axo pid=,ppid=,command=` output from row tuples."""
    return "\n".join(f"{pid:>5} {ppid:>5} {cmd}" for pid, ppid, cmd in rows)


def test_inspect_tailscaled_process_finds_userspace_state_file_mode():
    from integrations import tailscale
    rows = [
        (1, 0, "/sbin/launchd"),
        (
            69323, 1,
            "tailscaled --tun=userspace-networking "
            "--state=/Users/me/.feral/tailscaled-userspace.state "
            "--socket=/tmp/tailscaled-userspace.sock "
            "--socks5-server=localhost:1055",
        ),
    ]
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(0, stdout=_ps_output(rows)),
    ):
        info = tailscale.inspect_tailscaled_process()
    assert info.running is True
    assert info.pid == 69323
    assert info.is_userspace is True
    assert info.state_file == "/Users/me/.feral/tailscaled-userspace.state"
    assert info.state_dir == ""
    assert info.socket_path == "/tmp/tailscaled-userspace.sock"
    assert info.tun_mode == "userspace-networking"
    # The whole point: this state would fail Funnel cert provisioning.
    assert info.needs_migration is True


def test_inspect_tailscaled_process_no_migration_when_already_statedir():
    from integrations import tailscale
    rows = [
        (
            12345, 1,
            "/opt/homebrew/bin/tailscaled --tun=userspace-networking "
            "--statedir=/Users/me/.feral/tailscaled.d "
            "--socket=/tmp/tailscaled-userspace.sock",
        ),
    ]
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(0, stdout=_ps_output(rows)),
    ):
        info = tailscale.inspect_tailscaled_process()
    assert info.running is True
    assert info.state_dir.endswith("tailscaled.d")
    assert info.needs_migration is False  # already in statedir mode


def test_inspect_tailscaled_process_handles_no_running_daemon():
    from integrations import tailscale
    with patch.object(
        tailscale.subprocess, "run",
        return_value=_fake_proc(0, stdout="    1     0 /sbin/launchd\n"),
    ):
        info = tailscale.inspect_tailscaled_process()
    assert info.running is False
    assert info.needs_migration is False


def test_migrate_userspace_dry_run_returns_plan_no_mutations(tmp_path):
    from integrations import tailscale
    state_file = tmp_path / "tailscaled-userspace.state"
    state_file.write_bytes(b"FAKE_STATE")
    fake_info = tailscale.TailscaledProcessInfo(
        running=True,
        pid=12345,
        binary="/opt/homebrew/bin/tailscaled",
        args=(
            "/opt/homebrew/bin/tailscaled",
            "--tun=userspace-networking",
            f"--state={state_file}",
            "--socket=/tmp/tailscaled-userspace.sock",
        ),
        socket_path="/tmp/tailscaled-userspace.sock",
        state_file=str(state_file),
        tun_mode="userspace-networking",
        parent_pid=1,
    )
    plan = tailscale.migrate_userspace_to_statedir(info=fake_info, dry_run=True)
    assert plan["dry_run"] is True
    assert plan["stop_pid"] == 12345
    assert plan["new_state_dir"].endswith("tailscaled.d")
    assert plan["new_state_file"].endswith("/tailscaled.d/tailscaled.state")
    assert "--statedir=" in " ".join(plan["restart_argv"])
    assert "--state=" not in " ".join(plan["restart_argv"])
    # State file untouched on dry run.
    assert state_file.exists()
    assert state_file.read_bytes() == b"FAKE_STATE"


def test_migrate_userspace_skips_when_already_in_statedir_mode():
    from integrations import tailscale
    fake_info = tailscale.TailscaledProcessInfo(
        running=True,
        pid=12345,
        binary="tailscaled",
        args=("tailscaled", "--statedir=/x", "--socket=/y"),
        state_dir="/x",
        socket_path="/y",
        tun_mode="userspace-networking",
    )
    result = tailscale.migrate_userspace_to_statedir(info=fake_info)
    assert result["migrated"] is False
    assert result["reason"] == "already_in_statedir_mode_or_not_userspace"


def test_migrate_userspace_raises_when_state_file_missing(tmp_path):
    from integrations import tailscale
    fake_info = tailscale.TailscaledProcessInfo(
        running=True,
        pid=12345,
        binary="tailscaled",
        args=("tailscaled", "--tun=userspace-networking",
              f"--state={tmp_path / 'missing.state'}",
              "--socket=/tmp/x.sock"),
        socket_path="/tmp/x.sock",
        state_file=str(tmp_path / "missing.state"),
        tun_mode="userspace-networking",
    )
    with pytest.raises(tailscale.TailscaleMigrationFailed) as exc:
        tailscale.migrate_userspace_to_statedir(info=fake_info)
    assert "doesn't exist" in str(exc.value)
    assert "no changes made" in str(exc.value)


def test_funnel_enable_triggers_auto_migration_when_state_file_mode(monkeypatch, tmp_path):
    """When inspect_tailscaled_process reports needs_migration=True,
    funnel_enable MUST run the migration BEFORE issuing
    `funnel --bg <port>` — otherwise the user gets a half-broken state
    where Funnel is on but TLS handshakes fail."""
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    pre_migration_info = tailscale.TailscaledProcessInfo(
        running=True,
        pid=99,
        binary="tailscaled",
        args=("tailscaled", "--tun=userspace-networking",
              f"--state={tmp_path / 'state'}",
              "--socket=/tmp/x.sock"),
        socket_path="/tmp/x.sock",
        state_file=str(tmp_path / "state"),
        tun_mode="userspace-networking",
    )
    # The migration is what we're asserting got called; stub it out.
    migrate_calls: list[dict] = []

    def fake_migrate(*, info=None, dry_run=False):
        migrate_calls.append({"info_pid": info.pid, "dry_run": dry_run})
        return {
            "migrated": True,
            "old_state_file": str(tmp_path / "state"),
            "new_state_dir": str(tmp_path / "tailscaled.d"),
        }

    def fake_run(cmd, **kwargs):
        if "funnel" in cmd and "--bg" in cmd:
            return _fake_proc(0)
        if "status" in cmd and "--json" in cmd:
            return _fake_proc(0, stdout=SAMPLE_STATUS_JSON)
        return _fake_proc(0)

    with (
        patch.object(tailscale, "inspect_tailscaled_process",
                     return_value=pre_migration_info),
        patch.object(tailscale, "migrate_userspace_to_statedir",
                     side_effect=fake_migrate),
        patch.object(tailscale.subprocess, "run", side_effect=fake_run),
    ):
        result = tailscale.funnel_enable(9090)

    # Migration was called with the inspected info BEFORE Funnel.
    assert len(migrate_calls) == 1
    assert migrate_calls[0]["info_pid"] == 99
    assert migrate_calls[0]["dry_run"] is False
    assert result["enabled"] is True
    assert result["migrated"]["migrated"] is True


def test_funnel_enable_skips_migration_when_auto_migrate_false(monkeypatch, tmp_path):
    """auto_migrate=False MUST raise NoVarRootInUserspace instead of
    silently leaving the daemon broken."""
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    needs_migration_info = tailscale.TailscaledProcessInfo(
        running=True, pid=99, binary="tailscaled",
        args=("tailscaled", "--tun=userspace-networking",
              f"--state={tmp_path / 'state'}", "--socket=/tmp/x.sock"),
        socket_path="/tmp/x.sock", state_file=str(tmp_path / "state"),
        tun_mode="userspace-networking",
    )
    with patch.object(tailscale, "inspect_tailscaled_process",
                      return_value=needs_migration_info):
        with pytest.raises(tailscale.TailscaleNoVarRootInUserspace):
            tailscale.funnel_enable(9090, auto_migrate=False)


def test_funnel_enable_skips_migration_when_already_in_statedir_mode(monkeypatch):
    """Default flow when daemon doesn't need migration: no migrate call."""
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/local/bin/tailscale")
    from integrations import tailscale

    healthy_info = tailscale.TailscaledProcessInfo(
        running=True, pid=99, binary="tailscaled",
        args=("tailscaled", "--statedir=/x"), state_dir="/x",
        tun_mode="userspace-networking",
    )

    def fake_run(cmd, **kwargs):
        if "funnel" in cmd and "--bg" in cmd:
            return _fake_proc(0)
        if "status" in cmd and "--json" in cmd:
            return _fake_proc(0, stdout=SAMPLE_STATUS_JSON)
        return _fake_proc(0)

    with (
        patch.object(tailscale, "inspect_tailscaled_process",
                     return_value=healthy_info),
        patch.object(tailscale, "migrate_userspace_to_statedir") as mig_mock,
        patch.object(tailscale.subprocess, "run", side_effect=fake_run),
    ):
        result = tailscale.funnel_enable(9090)
    mig_mock.assert_not_called()
    assert result["enabled"] is True
    assert "migrated" not in result


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
