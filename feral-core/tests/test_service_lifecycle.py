"""v2026.5.28 — ``feral start`` as a real macOS service.

Before this release ``feral start`` ran uvicorn in a non-daemon thread
of the operator's interactive shell, so closing the terminal killed
the brain. ``feral install-service`` existed as a separate command but
the label was ``ai.feral.brain``, the plist did not propagate FERAL_*
env vars, and there was no ``feral stop`` / ``feral status`` / ``feral
logs`` / ``feral restart`` story — operators had to learn launchctl by
hand.

This module locks in the post-v2026.5.28 behaviour:

* Service label is the stable reverse-DNS ``com.feral.brain``;
  ``ai.feral.brain`` is recognised as a legacy label that gets
  migrated on every install.
* The plist embeds ``ProgramArguments`` that delegate back to
  ``feral start --foreground --no-browser`` so the launchd-launched
  brain renders the same banner chrome as a foreground run.
* ``EnvironmentVariables`` carries every ``FERAL_*`` env the operator
  currently has set, since launchd does not source shell rc.
* ``StandardOutPath`` / ``StandardErrorPath`` point at
  ``~/.feral/logs/brain.{log,err}`` — same paths v2026.5.27 used so
  any operator tail script keeps working.
* ``cmd_stop`` is idempotent — running it twice does not raise.
* ``cmd_logs`` falls back to printing the file when ``tail`` is
  unavailable.
* The legacy ``install_service`` / ``uninstall_service`` shims still
  exist (callers in CI scripts depend on them).
"""
from __future__ import annotations

import importlib
import platform
from pathlib import Path

import pytest


def _reload_daemon(monkeypatch, *, fake_home: Path | None = None):
    if fake_home is not None:
        monkeypatch.setenv("HOME", str(fake_home))
    from cli import daemon as _d

    return importlib.reload(_d)


def test_service_label_is_com_feral_brain():
    from cli import daemon as _d

    assert _d.SERVICE_LABEL == "com.feral.brain"


def test_legacy_label_recognised_for_migration():
    from cli import daemon as _d

    assert "ai.feral.brain" in _d.LEGACY_LABELS


def test_render_plist_snapshot_invariants(monkeypatch, tmp_path):
    """Plist must declare every field operators rely on at runtime."""
    daemon = _reload_daemon(monkeypatch, fake_home=tmp_path)

    program_args = ["/usr/local/bin/feral", "start", "--foreground", "--no-browser"]
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "FERAL_TLS": "1",
        "FERAL_PORT": "9090",
    }
    plist = daemon._render_plist(program_args, env)

    assert "<key>Label</key>" in plist
    assert f"<string>{daemon.SERVICE_LABEL}</string>" in plist
    assert "<key>ProgramArguments</key>" in plist
    assert "<string>/usr/local/bin/feral</string>" in plist
    assert "<string>--foreground</string>" in plist
    assert "<string>--no-browser</string>" in plist
    assert "<key>RunAtLoad</key>" in plist
    assert "<true/>" in plist
    assert "<key>KeepAlive</key>" in plist
    assert "<key>StandardOutPath</key>" in plist
    assert str(tmp_path / ".feral" / "logs" / "brain.log") in plist
    assert "<key>StandardErrorPath</key>" in plist
    assert str(tmp_path / ".feral" / "logs" / "brain.err") in plist
    assert "<key>EnvironmentVariables</key>" in plist
    assert "<string>FERAL_TLS</string>" not in plist  # FERAL_TLS is a KEY, not a value
    assert "<key>FERAL_TLS</key>" in plist
    assert "<key>FERAL_PORT</key>" in plist
    assert "<key>WorkingDirectory</key>" in plist


def test_build_environment_vars_propagates_feral_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("FERAL_PORT", "8123")
    monkeypatch.setenv("FERAL_TLS", "1")
    monkeypatch.setenv("FERAL_NEW_FEATURE_FLAG", "experimental")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("UNRELATED_VAR", "nope")
    daemon = _reload_daemon(monkeypatch)
    env = daemon._build_environment_vars()
    assert env["FERAL_PORT"] == "8123"
    assert env["FERAL_TLS"] == "1"
    assert env["FERAL_NEW_FEATURE_FLAG"] == "experimental"
    assert env["HOME"] == str(tmp_path)
    assert "PATH" in env
    assert "UNRELATED_VAR" not in env  # only FERAL_* + the explicit fixed set


def test_logs_dir_resolves_under_feral_home(monkeypatch, tmp_path):
    daemon = _reload_daemon(monkeypatch, fake_home=tmp_path)
    stdout, stderr = daemon.log_paths()
    assert stdout == tmp_path / ".feral" / "logs" / "brain.log"
    assert stderr == tmp_path / ".feral" / "logs" / "brain.err"
    # log_paths() must be idempotent: directory is created on access.
    assert stdout.parent.is_dir()


def test_resolve_program_arguments_uses_foreground_no_browser(monkeypatch, tmp_path):
    daemon = _reload_daemon(monkeypatch, fake_home=tmp_path)
    args = daemon._resolve_program_arguments()
    # Either the `feral` shim path with start --foreground --no-browser,
    # or the python-fallback shape `python -m cli.main serve`.
    if args[0].endswith("feral") and len(args) == 4:
        assert args[1:] == ["start", "--foreground", "--no-browser"]
    else:
        assert args[1:] == ["-m", "cli.main", "serve"]


def test_install_service_back_compat_returns_bool(monkeypatch, tmp_path):
    """Back-compat shim must keep its True/False return for old CI scripts."""
    daemon = _reload_daemon(monkeypatch, fake_home=tmp_path)
    captured: dict = {}

    def _fake_start_service():
        captured["called"] = True
        return {"installed": True, "running": True}

    monkeypatch.setattr(daemon, "start_service", _fake_start_service)
    assert daemon.install_service() is True
    assert captured.get("called") is True


def test_install_service_back_compat_swallows_errors(monkeypatch, tmp_path):
    daemon = _reload_daemon(monkeypatch, fake_home=tmp_path)

    def _explode():
        raise RuntimeError("boom")

    monkeypatch.setattr(daemon, "start_service", _explode)
    assert daemon.install_service() is False


def test_stop_macos_no_op_when_not_installed(monkeypatch, tmp_path):
    """Stopping a service that was never installed must not raise."""
    daemon = _reload_daemon(monkeypatch, fake_home=tmp_path)
    # Force the plist path to a non-existent location.
    fake_plist = tmp_path / "nope.plist"
    monkeypatch.setattr(daemon, "_launchd_plist_path", lambda: fake_plist)
    assert daemon._stop_macos() is False


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux"),
    reason="service mode is only supported on macOS / Linux",
)
def test_service_status_shape_without_install(monkeypatch, tmp_path):
    """Status before any install reports installed=False, running=False."""
    daemon = _reload_daemon(monkeypatch, fake_home=tmp_path)
    if platform.system() == "Darwin":
        monkeypatch.setattr(
            daemon, "_launchd_plist_path", lambda: tmp_path / "absent.plist"
        )
    else:
        monkeypatch.setattr(
            daemon,
            "_systemd_unit_path",
            lambda: tmp_path / "absent.service",
        )

    status = daemon.service_status()
    assert status["installed"] is False
    assert status["running"] is False


def test_is_service_supported_on_this_platform():
    from cli import daemon as _d

    if platform.system() in ("Darwin", "Linux"):
        assert _d.is_service_supported()
    else:
        assert _d.is_service_supported() is False


def test_cli_subcommands_registered_via_argparse():
    """Smoke test the new argparse surface: stop / restart / service-status / logs.

    Drives the real registration via ``feral --help`` in a subprocess
    (the registration lives inside ``cli.main.main`` and there is no
    side-effect-free API to inspect it). If the help text lists every
    new subcommand we know argparse hooked them up.
    """
    from cli import main as _m

    completed = __import__("subprocess").run(
        [_m.sys.executable, "-m", "cli.main", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    out = (completed.stdout or "") + (completed.stderr or "")
    assert "stop" in out
    assert "restart" in out
    assert "service-status" in out
    assert "logs" in out
