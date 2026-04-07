"""
Tests for THEORA identity workspace: YAML identity, markdown files, and tool sync.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from identity.workspace import IdentityWorkspace


@pytest.fixture
def workspace_home(tmp_path: Path) -> Path:
    """Isolated THEORA home directory."""
    return tmp_path / "theora_identity"


@pytest.fixture
def workspace(workspace_home: Path) -> IdentityWorkspace:
    return IdentityWorkspace(home_dir=str(workspace_home))


class TestIdentityWorkspaceInit:
    """``IdentityWorkspace.__init__`` creates the expected layout."""

    def test_creates_directory_structure(self, workspace_home: Path) -> None:
        IdentityWorkspace(home_dir=str(workspace_home))
        assert workspace_home.is_dir()
        assert (workspace_home / "IDENTITY.yaml").exists()
        assert (workspace_home / "SOUL.md").exists()
        assert (workspace_home / "MEMORY.md").exists()
        assert (workspace_home / "TOOLS.md").exists()
        # Defaults were written
        assert "THEORA" in (workspace_home / "IDENTITY.yaml").read_text()


class TestIdentityYamlRoundtrip:
    def test_load_save_identity_roundtrip(self, workspace: IdentityWorkspace) -> None:
        data = {
            "name": "TestAgent",
            "tagline": "Roundtrip tagline",
            "rules": ["rule a", "rule b"],
        }
        workspace.save_identity(data)
        loaded = workspace.load_identity()
        assert loaded.get("name") == "TestAgent"
        assert loaded.get("tagline") == "Roundtrip tagline"
        assert loaded.get("rules") == ["rule a", "rule b"]
        raw = (Path(workspace._home) / "IDENTITY.yaml").read_text()
        parsed = yaml.safe_load(raw)
        assert parsed == loaded


class TestMarkdownFiles:
    def test_read_write_soul(self, workspace: IdentityWorkspace) -> None:
        workspace.write_soul("Soul content alpha")
        assert workspace.read_soul() == "Soul content alpha"

    def test_read_write_memory(self, workspace: IdentityWorkspace) -> None:
        workspace.write_memory("Memory note beta")
        assert workspace.read_memory() == "Memory note beta"

    def test_read_write_tools(self, workspace: IdentityWorkspace) -> None:
        workspace.write_tools("Tools gamma")
        assert workspace.read_tools() == "Tools gamma"


class TestBuildSystemPrompt:
    def test_build_system_prompt_non_empty_and_includes_identity(self, workspace: IdentityWorkspace) -> None:
        workspace.save_identity({"name": "CustomName", "tagline": "A tagline."})
        workspace.write_soul("Soul line.")
        prompt = workspace.build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt.strip()) > 0
        assert "CustomName" in prompt
        assert "A tagline." in prompt
        assert "Soul line." in prompt


class TestSyncToolsFromRegistry:
    def test_sync_tools_from_registry_writes_skill_names(self, workspace: IdentityWorkspace) -> None:
        ep = MagicMock()
        ep.id = "default"
        ep.description = "Does a thing"

        sk = MagicMock()
        sk.skill_id = "fake_skill"
        sk.name = "Fake Skill"
        sk.safety_level = "SAFE"
        sk.description = "Fake description for tests."
        sk.endpoints = [ep]

        registry = MagicMock()
        registry.skills = {"fake_skill": sk}

        workspace.sync_tools_from_registry(registry)
        tools_md = workspace.read_tools()
        assert "Fake Skill" in tools_md or "fake_skill" in tools_md
        assert "SAFE" in tools_md
        assert "fake_skill__default" in tools_md
