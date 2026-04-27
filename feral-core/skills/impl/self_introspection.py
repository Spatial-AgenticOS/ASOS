"""
Self-introspection skill: lets the agent answer meta-questions about its own
surface. Removes the "I don't know which tools I have" class of failures.

Pulls live data from BrainState: channel manager, skill registry, HUP node
registry, mitosis engine, tool genesis engine. Returns compact JSON that the
LLM can render back to the user in prose.
"""
from __future__ import annotations

import logging
import platform
import socket
from typing import Any, Dict

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skill.self_introspection")


@register_skill
class SelfIntrospectionSkill(BaseSkill):
    def __init__(self):
        super().__init__("self_introspection")

    @staticmethod
    def _state():
        try:
            from api.state import state
            return state
        except Exception:
            return None

    async def execute(
        self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]
    ) -> Dict[str, Any]:
        state = self._state()
        if state is None:
            return {"success": False, "status_code": 503, "data": None, "error": "FERAL brain not ready."}

        if endpoint_id == "list_capabilities":
            return self._list_capabilities(state)
        if endpoint_id == "describe_skill":
            return self._describe_skill(state, args)
        if endpoint_id == "active_channels":
            return self._active_channels(state)
        if endpoint_id == "connected_devices":
            return self._connected_devices(state)
        if endpoint_id == "current_session":
            return self._current_session(state)
        if endpoint_id == "list_specialists":
            return self._list_specialists(state)
        if endpoint_id == "list_pending_proposals":
            return self._list_pending_proposals(state)

        return {"success": False, "status_code": 400, "data": None, "error": f"Unknown endpoint {endpoint_id!r}"}

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _skill_registry(state):
        """Return the live SkillRegistry regardless of legacy attribute name.

        Historically callers used ``state.skills``; canonical is
        ``state.skill_registry``. BrainState now exposes both, but we
        still probe defensively so this skill works against older
        snapshots + tests that mock only one of the two.
        """
        return getattr(state, "skill_registry", None) or getattr(state, "skills", None)

    def _list_capabilities(self, state) -> Dict[str, Any]:
        skills_out = []
        registry = self._skill_registry(state)
        skill_map = getattr(registry, "skills", {}) if registry is not None else {}
        try:
            for skill in skill_map.values():
                endpoints = []
                for ep in getattr(skill, "endpoints", []) or []:
                    endpoints.append({
                        "id": getattr(ep, "id", ""),
                        "description": getattr(ep, "description", ""),
                    })
                skills_out.append({
                    "skill_id": getattr(skill, "skill_id", ""),
                    "name": getattr(getattr(skill, "brand", None), "name", ""),
                    "description": getattr(skill, "description", ""),
                    "endpoints": endpoints,
                })
        except Exception as exc:
            logger.warning("list_capabilities: %s", exc)

        data = {
            "skills": skills_out,
            "active_channels": self._active_channels_payload(state),
            "connected_devices": self._connected_devices_payload(state),
            "autonomy_mode": self._autonomy_mode(state),
            "version": self._version(),
        }
        return {"success": True, "status_code": 200, "data": data, "error": None}

    def _describe_skill(self, state, args: Dict[str, Any]) -> Dict[str, Any]:
        target = (args.get("skill_id") or "").strip()
        if not target:
            return {"success": False, "status_code": 400, "data": None, "error": "skill_id required"}
        registry = self._skill_registry(state)
        skill_map = getattr(registry, "skills", {}) if registry is not None else {}
        skill = skill_map.get(target)
        if skill is None:
            return {"success": False, "status_code": 404, "data": None, "error": f"No skill named {target!r}"}
        endpoints = []
        for ep in getattr(skill, "endpoints", []) or []:
            endpoints.append({
                "id": getattr(ep, "id", ""),
                "description": getattr(ep, "description", ""),
                "params": [
                    {"name": getattr(p, "name", ""), "type": getattr(p, "type", ""), "required": getattr(p, "required", False)}
                    for p in getattr(ep, "params", []) or []
                ],
            })
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "skill_id": getattr(skill, "skill_id", ""),
                "name": getattr(getattr(skill, "brand", None), "name", ""),
                "description": getattr(skill, "description", ""),
                "endpoints": endpoints,
            },
            "error": None,
        }

    def _active_channels(self, state) -> Dict[str, Any]:
        return {"success": True, "status_code": 200, "data": {"channels": self._active_channels_payload(state)}, "error": None}

    def _connected_devices(self, state) -> Dict[str, Any]:
        return {"success": True, "status_code": 200, "data": {"devices": self._connected_devices_payload(state)}, "error": None}

    def _current_session(self, state) -> Dict[str, Any]:
        model = "unknown"
        try:
            llm = getattr(state, "llm_client", None) or getattr(state, "llm", None)
            if llm is not None:
                provider = getattr(llm, "provider", None) or type(llm).__name__
                name = getattr(llm, "model_name", None) or getattr(llm, "model", None) or "default"
                model = f"{provider}/{name}"
        except Exception:
            pass
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "version": self._version(),
                "model": model,
                "host": socket.gethostname(),
                "os": platform.system(),
                "autonomy_mode": self._autonomy_mode(state),
            },
            "error": None,
        }

    def _list_specialists(self, state) -> Dict[str, Any]:
        specialists = []
        try:
            engine = getattr(state, "agent_mitosis", None) or getattr(state, "mitosis_engine", None)
            if engine and hasattr(engine, "list_specialists"):
                for sp in engine.list_specialists():
                    specialists.append({
                        "id": getattr(sp, "id", None) or sp.get("id"),
                        "domain": getattr(sp, "domain", None) or sp.get("domain"),
                        "allowed_skills": list(getattr(sp, "allowed_skills", None) or sp.get("allowed_skills") or []),
                        "confidence": getattr(sp, "confidence", None) or sp.get("confidence", 0.0),
                    })
        except Exception as exc:
            logger.debug("list_specialists: %s", exc)
        return {"success": True, "status_code": 200, "data": {"specialists": specialists}, "error": None}

    def _list_pending_proposals(self, state) -> Dict[str, Any]:
        proposals = []
        try:
            engine = getattr(state, "tool_genesis", None) or getattr(state, "tool_genesis_engine", None)
            if engine and hasattr(engine, "list_pending_proposals"):
                for prop in engine.list_pending_proposals():
                    proposals.append(prop if isinstance(prop, dict) else {
                        "tool_id": getattr(prop, "tool_id", ""),
                        "name": getattr(prop, "name", ""),
                        "pattern": getattr(prop, "pattern", ""),
                        "autonomy": getattr(prop, "autonomy", ""),
                        "created_at": getattr(prop, "created_at", None),
                        "preview": getattr(prop, "preview", ""),
                    })
        except Exception as exc:
            logger.debug("list_pending_proposals: %s", exc)
        return {"success": True, "status_code": 200, "data": {"proposals": proposals}, "error": None}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _active_channels_payload(state) -> list[dict]:
        out: list[dict] = []
        cm = getattr(state, "channel_manager", None)
        if not cm:
            return out
        for ctype, ch in cm.channels.items():
            out.append({
                "name": ctype,
                "running": bool(getattr(ch, "_running", False)),
                "bot_username": getattr(ch, "_bot_username", None),
            })
        return out

    @staticmethod
    def _connected_devices_payload(state) -> list[dict]:
        """Return a compact view of devices known to ``state.device_registry``.

        Falls back to legacy ``node_registry`` / ``nodes`` attributes for
        any caller that still exposes them. The canonical path uses
        ``DeviceRegistry.list_devices()`` (see ``hardware/protocol.py``);
        anything else is best-effort.
        """
        try:
            registry = (
                getattr(state, "device_registry", None)
                or getattr(state, "node_registry", None)
                or getattr(state, "nodes", None)
            )
            if not registry:
                return []
            if hasattr(registry, "list_devices"):
                raw = registry.list_devices()
            elif hasattr(registry, "list_nodes"):
                raw = registry.list_nodes()
            elif hasattr(registry, "all"):
                raw = registry.all()
            elif hasattr(registry, "nodes"):
                raw = list(registry.nodes.values())
            elif hasattr(registry, "_devices"):
                raw = list(registry._devices.values())
            else:
                return []
            devices = []
            for node in raw:
                if isinstance(node, dict):
                    caps = node.get("capabilities") or []
                    devices.append({
                        "node_id": node.get("device_id") or node.get("node_id") or node.get("id"),
                        "type": node.get("device_type") or node.get("type"),
                        "name": node.get("name"),
                        "capabilities": [getattr(c, "category", c) if not isinstance(c, str) else c for c in caps],
                        "last_seen": node.get("last_seen"),
                    })
                else:
                    caps_raw = list(getattr(node, "capabilities", []) or [])
                    caps = [getattr(c, "category", None) or getattr(c, "name", None) or str(c) for c in caps_raw]
                    devices.append({
                        "node_id": getattr(node, "device_id", None) or getattr(node, "node_id", None) or getattr(node, "id", None),
                        "type": getattr(node, "device_type", None) or getattr(node, "type", None),
                        "name": getattr(node, "name", None),
                        "capabilities": caps,
                        "last_seen": getattr(node, "last_seen", None),
                    })
            return devices
        except Exception:
            return []

    @staticmethod
    def _autonomy_mode(state) -> str:
        try:
            cfg = getattr(state, "config", None)
            if cfg and hasattr(cfg, "get_setting"):
                return str(cfg.get_setting("autonomy_mode") or "hybrid")
        except Exception:
            pass
        return "hybrid"

    @staticmethod
    def _version() -> str:
        try:
            import importlib.metadata as md
            return md.version("feral-ai")
        except Exception:
            return "dev"
