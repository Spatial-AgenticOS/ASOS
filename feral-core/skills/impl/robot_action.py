"""Bridge between robot_action skill manifest and hardware robot arm adapter."""

from __future__ import annotations

import logging
from typing import Any, Dict

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skills.robot_action")


@register_skill
class RobotActionSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="robot_ext")
        self._adapter = None

    def _get_adapter(self):
        if self._adapter is not None:
            return self._adapter
        try:
            from hardware.adapters.robot_arm import RobotArmAdapter
            self._adapter = RobotArmAdapter()
        except ImportError:
            logger.warning("hardware.adapters.robot_arm not available")
        return self._adapter

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        adapter = self._get_adapter()
        if adapter is None:
            return {"success": False, "status_code": 500, "data": None, "error": "Robot arm adapter not available"}

        try:
            from hardware.protocol import HUPAction, HUPActionType
            action = HUPAction(
                action_id=f"skill_{endpoint_id}",
                device_id=adapter.device_id,
                capability_id=self._map_endpoint(endpoint_id),
                action_type=HUPActionType.EXECUTE,
                parameters=args,
            )
            result = await adapter.execute(action)
            return {
                "success": result.status == "success",
                "status_code": 200 if result.status == "success" else 500,
                "data": result.data,
                "error": result.error,
            }
        except Exception as e:
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}

    @staticmethod
    def _map_endpoint(endpoint_id: str) -> str:
        mapping = {
            "robot_move": "move_joints",
            "robot_grip": "gripper",
        }
        return mapping.get(endpoint_id, endpoint_id)
