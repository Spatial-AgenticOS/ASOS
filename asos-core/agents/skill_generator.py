"""
THEORA Skill Generator — Self-Evolving Agent Intelligence
============================================================
The agent can propose, generate, and register new skills at runtime
based on user conversations. This is the feature that makes ASOS
fundamentally different from every other agent system.

Flow:
  1. User says: "I wish you could check my Notion pages"
  2. Agent detects an unmet capability need
  3. Agent generates a skill manifest (JSON) using LLM
  4. Brain sends a CONFIRM request to the client
  5. User approves (or edits) the skill
  6. Skill is registered live — no restart needed
  7. Agent can now use it in future conversations

This is not "tool use" — this is tool *creation*.
"""

from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.llm_provider import LLMProvider
    from skills.registry import SkillRegistry

logger = logging.getLogger("theora.skill_gen")

SKILL_GENERATION_PROMPT = """You are THEORA's skill architect. The user needs a capability that doesn't exist yet.
Based on the conversation, generate a skill manifest JSON that would satisfy the user's need.

The skill manifest format:
{
  "skill_id": "lowercase_snake_case",
  "brand": {
    "name": "Human Readable Name",
    "primary_color": "#hexcolor"
  },
  "description": "What this skill does — the LLM reads this to decide when to use it",
  "trigger_phrases": ["phrase 1", "phrase 2", "phrase 3"],
  "categories": ["category1", "category2"],
  "auth": {
    "type": "none" | "api_key" | "bearer" | "oauth2",
    "api_key_header": "X-API-Key" (if api_key)
  },
  "endpoints": [
    {
      "id": "endpoint_id",
      "method": "GET" | "POST" | "PUT" | "DELETE",
      "url": "https://api.example.com/v1/endpoint",
      "description": "What this endpoint does",
      "params": [
        {
          "name": "param_name",
          "type": "string" | "number" | "boolean",
          "description": "What this param is",
          "required": true
        }
      ],
      "returns_description": "What the response contains",
      "ui_hint": "list" | "detail_card" | "metric" | "grid_cards"
    }
  ],
  "requires_daemon": false,
  "permissions": []
}

Rules:
- Use REAL API endpoints when possible (you know many public APIs)
- If the API requires auth, set the auth type correctly
- Make trigger_phrases natural and varied
- Keep endpoint descriptions clear — the LLM uses them for routing
- If unsure of the exact URL, use a reasonable placeholder with a comment

Return ONLY the JSON. No markdown, no explanation."""

DETECT_NEED_PROMPT = """Analyze this conversation snippet. Does the user want the AI to do something it currently cannot?

Current capabilities (skills already loaded):
{skills}

Conversation:
{conversation}

If the user is asking for something no existing skill can handle, respond with:
{{"needs_skill": true, "capability": "brief description of what's needed", "service": "the service/API that could provide it"}}

If existing skills can handle it, respond with:
{{"needs_skill": false}}

Return ONLY JSON."""


class SkillGenerator:
    """
    Detects unmet capability needs and generates new skills at runtime.
    """

    def __init__(
        self,
        llm: "LLMProvider",
        skill_registry: "SkillRegistry",
        skills_dir: Optional[str] = None,
    ):
        self._llm = llm
        self._registry = skill_registry
        self._skills_dir = Path(skills_dir) if skills_dir else self._default_skills_dir()
        self._pending_skills: dict[str, dict] = {}  # skill_id → manifest dict
        self._generation_count = 0
        self._last_detection_time = 0
        self._detection_cooldown = 30  # seconds between detection attempts

    @staticmethod
    def _default_skills_dir() -> Path:
        home = os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))
        return Path(home) / "skills"

    async def detect_unmet_need(self, conversation: list[dict]) -> Optional[dict]:
        """
        Analyze recent conversation to detect if the user needs a capability
        that doesn't exist yet.
        """
        now = time.time()
        if now - self._last_detection_time < self._detection_cooldown:
            return None
        self._last_detection_time = now

        if not self._llm or not self._llm.available:
            return None

        skill_names = [
            f"{s.skill_id}: {s.description[:80]}"
            for s in self._registry.skills.values()
        ]
        skills_str = "\n".join(skill_names) if skill_names else "(none)"

        recent = conversation[-6:] if len(conversation) > 6 else conversation
        conv_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')[:200]}"
            for m in recent
        )

        prompt = DETECT_NEED_PROMPT.format(skills=skills_str, conversation=conv_str)

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
            )
            text, _ = self._llm.extract_response(response)
            if not text:
                return None

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            result = json.loads(cleaned)
            if result.get("needs_skill"):
                logger.info(f"Detected unmet need: {result.get('capability')}")
                return result
            return None

        except Exception as e:
            logger.debug(f"Need detection failed: {e}")
            return None

    async def generate_skill(self, capability: str, service: str = "") -> Optional[dict]:
        """
        Generate a new skill manifest using LLM based on what's needed.
        Returns the manifest dict or None.
        """
        if not self._llm or not self._llm.available:
            return None

        context = f"The user needs: {capability}"
        if service:
            context += f"\nSuggested service/API: {service}"

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": SKILL_GENERATION_PROMPT},
                    {"role": "user", "content": context},
                ],
                temperature=0.3,
                max_tokens=1500,
            )
            text, _ = self._llm.extract_response(response)
            if not text:
                return None

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

            manifest = json.loads(cleaned.strip())

            if "skill_id" not in manifest or "endpoints" not in manifest:
                logger.warning("Generated skill missing required fields")
                return None

            # Store as pending — needs user approval
            skill_id = manifest["skill_id"]
            self._pending_skills[skill_id] = manifest
            self._generation_count += 1
            logger.info(f"Generated skill: {skill_id} ({manifest.get('brand', {}).get('name', '?')})")
            return manifest

        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON for skill generation")
            return None
        except Exception as e:
            logger.warning(f"Skill generation failed: {e}")
            return None

    async def approve_skill(self, skill_id: str) -> bool:
        """
        User approved a pending skill. Register it live and persist to disk.
        """
        manifest = self._pending_skills.pop(skill_id, None)
        if not manifest:
            logger.warning(f"No pending skill with id: {skill_id}")
            return False

        try:
            from models.skill_manifest import SkillManifest
            skill = SkillManifest(**manifest)
            self._registry.register_skill(skill)

            self._skills_dir.mkdir(parents=True, exist_ok=True)
            path = self._skills_dir / f"{skill_id}.json"
            with open(path, "w") as f:
                json.dump(manifest, f, indent=2)

            logger.info(f"Skill approved and registered: {skill_id} → {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to register approved skill {skill_id}: {e}")
            return False

    def reject_skill(self, skill_id: str) -> bool:
        """User rejected a pending skill."""
        removed = self._pending_skills.pop(skill_id, None)
        if removed:
            logger.info(f"Skill rejected: {skill_id}")
        return removed is not None

    def get_pending_skills(self) -> list[dict]:
        """Get all skills waiting for user approval."""
        return list(self._pending_skills.values())

    @property
    def stats(self) -> dict:
        return {
            "generated_count": self._generation_count,
            "pending_count": len(self._pending_skills),
            "skills_dir": str(self._skills_dir),
        }
