"""
Tests for THEORA Config Loader — Layered configuration system.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from config.loader import ConfigLoader, theora_home, theora_data_home, DEFAULT_SETTINGS


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temp dirs simulating user home and project."""
    user_home = tmp_path / ".theora"
    user_home.mkdir()
    project = tmp_path / "my-project" / ".theora"
    project.mkdir(parents=True)
    return tmp_path, user_home, project


class TestConfigDiscovery:

    def test_default_settings_returned_when_no_files(self, tmp_path):
        loader = ConfigLoader(project_dir=str(tmp_path))
        loader.user_home = tmp_path / ".theora-empty"
        settings = loader.discover()
        assert settings["llm"]["provider"] == "openai"
        assert settings["version"] == "0.4.0"

    def test_user_config_overrides_defaults(self, temp_dirs):
        tmp_path, user_home, _ = temp_dirs
        user_settings = {"llm": {"provider": "groq", "model": "mixtral-8x7b"}}
        (user_home / "settings.json").write_text(json.dumps(user_settings))

        loader = ConfigLoader(project_dir=str(tmp_path / "my-project"))
        loader.user_home = user_home
        settings = loader.discover()
        assert settings["llm"]["provider"] == "groq"
        assert settings["llm"]["model"] == "mixtral-8x7b"

    def test_project_config_overrides_user(self, temp_dirs):
        tmp_path, user_home, project = temp_dirs
        (user_home / "settings.json").write_text(json.dumps({"llm": {"model": "user-model"}}))
        (project / "settings.json").write_text(json.dumps({"llm": {"model": "project-model"}}))

        loader = ConfigLoader(project_dir=str(tmp_path / "my-project"))
        loader.user_home = user_home
        settings = loader.discover()
        assert settings["llm"]["model"] == "project-model"

    def test_local_config_overrides_project(self, temp_dirs):
        tmp_path, user_home, project = temp_dirs
        (project / "settings.json").write_text(json.dumps({"llm": {"model": "proj"}}))
        (project / "settings.local.json").write_text(json.dumps({"llm": {"model": "local"}}))

        loader = ConfigLoader(project_dir=str(tmp_path / "my-project"))
        loader.user_home = user_home
        settings = loader.discover()
        assert settings["llm"]["model"] == "local"

    def test_env_overrides_all(self, temp_dirs, monkeypatch):
        tmp_path, user_home, project = temp_dirs
        (project / "settings.json").write_text(json.dumps({"llm": {"model": "from-file"}}))
        monkeypatch.setenv("THEORA_LLM_MODEL", "from-env")

        loader = ConfigLoader(project_dir=str(tmp_path / "my-project"))
        loader.user_home = user_home
        settings = loader.discover()
        assert settings["llm"]["model"] == "from-env"

    def test_boolean_env_coercion(self, temp_dirs, monkeypatch):
        tmp_path, user_home, _ = temp_dirs
        monkeypatch.setenv("THEORA_STREAMING", "true")

        loader = ConfigLoader(project_dir=str(tmp_path / "my-project"))
        loader.user_home = user_home
        settings = loader.discover()
        assert settings["features"]["streaming"] is True


class TestCredentials:

    def test_credentials_loaded_from_file(self, temp_dirs):
        _, user_home, _ = temp_dirs
        creds = {"OPENAI_API_KEY": "sk-test-123"}
        (user_home / "credentials.json").write_text(json.dumps(creds))

        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        assert loader.get_credential("OPENAI_API_KEY") == "sk-test-123"

    def test_env_credentials_override(self, temp_dirs, monkeypatch):
        _, user_home, _ = temp_dirs
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        assert loader.get_credential("OPENAI_API_KEY") == "sk-from-env"

    def test_skill_keys_from_env(self, temp_dirs, monkeypatch):
        _, user_home, _ = temp_dirs
        monkeypatch.setenv("THEORA_KEY_web_search", "ws-key-123")

        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        assert loader.get_skill_key("web_search") == "ws-key-123"

    def test_credentials_not_in_settings(self, temp_dirs):
        _, user_home, _ = temp_dirs
        creds = {"OPENAI_API_KEY": "sk-secret"}
        (user_home / "credentials.json").write_text(json.dumps(creds))

        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        safe = loader.to_client_safe_dict()
        assert "OPENAI_API_KEY" not in json.dumps(safe)
        assert safe["has_llm_key"] is True

    def test_save_credentials_sets_permissions(self, temp_dirs):
        _, user_home, _ = temp_dirs
        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        loader.save_credentials({"OPENAI_API_KEY": "sk-new"})

        cred_path = user_home / "credentials.json"
        assert cred_path.exists()
        stat = cred_path.stat()
        assert oct(stat.st_mode)[-3:] == "600"


class TestSetupStatus:

    def test_setup_incomplete_when_no_key(self, temp_dirs):
        _, user_home, _ = temp_dirs
        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        assert loader.setup_complete is False

    def test_setup_complete_with_key(self, temp_dirs):
        _, user_home, _ = temp_dirs
        (user_home / "credentials.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-valid"}))
        (user_home / "USER.md").write_text("My name is Test User. I work on AI projects and health technology.")

        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        assert loader.setup_complete is True

    def test_setup_complete_with_ollama(self, temp_dirs):
        _, user_home, _ = temp_dirs
        (user_home / "settings.json").write_text(json.dumps({"llm": {"provider": "ollama"}}))
        (user_home / "USER.md").write_text("My name is Test User. I prefer local models for privacy.")

        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        assert loader.setup_complete is True


class TestWriteAPI:

    def test_update_settings_persists(self, temp_dirs):
        _, user_home, _ = temp_dirs
        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        loader.update_settings("llm", "model", "gpt-4o")

        reloaded = json.loads((user_home / "settings.json").read_text())
        assert reloaded["llm"]["model"] == "gpt-4o"

    def test_client_safe_dict_excludes_security(self, temp_dirs):
        _, user_home, _ = temp_dirs
        loader = ConfigLoader()
        loader.user_home = user_home
        loader.discover()
        safe = loader.to_client_safe_dict()
        assert "security" not in safe

    def test_export_as_env(self, temp_dirs, monkeypatch):
        tmp_path, user_home, _ = temp_dirs
        monkeypatch.delenv("THEORA_LLM_PROVIDER", raising=False)
        (user_home / "credentials.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-export"}))

        loader = ConfigLoader(project_dir=str(tmp_path / "my-project"))
        loader.user_home = user_home
        settings = loader.discover()
        assert settings["llm"]["provider"] == "openai"
        env = loader.export_as_env()
        assert env["OPENAI_API_KEY"] == "sk-export"
        assert env["THEORA_LLM_PROVIDER"] == "openai"


class TestXDGPaths:

    def test_theora_home_respects_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("THEORA_HOME", str(tmp_path / "custom"))
        assert theora_home() == tmp_path / "custom"

    def test_theora_home_xdg_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("THEORA_HOME", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        assert theora_home() == tmp_path / "xdg" / "theora"

    def test_theora_data_home_xdg(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        assert theora_data_home() == tmp_path / "data" / "theora"
