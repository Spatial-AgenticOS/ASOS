"""
THEORA Skill Registry — Loading and Managing Skills
=====================================================
Loads skill manifests, provides embedding-based search,
and converts skills to LLM tool definitions.
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from models.skill_manifest import SkillManifest, WEATHER_SKILL

logger = logging.getLogger("theora.skills")


class SkillRegistry:
    """Manages all registered skills and provides fast lookup."""

    def __init__(self):
        self.skills: dict[str, SkillManifest] = {}
        self._tool_cache: dict[str, list[dict]] = {}  # skill_id → LLM tool defs

    def load_builtin_skills(self):
        """Load the default skills that ship with THEORA."""
        # Load hardcoded weather skill
        self.register(WEATHER_SKILL)

        # Load all JSON manifests from the manifests directory
        manifests_dir = Path(__file__).parent / "manifests"
        if manifests_dir.exists():
            self.load_from_directory(manifests_dir)

        logger.info(f"Loaded {len(self.skills)} skills total")

    def register(self, manifest: SkillManifest):
        """Register a skill manifest."""
        self.skills[manifest.skill_id] = manifest
        self._tool_cache[manifest.skill_id] = self._manifest_to_tools(manifest)
        logger.info(f"Registered skill: {manifest.brand.name} ({manifest.skill_id})")

    def load_from_file(self, path: str | Path):
        """Load a skill manifest from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        manifest = SkillManifest(**data)
        self.register(manifest)

    def load_from_directory(self, directory: str | Path):
        """Load all skill manifests from a directory."""
        p = Path(directory)
        for skill_file in p.glob("*.json"):
            try:
                self.load_from_file(skill_file)
            except Exception as e:
                logger.error(f"Failed to load skill {skill_file}: {e}")

    def get_all_tools(self) -> list[dict]:
        """Get all tools from all skills in LLM-compatible format."""
        tools = []
        for skill_id, skill_tools in self._tool_cache.items():
            tools.extend(skill_tools)
        return tools

    def find_skills_for_query(self, query: str, top_k: int = 5) -> list[SkillManifest]:
        """
        Find the most relevant skills for a user query.
        
        v1: Improved keyword/trigger phrase matching with tiered scoring.
        v2: Embedding-based semantic search (future).
        """
        scored: list[tuple[float, SkillManifest]] = []

        query_lower = query.lower().strip()
        query_words = set(query_lower.split())

        for skill in self.skills.values():
            score = 0.0

            # Check trigger phrases — highest priority
            best_trigger_score = 0.0
            for phrase in skill.trigger_phrases:
                phrase_lower = phrase.lower()

                # Exact match: query IS the trigger phrase
                if phrase_lower == query_lower:
                    best_trigger_score = max(best_trigger_score, 25.0)
                # Trigger phrase fully contained in query
                elif phrase_lower in query_lower:
                    best_trigger_score = max(best_trigger_score, 20.0)
                # Query fully contained in trigger phrase
                elif query_lower in phrase_lower:
                    best_trigger_score = max(best_trigger_score, 15.0)
                else:
                    # Partial word overlap, normalized by phrase length
                    phrase_words = set(phrase_lower.split())
                    overlap = phrase_words & query_words
                    if overlap:
                        overlap_ratio = len(overlap) / max(len(phrase_words), 1)
                        phrase_score = len(overlap) * 3.0 * overlap_ratio
                        best_trigger_score = max(best_trigger_score, phrase_score)

            score += best_trigger_score

            # Check categories — strong signal
            for cat in skill.categories:
                if cat.lower() in query_lower:
                    score += 5.0

            # Check description — weak signal, heavily normalized
            desc_words = set(skill.description.lower().split())
            # Remove common stop words to avoid noise
            stop_words = {"the", "a", "an", "and", "or", "for", "to", "in", "on", "of", "is", "it", "get", "from", "your", "with"}
            meaningful_desc = desc_words - stop_words
            meaningful_query = query_words - stop_words
            desc_overlap = meaningful_desc & meaningful_query
            score += len(desc_overlap) * 0.5  # Very low weight to prevent noise

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored[:top_k]]

    def get_tools_for_skills(self, skills: list[SkillManifest]) -> list[dict]:
        """Get LLM tool definitions for a subset of skills."""
        tools = []
        for skill in skills:
            tools.extend(self._tool_cache.get(skill.skill_id, []))
        return tools

    def _manifest_to_tools(self, manifest: SkillManifest) -> list[dict]:
        """
        Convert a skill manifest to LLM function-calling tool definitions.
        This is what gets injected into the LLM's tool list.
        Compatible with OpenAI function calling format.
        """
        tools = []
        for endpoint in manifest.endpoints:
            properties = {}
            required = []
            for param in endpoint.params:
                prop: dict = {
                    "type": param.type if param.type != "array" else "array",
                    "description": param.description,
                }
                if param.type == "array" and param.items:
                    prop["items"] = param.items
                if param.enum:
                    prop["enum"] = param.enum
                if param.default:
                    prop["default"] = param.default
                properties[param.name] = prop
                if param.required:
                    required.append(param.name)

            tool = {
                "type": "function",
                "function": {
                    "name": f"{manifest.skill_id}__{endpoint.id}",
                    "description": f"[{manifest.brand.name}] {endpoint.description}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
                "_theora_meta": {
                    "skill_id": manifest.skill_id,
                    "endpoint_id": endpoint.id,
                    "method": endpoint.method,
                    "url": endpoint.url,
                    "ui_hint": endpoint.ui_hint,
                    "brand": manifest.brand.model_dump(),
                },
            }
            tools.append(tool)

        return tools
