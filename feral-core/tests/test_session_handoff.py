"""
Tests for agents.session_handoff — SessionHandoffManager, ConnectedDevice,
and format_for_device.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.session_handoff import (
    DEFAULT_HISTORY_DEPTH,
    NODE_TYPES,
    ConnectedDevice,
    SessionHandoffManager,
    format_for_device,
)


# ── ConnectedDevice / NODE_TYPES ─────────────────────────────────────────────


def test_connected_device_fields():
    d = ConnectedDevice(
        session_id="sess-1",
        node_type="phone",
        node_id="n1",
        connected_at=123.0,
    )
    assert d.session_id == "sess-1"
    assert d.node_type == "phone"
    assert d.node_id == "n1"
    assert d.connected_at == 123.0


def test_node_types_tuple():
    assert "phone" in NODE_TYPES
    assert "desktop" in NODE_TYPES
    assert "wristband" in NODE_TYPES
    assert "glasses" in NODE_TYPES
    assert len(NODE_TYPES) == 4


# ── SessionHandoffManager — initialization ─────────────────────────────────


def test_session_handoff_manager_init_defaults():
    mgr = SessionHandoffManager()
    assert mgr._sessions == {}
    assert mgr._daemons == {}
    assert mgr._memory is None
    assert mgr._send_to_session is None
    assert mgr._device_registry == {}


def test_session_handoff_manager_init_with_injected_sessions_and_memory():
    sessions = {"a": 1}
    memory = MagicMock()
    send = AsyncMock()
    mgr = SessionHandoffManager(sessions=sessions, memory=memory, send_to_session=send)
    assert mgr._sessions is sessions
    assert mgr._memory is memory
    assert mgr._send_to_session is send


# ── register / unregister / list ────────────────────────────────────────────


def test_register_device_defaults_node_id_to_session_id():
    mgr = SessionHandoffManager()
    mgr.register_device("full-session-id", "desktop", node_id="")
    dev = mgr._device_registry["full-session-id"]
    assert dev.node_id == "full-session-id"
    assert dev.node_type == "desktop"


def test_register_device_unknown_node_type_becomes_desktop():
    mgr = SessionHandoffManager()
    mgr.register_device("s1", "not_a_real_type", node_id="nid")
    assert mgr._device_registry["s1"].node_type == "desktop"


def test_unregister_device_removes_entry():
    mgr = SessionHandoffManager()
    mgr.register_device("s-unreg", "phone")
    mgr.unregister_device("s-unreg")
    assert "s-unreg" not in mgr._device_registry


def test_get_active_devices_returns_serializable_dicts():
    mgr = SessionHandoffManager()
    mgr.register_device("sess-a", "phone", node_id="phone-1")
    rows = mgr.get_active_devices()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess-a"
    assert rows[0]["node_type"] == "phone"
    assert rows[0]["node_id"] == "phone-1"
    assert "connected_at" in rows[0]


# ── handoff — context transfer and errors ───────────────────────────────────


@pytest.mark.asyncio
async def test_handoff_queues_when_no_matching_session():
    mgr = SessionHandoffManager(sessions={})
    mgr.register_device("only-phone", "phone")
    result = await mgr.handoff("only-phone", "desktop")
    assert result["success"] is True
    assert result["pending"] is True
    assert "available_devices" in result


@pytest.mark.asyncio
async def test_handoff_fails_when_source_equals_target():
    sessions = {"same": True}
    mgr = SessionHandoffManager(sessions=sessions)
    mgr.register_device("same", "desktop")
    result = await mgr.handoff("same", "desktop")
    assert result["success"] is False
    assert "same" in result["error"].lower() or "Source and target" in result["error"]


@pytest.mark.asyncio
async def test_handoff_transfers_working_memory():
    memory = MagicMock()
    history = [{"role": "user", "content": "hello"}]
    memory.working_get = MagicMock(return_value=history)
    memory.working_replace = MagicMock()

    sessions = {"from-sess": True, "to-sess": True}
    mgr = SessionHandoffManager(sessions=sessions, memory=memory)
    mgr.register_device("from-sess", "phone")
    mgr.register_device("to-sess", "desktop")

    result = await mgr.handoff("from-sess", "desktop", history_depth=10)

    assert result["success"] is True
    assert result["from_session_id"] == "from-sess"
    assert result["to_session_id"] == "to-sess"
    assert result["to_node_type"] == "desktop"
    assert result["messages_transferred"] == 1
    memory.working_get.assert_called_once_with("from-sess", limit=10)
    memory.working_replace.assert_called_once_with("to-sess", list(history))


@pytest.mark.asyncio
async def test_handoff_uses_default_history_depth():
    memory = MagicMock()
    memory.working_get = MagicMock(return_value=[])
    memory.working_replace = MagicMock()
    sessions = {"a": True, "b": True}
    mgr = SessionHandoffManager(sessions=sessions, memory=memory)
    mgr.register_device("a", "phone")
    mgr.register_device("b", "wristband")

    await mgr.handoff("a", "wristband")

    memory.working_get.assert_called_with("a", limit=DEFAULT_HISTORY_DEPTH)


@pytest.mark.asyncio
async def test_handoff_with_notifications_calls_send_to_session():
    memory = MagicMock()
    memory.working_get = MagicMock(return_value=[{"x": 1}])
    memory.working_replace = MagicMock()
    send = AsyncMock()
    sessions = {"old-s": True, "new-s": True}
    mgr = SessionHandoffManager(sessions=sessions, memory=memory, send_to_session=send)
    mgr.register_device("old-s", "phone")
    mgr.register_device("new-s", "desktop")

    await mgr.handoff("old-s", "desktop")

    assert send.await_count == 2
    first_call = send.await_args_list[0].args
    second_call = send.await_args_list[1].args
    assert first_call[0] == "old-s"
    assert second_call[0] == "new-s"


@pytest.mark.asyncio
async def test_handoff_notify_old_device_swallows_send_errors():
    memory = MagicMock()
    memory.working_get = MagicMock(return_value=[])
    memory.working_replace = MagicMock()
    send = AsyncMock(side_effect=[Exception("network"), None])
    sessions = {"old-s": True, "new-s": True}
    mgr = SessionHandoffManager(sessions=sessions, memory=memory, send_to_session=send)
    mgr.register_device("old-s", "phone")
    mgr.register_device("new-s", "desktop")

    with patch("agents.session_handoff.logger") as log:
        result = await mgr.handoff("old-s", "desktop")

    assert result["success"] is True
    log.warning.assert_called()


@pytest.mark.asyncio
async def test_handoff_skips_memory_when_empty_history():
    memory = MagicMock()
    memory.working_get = MagicMock(return_value=None)
    memory.working_replace = MagicMock()
    sessions = {"a": True, "b": True}
    mgr = SessionHandoffManager(sessions=sessions, memory=memory)
    mgr.register_device("a", "glasses")
    mgr.register_device("b", "desktop")

    result = await mgr.handoff("a", "desktop")
    assert result["success"] is True
    assert result["messages_transferred"] == 0
    memory.working_replace.assert_not_called()


# ── format_for_device ────────────────────────────────────────────────────────


def test_format_for_device_phone_truncates_and_no_sdui():
    long_text = "x" * 250
    out = format_for_device(long_text, {"card": True}, "phone")
    assert len(out["text"]) <= 200
    assert out["voice_optimized"] is True
    assert out["sdui"] is None


def test_format_for_device_desktop_preserves_sdui():
    out = format_for_device("full", {"ui": 1}, "desktop")
    assert out["text"] == "full"
    assert out["sdui"] == {"ui": 1}
    assert out["voice_optimized"] is False


def test_format_for_device_wristband_ack_vs_alert():
    ack = format_for_device("all good", None, "wristband")
    assert "haptic" in ack
    assert ack["text"] is None

    alert = format_for_device("This is an ALERT for you", None, "wristband")
    assert len(alert["haptic"]) >= len(ack["haptic"])


def test_format_for_device_glasses_audio_and_short_display():
    out = format_for_device("short", None, "glasses")
    assert out["audio_transcript"] == "short"
    assert out["display_text"] == "short"

    long_t = "word " * 30
    out2 = format_for_device(long_t, None, "glasses")
    assert out2["audio_transcript"] == long_t
    assert len(out2["display_text"]) <= 80


def test_format_for_device_unknown_node_falls_back_like_desktop():
    out = format_for_device("t", {"s": 1}, "tablet")
    assert out["text"] == "t"
    assert out["sdui"] == {"s": 1}


@pytest.mark.asyncio
async def test_find_session_prefers_first_matching_node_type():
    """First registered desktop session wins when multiple match the target type."""
    sessions = {"s1": True, "s2": True}
    mgr = SessionHandoffManager(sessions=sessions)
    mgr.register_device("s1", "desktop")
    mgr.register_device("s2", "desktop")

    result = await mgr.handoff("s2", "desktop")
    assert result["success"] is True
    assert result["to_session_id"] == "s1"
    assert result["from_session_id"] == "s2"

