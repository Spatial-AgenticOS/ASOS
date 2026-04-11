"""FERAL System Settings skill — read/write user identity, agent personality, and config."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from skills.base import BaseSkill
from skills.impl import register_skill
from config.loader import feral_home

logger = logging.getLogger("feral.skills.system_settings")


def _home() -> Path:
    h = feral_home()
    h.mkdir(parents=True, exist_ok=True)
    return h


@register_skill
class SystemSettingsSkill(BaseSkill):
    name = "System Settings"
    description = "Read and modify FERAL identity, personality, and configuration."
    safety_level = "PRIVILEGED"

    def __init__(self) -> None:
        super().__init__(skill_id="system_settings")

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        if endpoint_id == "create_skill":
            return await self._create_skill(args)

        try:
            handler = {
                "read_user_profile": self._read_user_profile,
                "update_user_profile": self._update_user_profile,
                "read_agent_personality": self._read_agent_personality,
                "update_agent_personality": self._update_agent_personality,
                "read_settings": self._read_settings,
                "update_setting": self._update_setting,
            }.get(endpoint_id)

            if not handler:
                return {"success": False, "status_code": 404, "data": None, "error": f"Unknown endpoint: {endpoint_id}"}
            return handler(args)
        except Exception as e:
            logger.exception("system_settings error")
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}

    def _read_user_profile(self, args: dict) -> dict:
        user_md = _home() / "USER.md"
        content = user_md.read_text() if user_md.exists() else ""
        return {"success": True, "status_code": 200, "data": {"content": content}, "error": None}

    def _update_user_profile(self, args: dict) -> dict:
        home = _home()
        raw = args.get("raw_content")
        if raw:
            (home / "USER.md").write_text(raw)
        else:
            lines = ["# About Me\n"]
            if args.get("name"):
                lines.append(f"My name is {args['name']}.")
            if args.get("location"):
                lines.append(f"I live in {args['location']}.")
            if args.get("occupation"):
                lines.append(f"I work as {args['occupation']}.")
            if args.get("interests"):
                lines.append(f"\n## Interests\n{args['interests']}")
            (home / "USER.md").write_text("\n".join(lines) + "\n")

        return {"success": True, "status_code": 200, "data": {"updated": "USER.md"}, "error": None}

    def _read_agent_personality(self, args: dict) -> dict:
        home = _home()
        soul = (home / "SOUL.md").read_text() if (home / "SOUL.md").exists() else ""
        identity_path = home / "IDENTITY.yaml"
        name = "FERAL"
        if identity_path.exists():
            try:
                import yaml
                data = yaml.safe_load(identity_path.read_text()) or {}
                name = data.get("name", "FERAL")
            except Exception:
                pass
        return {
            "success": True, "status_code": 200,
            "data": {"name": name, "soul_content": soul},
            "error": None,
        }

    def _update_agent_personality(self, args: dict) -> dict:
        home = _home()
        identity_path = home / "IDENTITY.yaml"
        identity_data = {}
        if identity_path.exists():
            try:
                import yaml
                identity_data = yaml.safe_load(identity_path.read_text()) or {}
            except Exception:
                pass

        agent_name = args.get("agent_name") or identity_data.get("name", "FERAL")
        personality = args.get("personality")
        tts_voice = args.get("tts_voice")

        if personality:
            (home / "SOUL.md").write_text(f"# {agent_name}\n\n{personality}\n")

        identity_data["name"] = agent_name
        if personality:
            identity_data["personality"] = personality
        if tts_voice:
            identity_data.setdefault("voice", {})["tts_voice"] = tts_voice

        try:
            import yaml
            identity_path.write_text(yaml.dump(identity_data, default_flow_style=False, sort_keys=False))
        except ImportError:
            identity_path.write_text(json.dumps(identity_data, indent=2))

        return {"success": True, "status_code": 200, "data": {"updated": "IDENTITY.yaml + SOUL.md"}, "error": None}

    def _read_settings(self, args: dict) -> dict:
        from config.loader import ConfigLoader
        loader = ConfigLoader()
        loader.discover()
        safe = loader.to_client_safe_dict()
        return {"success": True, "status_code": 200, "data": safe, "error": None}

    def _update_setting(self, args: dict) -> dict:
        section = args.get("section", "")
        key = args.get("key", "")
        value = args.get("value", "")
        if not section or not key:
            return {"success": False, "status_code": 400, "data": None, "error": "section and key are required"}

        if value.lower() in ("true", "false"):
            value = value.lower() == "true"

        from config.loader import ConfigLoader
        loader = ConfigLoader()
        loader.discover()
        loader.update_settings(section, key, value)
        return {"success": True, "status_code": 200, "data": {"section": section, "key": key, "value": value}, "error": None}

    @staticmethod
    def _is_high_risk_capability(text: str) -> bool:
        lowered = (text or "").lower()
        risky_tokens = (
            "rm -rf", "delete all", "erase disk", "factory reset", "format disk",
            "shutdown", "reboot", "self destruct", "credential dump",
        )
        return any(token in lowered for token in risky_tokens)

    async def _create_skill(self, args: dict) -> dict:
        """Generate a new skill from a capability description and auto-approve it."""
        capability = args.get("capability", "").strip()
        if not capability:
            return {"success": False, "status_code": 400, "data": None, "error": "capability description is required"}
        if len(capability) < 8:
            return {"success": False, "status_code": 400, "data": None, "error": "capability description is too short"}
        if self._is_high_risk_capability(capability):
            return {"success": False, "status_code": 403, "data": None, "error": "capability blocked by safety policy"}

        try:
            from api.server import state
            if not state.skill_gen:
                return {"success": False, "status_code": 503, "data": None, "error": "Skill generator not initialized"}

            service = args.get("service", "")
            manifest = await state.skill_gen.generate_skill(capability, service)
            if not manifest:
                return {"success": False, "status_code": 500, "data": None, "error": "Failed to generate skill manifest"}

            skill_id = manifest.get("skill_id", "")
            auto_raw = args.get("auto_approve", True)
            auto_approve = auto_raw if isinstance(auto_raw, bool) else str(auto_raw).lower() in ("true", "1", "yes", "on")
            if auto_approve:
                approved = await state.skill_gen.approve_skill(skill_id)
                if not approved:
                    return {"success": False, "status_code": 500, "data": None, "error": f"Failed to register skill: {skill_id}"}
            else:
                approved = False

            return {
                "success": True, "status_code": 200,
                "data": {
                    "skill_id": skill_id,
                    "name": manifest.get("brand", {}).get("name", skill_id),
                    "endpoints": len(manifest.get("endpoints", [])),
                    "auto_approved": approved,
                    "needs_approval": not approved,
                    "message": (
                        f"Skill '{skill_id}' created and ready to use."
                        if approved
                        else f"Skill '{skill_id}' generated and pending approval."
                    ),
                },
                "error": None,
            }
        except Exception as e:
            logger.exception("create_skill failed")
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}
