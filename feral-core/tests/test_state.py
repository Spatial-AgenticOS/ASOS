"""
Tests for api/state.py — BrainState init, VisionBuffer, credential loading,
session management, and the async init pipeline with mocked externals.
"""

from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# VisionBuffer — lightweight, no external deps
# ---------------------------------------------------------------------------

from api.state import VisionBuffer, _log_activity


class TestVisionBuffer:
    def test_push_and_latest(self):
        buf = VisionBuffer(max_frames_per_node=3)
        buf.push("n1", {"data_b64": "aaa", "encoding": "jpeg"})
        assert buf.latest("n1")["data_b64"] == "aaa"

    def test_latest_none_for_unknown_node(self):
        buf = VisionBuffer()
        assert buf.latest("unknown") is None

    def test_ring_buffer_eviction(self):
        buf = VisionBuffer(max_frames_per_node=2)
        buf.push("n1", {"data_b64": "a"})
        buf.push("n1", {"data_b64": "b"})
        buf.push("n1", {"data_b64": "c"})
        assert len(buf.frames["n1"]) == 2
        assert buf.latest("n1")["data_b64"] == "c"

    def test_latest_data_url_jpeg(self):
        buf = VisionBuffer()
        buf.push("n1", {"data_b64": "abc123", "encoding": "jpeg"})
        url = buf.latest_data_url("n1")
        assert url == "data:image/jpeg;base64,abc123"

    def test_latest_data_url_png(self):
        buf = VisionBuffer()
        buf.push("n1", {"data_b64": "png_data", "encoding": "png"})
        url = buf.latest_data_url("n1")
        assert url.startswith("data:image/png;base64,")

    def test_latest_data_url_no_data(self):
        buf = VisionBuffer()
        assert buf.latest_data_url("n1") is None

    def test_latest_data_url_empty_b64(self):
        buf = VisionBuffer()
        buf.push("n1", {"data_b64": "", "encoding": "jpeg"})
        assert buf.latest_data_url("n1") is None

    def test_node_ids_with_frames(self):
        buf = VisionBuffer()
        buf.push("n1", {"data_b64": "a"})
        buf.push("n2", {"data_b64": "b"})
        ids = buf.node_ids_with_frames()
        assert set(ids) == {"n1", "n2"}

    def test_node_ids_empty(self):
        buf = VisionBuffer()
        assert buf.node_ids_with_frames() == []


# ---------------------------------------------------------------------------
# _log_activity
# ---------------------------------------------------------------------------

class TestLogActivity:
    def test_log_activity_appends(self):
        from api.state import state
        initial_len = len(state.activity_log)
        _log_activity("test_action", "some detail")
        assert len(state.activity_log) == initial_len + 1
        entry = state.activity_log[-1]
        assert entry["action"] == "test_action"
        assert entry["detail"] == "some detail"
        assert "timestamp" in entry


# ---------------------------------------------------------------------------
# BrainState — constructor + static helpers (sync, no async init)
# ---------------------------------------------------------------------------

class TestBrainStateConstructor:
    def test_sessions_dict_starts_empty(self):
        from api.state import state
        assert isinstance(state.sessions, dict)

    def test_activity_log_is_bounded_deque(self):
        from api.state import state
        assert isinstance(state.activity_log, deque)
        assert state.activity_log.maxlen == 100

    def test_skill_executor_none_without_orchestrator(self):
        from api.state import state
        if state.orchestrator is None:
            assert state.skill_executor is None

    def test_daemon_session_bindings(self):
        from api.state import state
        state.bind_session_to_daemon("s1", "d1")
        assert "s1" in state.get_sessions_for_daemon("d1")
        assert state.get_sessions_for_daemon("d_missing") == set()


class TestLoadStoredCredentials:
    def test_loads_keys_into_env(self, tmp_path, monkeypatch):
        creds = {"OPENAI_API_KEY": "sk-fromfile", "GROQ_API_KEY": "gk-test"}
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text(json.dumps(creds))

        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        from api.state import BrainState
        BrainState._load_stored_credentials()

        assert os.environ.get("OPENAI_API_KEY") == "sk-fromfile"
        assert os.environ.get("GROQ_API_KEY") == "gk-test"

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        creds = {"OPENAI_API_KEY": "sk-fromfile"}
        (tmp_path / "credentials.json").write_text(json.dumps(creds))
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-existing")

        from api.state import BrainState
        BrainState._load_stored_credentials()

        assert os.environ["OPENAI_API_KEY"] == "sk-existing"

    def test_missing_credentials_file_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        from api.state import BrainState
        BrainState._load_stored_credentials()  # should not raise

    def test_web_search_alias(self, tmp_path, monkeypatch):
        creds = {"web_search": "tavily-alias-key"}
        (tmp_path / "credentials.json").write_text(json.dumps(creds))
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        from api.state import BrainState
        BrainState._load_stored_credentials()
        assert os.environ.get("TAVILY_API_KEY") == "tavily-alias-key"

    def test_partial_creds_file_hydrates_missing_keys_from_vault(
        self, tmp_path, monkeypatch
    ):
        """A partial plaintext mirror must NOT suppress vault fallback
        for the other providers. Pre-fix this test would leave
        ANTHROPIC_API_KEY unset because OPENAI_API_KEY came from the
        file and the vault-fallback gate was ``not loaded``."""
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        from security.vault import BlindVault
        vault = BlindVault(vault_path=str(tmp_path / "credentials.json"))
        vault.set_credential("ANTHROPIC_API_KEY", "sk-ant-vault")
        vault.set_credential("GROQ_API_KEY", "gk-vault")

        (tmp_path / "credentials.json").write_text(
            json.dumps({"OPENAI_API_KEY": "sk-openai-file"})
        )

        from api.state import BrainState
        BrainState._load_stored_credentials()

        assert os.environ.get("OPENAI_API_KEY") == "sk-openai-file"
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-vault"
        assert os.environ.get("GROQ_API_KEY") == "gk-vault"

    def test_vault_only_bootstrap_with_no_creds_file(self, tmp_path, monkeypatch):
        """No credentials.json at all — every key must come from the
        encrypted vault. This is the v2026.5.0+ default once the
        plaintext mirror has been scrubbed."""
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        from security.vault import BlindVault
        vault = BlindVault()
        vault.set_credential("OPENAI_API_KEY", "sk-vault-only")
        vault.set_credential("ANTHROPIC_API_KEY", "sk-ant-vault-only")

        assert not (tmp_path / "credentials.json").exists()

        from api.state import BrainState
        BrainState._load_stored_credentials()

        assert os.environ.get("OPENAI_API_KEY") == "sk-vault-only"
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-vault-only"

    def test_corrupt_creds_file_falls_back_to_vault(self, tmp_path, monkeypatch):
        """Corrupt credentials.json must never lock the user out of
        keys that still live in the encrypted vault."""
        monkeypatch.setenv("FERAL_HOME", str(tmp_path))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        from security.vault import BlindVault
        vault = BlindVault()
        vault.set_credential("OPENAI_API_KEY", "sk-from-vault")
        vault.set_credential("GROQ_API_KEY", "gk-from-vault")

        (tmp_path / "credentials.json").write_text("{not valid json,,,")

        from api.state import BrainState
        BrainState._load_stored_credentials()

        assert os.environ.get("OPENAI_API_KEY") == "sk-from-vault"
        assert os.environ.get("GROQ_API_KEY") == "gk-from-vault"
