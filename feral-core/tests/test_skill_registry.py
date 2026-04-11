"""
Unit tests for `skills.registry.SkillRegistry`.

Covers registration, builtin loading, LLM tool projection, and JSON manifests.
"""

from __future__ import annotations

import json
from pathlib import Path

from models.skill_manifest import BrandProfile, EndpointParam, SkillEndpoint, SkillManifest
from skills.registry import SkillRegistry


class TestSkillRegistryBasics:
    """Core registry behavior."""

    def test_init_empty_skills_dict(self) -> None:
        """A new registry has no skills until loaded or registered."""
        reg = SkillRegistry()
        assert reg.skills == {}
        assert reg._tool_cache == {}

    def test_skills_property_returns_dict(self) -> None:
        """`skills` maps skill IDs to manifests."""
        reg = SkillRegistry()
        assert isinstance(reg.skills, dict)
        m = SkillManifest(
            skill_id="ext_test",
            brand=BrandProfile(name="Ext", primary_color="#111"),
            description="External test skill",
            endpoints=[],
        )
        reg.register(m)
        assert reg.skills["ext_test"] is m


class TestSkillRegistryLoading:
    """Builtin and file-based manifests."""

    def test_load_builtin_skills_populates(self) -> None:
        """Builtin loader registers at least the packaged default skills."""
        reg = SkillRegistry()
        reg.load_builtin_skills()
        assert len(reg.skills) >= 1
        assert "weather_current" in reg.skills

    def test_load_manifest_from_json_file(self, tmp_path: Path) -> None:
        """`load_from_file` ingests a JSON file into manifests and tools."""
        manifest = {
            "skill_id": "json_file_skill",
            "brand": {"name": "JSONSkill", "primary_color": "#222"},
            "description": "Loaded from disk",
            "endpoints": [
                {
                    "id": "ping",
                    "method": "GET",
                    "url": "https://example.test/ping",
                    "description": "Ping",
                    "params": [],
                }
            ],
        }
        path = tmp_path / "skill.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")

        reg = SkillRegistry()
        reg.load_from_file(path)
        assert "json_file_skill" in reg.skills
        tools = reg.get_tools_for_skills([reg.skills["json_file_skill"]])
        assert any(t["function"]["name"] == "json_file_skill__ping" for t in tools)


class TestSkillRegistryTools:
    """LLM tool definitions."""

    def test_register_external_skill_and_get_tools_for_skills(self) -> None:
        """Registered skills expose OpenAI-style function tools."""
        reg = SkillRegistry()
        ep = SkillEndpoint(
            id="do_thing",
            method="GET",
            url="https://example.test/x",
            description="Does a thing",
            params=[EndpointParam(name="q", type="string", description="query", required=True)],
        )
        m = SkillManifest(
            skill_id="custom_skill",
            brand=BrandProfile(name="Custom", primary_color="#333"),
            description="Custom registered skill",
            endpoints=[ep],
        )
        reg.register(m)
        tools = reg.get_tools_for_skills([m])
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "custom_skill__do_thing"
        assert "q" in tools[0]["function"]["parameters"]["properties"]
