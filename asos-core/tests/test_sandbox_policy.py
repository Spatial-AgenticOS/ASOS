"""Tests for sandbox policies."""
import pytest
from security.sandbox_policy import SandboxPolicy


class TestSandboxPolicy:
    def test_default_policy(self):
        p = SandboxPolicy()
        assert p.to_dict()["version"] == "1.0"
        assert p.to_dict()["name"] == "default"

    def test_network_allowlist(self):
        p = SandboxPolicy()
        assert p.can_access_domain("api.openai.com") is True
        assert p.can_access_domain("evil.example.com") is False

    def test_network_wildcard(self):
        p = SandboxPolicy()
        assert p.can_access_domain("myproject.supabase.co") is True

    def test_sensor_allowed(self):
        p = SandboxPolicy()
        assert p.can_read_sensor("heart_rate") is True
        assert p.can_read_sensor("gps") is True

    def test_actuator_confirmation(self):
        p = SandboxPolicy()
        allowed, needs_confirm = p.can_use_actuator("display")
        assert allowed is True
        assert needs_confirm is False

        allowed, needs_confirm = p.can_use_actuator("motor")
        assert allowed is False  # not in allowed list
        assert needs_confirm is True

    def test_movement_speed(self):
        p = SandboxPolicy()
        assert p.max_movement_speed() == 50

    def test_camera_allowed(self):
        p = SandboxPolicy()
        assert p.can_capture_camera() is True

    def test_skill_generation(self):
        p = SandboxPolicy()
        assert p.can_generate_skills() is True
        assert p.skill_requires_approval() is True

    def test_shell_blocked_by_default(self):
        p = SandboxPolicy()
        assert p.can_execute_shell() is False

    def test_tool_calls_limit(self):
        p = SandboxPolicy()
        assert p.max_tool_calls_per_turn() == 20

    def test_mcp_allowed(self):
        p = SandboxPolicy()
        assert p.can_use_mcp_server("github") is True

    def test_custom_policy(self):
        custom = {
            "version": "1.0",
            "name": "restrictive",
            "permissions": {"max_tier": "passive", "require_confirmation_above": "passive"},
            "network": {"mode": "denylist", "blocked_domains": ["evil.com"]},
            "hardware": {
                "sensors": {"allowed": ["heart_rate"], "blocked": ["gps"]},
                "actuators": {"allowed": [], "blocked": [], "requires_confirmation": []},
                "cameras": {"allowed": False},
                "movement": {"max_speed_pct": 10},
            },
            "skills": {"allow_generation": False, "require_approval": True, "blocked_skill_ids": []},
            "mcp": {"allow_external_servers": False},
            "execution": {"allow_shell_commands": False, "max_tool_calls_per_turn": 5},
        }
        p = SandboxPolicy(custom)
        assert p.can_read_sensor("heart_rate") is True
        assert p.can_read_sensor("gps") is False
        assert p.can_capture_camera() is False
        assert p.max_movement_speed() == 10
        assert p.can_generate_skills() is False
        assert p.can_use_mcp_server("anything") is False
        assert p.max_tool_calls_per_turn() == 5

    def test_tier_check(self):
        p = SandboxPolicy()
        assert p.can_use_tier("passive") is True
        assert p.can_use_tier("active") is True
        assert p.can_use_tier("privileged") is False

    def test_confirmation_check(self):
        p = SandboxPolicy()
        assert p.needs_confirmation("passive") is False
        assert p.needs_confirmation("active") is False
        assert p.needs_confirmation("privileged") is True
