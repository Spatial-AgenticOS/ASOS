"""
Digital Twin skill implementation.

Bridges the ``DigitalTwin`` agent into the skill registry so the LLM
can call ``digital_twin__ask``, ``digital_twin__predict_preference``,
and ``digital_twin__daily_reflection`` as regular tool calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.digital_twin import DigitalTwin

logger = logging.getLogger("feral.skills.digital_twin")

_twin_instance: DigitalTwin | None = None


def set_twin(twin: DigitalTwin):
    global _twin_instance
    _twin_instance = twin


def get_twin_skill_manifest() -> dict:
    import json
    from pathlib import Path

    manifest_path = Path(__file__).parent.parent / "manifests" / "digital_twin.json"
    return json.loads(manifest_path.read_text())


class DigitalTwinSkillBridge:
    """Wraps the DigitalTwin agent as a skill the orchestrator can invoke."""

    def __init__(self):
        self.skill_id = "digital_twin"

    async def execute(self, endpoint_id: str, args: dict, vault: dict) -> dict:
        if not _twin_instance:
            return {
                "success": False,
                "status_code": 503,
                "data": {},
                "error": "Digital twin not initialized. Run setup wizard first.",
            }

        try:
            if endpoint_id == "ask":
                question = args.get("question", "")
                if not question:
                    return {"success": False, "status_code": 400, "data": {}, "error": "question is required"}
                answer = await _twin_instance.ask(question)
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"answer": answer, "reasoning_sources": ["memory", "identity", "knowledge_graph"]},
                }

            elif endpoint_id == "predict_preference":
                category = args.get("category", "")
                if not category:
                    return {"success": False, "status_code": 400, "data": {}, "error": "category is required"}
                result = await _twin_instance.predict_preference(category)
                return {"success": True, "status_code": 200, "data": result}

            elif endpoint_id == "daily_reflection":
                reflection = await _twin_instance.daily_reflection()
                return {"success": True, "status_code": 200, "data": {"reflection": reflection}}

            else:
                return {"success": False, "status_code": 404, "data": {}, "error": f"Unknown endpoint: {endpoint_id}"}

        except Exception as e:
            logger.error("Digital twin skill error: %s", e)
            return {"success": False, "status_code": 500, "data": {}, "error": str(e)}
