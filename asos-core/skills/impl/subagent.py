"""
Subagent skill shim.

Execution is handled directly in `agents.orchestrator.Orchestrator` so the
tool has access to the active session, skills, and tool executor.
"""

from __future__ import annotations

from typing import Any, Dict

from skills.base import BaseSkill
from skills.impl import register_skill


@register_skill
class SubagentSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="subagent")

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        _ = args
        _ = vault
        return {
            "success": False,
            "status_code": 501,
            "data": None,
            "error": (
                f"Endpoint '{endpoint_id}' must be executed through orchestrator runtime. "
                "Use LLM tool calling path, not direct executor mode."
            ),
        }
