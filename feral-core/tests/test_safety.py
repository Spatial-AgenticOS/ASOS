"""Tests for the graduated safety permission system.

Imports and tests the REAL production classify_safety from agents.tool_runner,
rather than duplicating the logic locally (which previously caused the
CONFIRM-before-AUTO ordering bug to go undetected).
"""
import pytest
from unittest.mock import MagicMock

from agents.tool_runner import ToolRunner, SafetyLevel


@pytest.fixture
def runner():
    """ToolRunner backed by a stub orchestrator — enough for classification tests."""
    orch = MagicMock()
    return ToolRunner(orch, autonomy_mode="hybrid")


class TestSafetyClassification:
    def test_search_is_auto(self, runner):
        assert runner.classify_safety("web_search__web_search", {"q": "weather"}) == SafetyLevel.AUTO

    def test_notes_search_is_auto(self, runner):
        assert runner.classify_safety("notes_memory__search", {"content": "test"}) == SafetyLevel.AUTO

    def test_read_is_auto(self, runner):
        assert runner.classify_safety("github_api__get_repos", {}) == SafetyLevel.AUTO

    def test_send_message_is_confirm(self, runner):
        assert runner.classify_safety("messaging_sms__send_sms", {"to": "+1234", "body": "hi"}) == SafetyLevel.CONFIRM

    def test_robot_move_normal_is_confirm(self, runner):
        assert runner.classify_safety("robot_ext__robot_move", {"direction": "forward", "speed": 30}) == SafetyLevel.CONFIRM

    def test_robot_move_fast_is_deny(self, runner):
        assert runner.classify_safety("robot_ext__robot_move", {"direction": "forward", "speed": 90}) == SafetyLevel.DENY

    def test_format_is_deny(self, runner):
        assert runner.classify_safety("desktop_control__format_disk", {}) == SafetyLevel.DENY

    def test_factory_reset_is_deny(self, runner):
        assert runner.classify_safety("device__factory_reset", {}) == SafetyLevel.DENY

    def test_play_music_is_confirm(self, runner):
        assert runner.classify_safety("spotify_music__play_song", {"uri": "..."}) == SafetyLevel.CONFIRM

    def test_unknown_tool_requires_confirmation(self, runner):
        assert runner.classify_safety("totally_unknown__something", {}) == SafetyLevel.CONFIRM

    def test_volume_control_is_confirm(self, runner):
        assert runner.classify_safety("desktop_control__volume_set", {"level": 50}) == SafetyLevel.CONFIRM

    def test_list_playlists_is_confirm_due_to_play(self, runner):
        """'playlists' contains 'play' — CONFIRM pattern wins over 'list' AUTO."""
        assert runner.classify_safety("spotify_music__list_playlists", {}) == SafetyLevel.CONFIRM

    def test_list_directory_is_auto(self, runner):
        assert runner.classify_safety("files__list_directory", {}) == SafetyLevel.AUTO

    def test_status_is_auto(self, runner):
        assert runner.classify_safety("smart_home__status_lights", {}) == SafetyLevel.AUTO

    def test_confirm_before_auto_on_delete(self, runner):
        """Regression: the old duplicated code checked AUTO before CONFIRM,
        which would mis-classify 'notes_memory__delete_note' as AUTO.
        The production code checks CONFIRM first — 'delete' must win."""
        assert runner.classify_safety("notes_memory__delete_note", {}) == SafetyLevel.CONFIRM

    def test_confirm_before_auto_on_create(self, runner):
        """'query_create' has both 'query' (AUTO) and 'create' (CONFIRM)."""
        assert runner.classify_safety("db__create_query", {}) == SafetyLevel.CONFIRM
