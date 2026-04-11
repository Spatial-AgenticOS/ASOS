"""Tests for the graduated safety permission system.
Self-contained — mirrors the logic from orchestrator.py without importing it
to avoid heavyweight dependencies (fastapi, etc.) in unit tests."""
import pytest


class SafetyLevel:
    AUTO = "auto"
    CONFIRM = "confirm"
    DENY = "deny"


def classify_safety(tool_name: str, args: dict) -> str:
    """Mirror of Orchestrator._classify_safety for unit testing."""
    name_lower = tool_name.lower()

    deny_actions = ["format", "erase_all", "factory_reset", "self_destruct"]
    if any(d in name_lower for d in deny_actions):
        return SafetyLevel.DENY
    if ("robot_move" in name_lower or "actuator" in name_lower) and args.get("speed", 0) > 80:
        return SafetyLevel.DENY

    auto_patterns = [
        "search", "query", "get", "list", "current", "now_playing",
        "forecast", "status", "read", "notes_memory", "web_search",
    ]
    if any(p in name_lower for p in auto_patterns):
        return SafetyLevel.AUTO

    confirm_patterns = [
        "send", "post", "create", "delete", "update", "move", "grip",
        "play", "pause", "skip", "volume", "lock", "message", "order",
        "schedule", "daemon", "execute", "robot", "actuator", "motor",
    ]
    if any(p in name_lower for p in confirm_patterns):
        return SafetyLevel.CONFIRM

    return SafetyLevel.AUTO


class TestSafetyClassification:
    def test_search_is_auto(self):
        assert classify_safety("web_search__web_search", {"q": "weather"}) == SafetyLevel.AUTO

    def test_notes_is_auto(self):
        assert classify_safety("notes_memory__save_note", {"content": "test"}) == SafetyLevel.AUTO

    def test_read_is_auto(self):
        assert classify_safety("github_api__get_repos", {}) == SafetyLevel.AUTO

    def test_send_message_is_confirm(self):
        assert classify_safety("messaging_sms__send_sms", {"to": "+1234", "body": "hi"}) == SafetyLevel.CONFIRM

    def test_robot_move_normal_is_confirm(self):
        assert classify_safety("robot_ext__robot_move", {"direction": "forward", "speed": 30}) == SafetyLevel.CONFIRM

    def test_robot_move_fast_is_deny(self):
        assert classify_safety("robot_ext__robot_move", {"direction": "forward", "speed": 90}) == SafetyLevel.DENY

    def test_format_is_deny(self):
        assert classify_safety("desktop_control__format_disk", {}) == SafetyLevel.DENY

    def test_factory_reset_is_deny(self):
        assert classify_safety("device__factory_reset", {}) == SafetyLevel.DENY

    def test_play_music_is_confirm(self):
        assert classify_safety("spotify_music__play_song", {"uri": "..."}) == SafetyLevel.CONFIRM

    def test_unknown_tool_is_auto(self):
        assert classify_safety("totally_unknown__something", {}) == SafetyLevel.AUTO

    def test_volume_control_is_confirm(self):
        assert classify_safety("desktop_control__volume_set", {"level": 50}) == SafetyLevel.CONFIRM

    def test_list_endpoint_is_auto(self):
        assert classify_safety("spotify_music__list_playlists", {}) == SafetyLevel.AUTO

    def test_status_is_auto(self):
        assert classify_safety("smart_home__status_lights", {}) == SafetyLevel.AUTO
