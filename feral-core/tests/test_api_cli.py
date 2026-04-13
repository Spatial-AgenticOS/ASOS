"""
Tests for the FERAL CLI entry points.

Covers: cmd_doctor, cmd_status, main() --help, invalid subcommand,
cmd_devices, cmd_skills, cmd_identity, and _is_first_run.
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_cli():
    """Import cli.main lazily to avoid side effects from module-level code."""
    from cli import main as cli_mod
    return cli_mod


# ═══════════════════════════════════════════════
#  cmd_doctor
# ═══════════════════════════════════════════════

class TestCmdDoctor:
    def test_doctor_runs_without_crash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        cli = _import_cli()
        cli.cmd_doctor()

    def test_doctor_detects_python_version(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        cli = _import_cli()
        cli.cmd_doctor()
        out = capsys.readouterr().out
        assert "Python version" in out


# ═══════════════════════════════════════════════
#  cmd_status
# ═══════════════════════════════════════════════

class TestCmdStatus:
    def test_status_shows_error_when_brain_not_running(self, capsys):
        cli = _import_cli()
        with patch.object(cli, "_http_get", return_value={"error": "Connection refused"}):
            cli.cmd_status()
        out = capsys.readouterr().out
        assert "Error" in out

    def test_status_shows_dashboard_data(self, capsys):
        cli = _import_cli()
        fake = {
            "session_count": 2,
            "device_count": 1,
            "skills_count": 5,
            "llm_available": True,
            "audio_available": False,
            "wasm_available": False,
            "wake_word_enabled": True,
            "sync": {"running": True, "peer_count": 0},
            "memory": {"notes": 10, "episodes": 3, "knowledge_triples": 7},
        }
        with patch.object(cli, "_http_get", return_value=fake):
            cli.cmd_status()
        out = capsys.readouterr().out
        assert "Sessions" in out
        assert "10 notes" in out


# ═══════════════════════════════════════════════
#  main() argument parsing
# ═══════════════════════════════════════════════

class TestMainEntrypoint:
    def test_help_exits_zero(self):
        cli = _import_cli()
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["feral", "--help"]):
                cli.main()
        assert exc_info.value.code == 0

    def test_doctor_subcommand_dispatches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        cli = _import_cli()
        with patch("sys.argv", ["feral", "doctor"]):
            cli.main()


# ═══════════════════════════════════════════════
#  cmd_devices / cmd_skills / cmd_identity
# ═══════════════════════════════════════════════

class TestCmdHelpers:
    def test_devices_no_devices(self, capsys):
        cli = _import_cli()
        with patch.object(cli, "_http_get", return_value={"devices": []}):
            cli.cmd_devices()
        assert "No devices" in capsys.readouterr().out

    def test_skills_list(self, capsys):
        cli = _import_cli()
        fake = [{"name": "Web Search", "skill_id": "web_search", "endpoints": 2}]
        with patch.object(cli, "_http_get", return_value=fake):
            cli.cmd_skills()
        out = capsys.readouterr().out
        assert "Web Search" in out

    def test_identity_display(self, capsys):
        cli = _import_cli()
        fake = {"name": "FERAL", "tagline": "AI OS", "personality": "helpful"}
        with patch.object(cli, "_http_get", return_value=fake):
            cli.cmd_identity()
        out = capsys.readouterr().out
        assert "FERAL" in out


# ═══════════════════════════════════════════════
#  _is_first_run
# ═══════════════════════════════════════════════

class TestFirstRunDetection:
    def test_first_run_true_when_no_keys(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        cli = _import_cli()
        assert cli._is_first_run() is True

    def test_first_run_false_when_env_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cli = _import_cli()
        assert cli._is_first_run() is False
