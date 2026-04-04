"""
THEORA Sandbox Policies — Declarative Security for Hardware + Software
=======================================================================
NemoClaw uses YAML policies for network/filesystem sandboxing.
THEORA extends this to HARDWARE — you can declare what a device is
allowed to do, what sensors can be read, what actuators can move,
and at what rate.

This is the missing piece in every other agent system:
  NemoClaw can sandbox which URLs a process can reach.
  THEORA can sandbox which direction a robot arm can move.

Policy file: ~/.theora/policies/default.yaml (or per-device)
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger("theora.sandbox_policy")


class SandboxPolicy:
    """
    Declarative security policy that governs what agents and devices can do.
    Loaded from YAML/dict configuration.
    """

    def __init__(self, policy_data: Optional[dict] = None):
        self._data = policy_data or self._default_policy()

    @staticmethod
    def _default_policy() -> dict:
        return {
            "version": "1.0",
            "name": "default",
            "description": "THEORA default safety policy",

            "permissions": {
                "max_tier": "active",
                "require_confirmation_above": "active",
                "auto_approve_categories": ["sensor", "display"],
            },

            "network": {
                "mode": "allowlist",
                "allowed_domains": [
                    "api.openai.com",
                    "api.anthropic.com",
                    "generativelanguage.googleapis.com",
                    "api.tavily.com",
                    "api.github.com",
                    "*.supabase.co",
                ],
                "blocked_domains": [],
                "max_requests_per_minute": 60,
            },

            "filesystem": {
                "read_paths": [
                    "~/.theora/",
                    "/tmp/theora/",
                ],
                "write_paths": [
                    "~/.theora/skills/",
                    "~/.theora/memory/",
                    "/tmp/theora/",
                ],
                "blocked_paths": [
                    "~/.ssh/",
                    "~/.aws/",
                    "~/.gnupg/",
                ],
            },

            "hardware": {
                "sensors": {
                    "allowed": ["heart_rate", "spo2", "temperature", "uv", "steps",
                                "accelerometer", "gyroscope", "ambient_light", "gps"],
                    "blocked": [],
                    "max_read_rate_per_second": {
                        "heart_rate": 1,
                        "spo2": 0.1,
                        "temperature": 0.05,
                        "gps": 0.2,
                    },
                },
                "actuators": {
                    "allowed": ["display", "speaker", "haptic", "led"],
                    "blocked": [],
                    "requires_confirmation": ["motor", "servo", "relay", "lock", "valve"],
                    "max_actions_per_minute": 30,
                },
                "cameras": {
                    "allowed": True,
                    "max_captures_per_minute": 6,
                    "auto_analyze": True,
                    "store_frames": False,
                },
                "movement": {
                    "max_speed_pct": 50,
                    "restricted_zones": [],
                    "emergency_stop_enabled": True,
                    "requires_confirmation_above_speed": 30,
                },
            },

            "skills": {
                "allow_generation": True,
                "require_approval": True,
                "max_pending": 10,
                "blocked_skill_ids": [],
                "rate_limits": {},
            },

            "memory": {
                "allow_persistent_storage": True,
                "allow_knowledge_graph": True,
                "max_notes": 10000,
                "max_episodes": 5000,
                "auto_forget_after_days": None,
            },

            "mcp": {
                "allow_external_servers": True,
                "allowed_servers": [],
                "blocked_servers": [],
                "max_concurrent_connections": 5,
            },

            "execution": {
                "max_tool_calls_per_turn": 20,
                "max_total_actions_per_session": 200,
                "timeout_per_action_ms": 30000,
                "allow_shell_commands": False,
                "allow_file_write": False,
                "allow_network_requests": True,
            },
        }

    @classmethod
    def load_from_file(cls, path: str) -> "SandboxPolicy":
        """Load a policy from a YAML or JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            logger.info(f"Policy file not found, using defaults: {path}")
            return cls()

        import json
        if file_path.suffix in (".yaml", ".yml"):
            try:
                import yaml
                with open(file_path) as f:
                    data = yaml.safe_load(f)
            except ImportError:
                logger.warning("PyYAML not installed, falling back to JSON")
                return cls()
        else:
            with open(file_path) as f:
                data = json.load(f)

        return cls(data)

    @classmethod
    def load_default(cls) -> "SandboxPolicy":
        home = os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))
        policy_dir = Path(home) / "policies"
        for name in ["default.yaml", "default.yml", "default.json"]:
            p = policy_dir / name
            if p.exists():
                return cls.load_from_file(str(p))
        return cls()

    # ─────────────────────────────────────────
    # Permission Checks
    # ─────────────────────────────────────────

    def can_use_tier(self, tier: str) -> bool:
        from security.vault import PermissionTier
        max_tier = self._data.get("permissions", {}).get("max_tier", "active")
        return PermissionTier.tier_level(tier) <= PermissionTier.tier_level(max_tier)

    def needs_confirmation(self, tier: str) -> bool:
        from security.vault import PermissionTier
        threshold = self._data.get("permissions", {}).get("require_confirmation_above", "active")
        return PermissionTier.tier_level(tier) > PermissionTier.tier_level(threshold)

    # ─────────────────────────────────────────
    # Network Checks
    # ─────────────────────────────────────────

    def can_access_domain(self, domain: str) -> bool:
        net = self._data.get("network", {})
        blocked = net.get("blocked_domains", [])
        if any(self._domain_match(domain, b) for b in blocked):
            return False
        mode = net.get("mode", "allowlist")
        if mode == "allowlist":
            allowed = net.get("allowed_domains", [])
            return any(self._domain_match(domain, a) for a in allowed)
        return True

    # ─────────────────────────────────────────
    # Hardware Checks
    # ─────────────────────────────────────────

    def can_read_sensor(self, sensor_type: str) -> bool:
        hw = self._data.get("hardware", {}).get("sensors", {})
        blocked = hw.get("blocked", [])
        if sensor_type in blocked:
            return False
        allowed = hw.get("allowed", [])
        return sensor_type in allowed or not allowed

    def can_use_actuator(self, actuator_type: str) -> tuple[bool, bool]:
        """Returns (allowed, needs_confirmation)."""
        hw = self._data.get("hardware", {}).get("actuators", {})
        blocked = hw.get("blocked", [])
        if actuator_type in blocked:
            return False, False
        needs_confirm = actuator_type in hw.get("requires_confirmation", [])
        allowed = hw.get("allowed", [])
        is_allowed = actuator_type in allowed or not allowed
        return is_allowed, needs_confirm

    def max_movement_speed(self) -> int:
        return self._data.get("hardware", {}).get("movement", {}).get("max_speed_pct", 50)

    def can_capture_camera(self) -> bool:
        return self._data.get("hardware", {}).get("cameras", {}).get("allowed", True)

    # ─────────────────────────────────────────
    # Skill Checks
    # ─────────────────────────────────────────

    def can_generate_skills(self) -> bool:
        return self._data.get("skills", {}).get("allow_generation", True)

    def skill_requires_approval(self) -> bool:
        return self._data.get("skills", {}).get("require_approval", True)

    def is_skill_blocked(self, skill_id: str) -> bool:
        blocked = self._data.get("skills", {}).get("blocked_skill_ids", [])
        return skill_id in blocked

    # ─────────────────────────────────────────
    # MCP Checks
    # ─────────────────────────────────────────

    def can_use_mcp_server(self, server_name: str) -> bool:
        mcp = self._data.get("mcp", {})
        if not mcp.get("allow_external_servers", True):
            return False
        blocked = mcp.get("blocked_servers", [])
        if server_name in blocked:
            return False
        allowed = mcp.get("allowed_servers", [])
        return not allowed or server_name in allowed

    # ─────────────────────────────────────────
    # Execution Checks
    # ─────────────────────────────────────────

    def can_execute_shell(self) -> bool:
        return self._data.get("execution", {}).get("allow_shell_commands", False)

    def max_tool_calls_per_turn(self) -> int:
        return self._data.get("execution", {}).get("max_tool_calls_per_turn", 20)

    # ─────────────────────────────────────────
    # Utils
    # ─────────────────────────────────────────

    @staticmethod
    def _domain_match(domain: str, pattern: str) -> bool:
        if pattern.startswith("*."):
            return domain.endswith(pattern[1:]) or domain == pattern[2:]
        return domain == pattern

    def to_dict(self) -> dict:
        return self._data

    def save(self, path: Optional[str] = None):
        import json
        if path is None:
            home = os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))
            p = Path(home) / "policies" / "default.json"
        else:
            p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(self._data, f, indent=2)
        logger.info(f"Policy saved: {p}")
