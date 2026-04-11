from __future__ import annotations
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger("feral.skills.base")

class BaseSkill:
    """
    Standard interface for Python-backed skills.
    
    Why use this instead of purely declarative JSON HTTP templates?
    1. Complex workflows (e.g., OAuth, paginated APIs, GraphQL).
    2. Data aggregation (calling 3 different APIs and summarizing).
    3. Hardware control (e.g., talking to ROS nodes, local binary execution).
    
    A python skill implements an `execute` method that handles arbitrary logic
    and returns a standard dictionary.
    """
    
    def __init__(self, skill_id: str):
        self.skill_id = skill_id

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        """
        Execute this skill.
        
        Args:
            endpoint_id: The `id` defined in the skill's JSON endpoints array.
            args: The extracted parameters from the LLM.
            vault: The local vault containing API keys (e.g., FERAL_KEY_...).
            
        Returns:
            Dict conforming to the SkillExecutor output format:
            {
                "success": bool,
                "status_code": int,
                "data": any (JSON serializable),
                "error": str | None
            }
        """
        raise NotImplementedError("Subclasses must implement execute()")

    def get_api_key(self, vault: Dict[str, str], fallback_env: Optional[str] = None) -> Optional[str]:
        """Helper to safely retrieve the API key."""
        key = vault.get(self.skill_id)
        if not key and fallback_env:
            import os
            key = os.getenv(fallback_env)
        return key
