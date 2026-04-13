"""Tests for voice.realtime_proxy — RealtimeProxy session management."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice.realtime_proxy import RealtimeProxy, RealtimeSession


@pytest.fixture()
def proxy():
    mock_personality = MagicMock()
    mock_personality.current_time_of_day.return_value = "morning"
    mock_personality.get_voice_instructions.return_value = "You are FERAL, a helpful AI."

    with patch("voice.realtime_proxy.os.getenv", return_value="sk-test-key"), \
         patch("voice.personality.VoicePersonality", return_value=mock_personality):
        return RealtimeProxy(
            skill_registry=MagicMock(),
            skill_executor=MagicMock(),
            memory=MagicMock(),
            perception=MagicMock(),
        )


# ── Init / availability ─────────────────────────────────────────

def test_available_with_api_key(proxy):
    assert proxy.available is True


def test_unavailable_without_key():
    with patch("voice.realtime_proxy.os.getenv", return_value=""), \
         patch("voice.personality.VoicePersonality"):
        p = RealtimeProxy()
    assert p.available is False


# ── Session tracking ─────────────────────────────────────────────

def test_get_session_returns_none_for_unknown(proxy):
    assert proxy.get_session("missing-node") is None


def test_get_session_after_manual_insert(proxy):
    rs = MagicMock(spec=RealtimeSession)
    proxy._sessions["sid-1"] = rs
    proxy._node_to_session["node-1"] = "sid-1"
    assert proxy.get_session("node-1") is rs


# ── System prompt building ───────────────────────────────────────

def test_system_prompt_includes_environment_context(proxy):
    frame = MagicMock()
    frame.to_system_context.return_value = "temperature: 72F"
    proxy._perception.get_frame.return_value = frame
    proxy._memory.working_get.return_value = []
    proxy._memory.build_context_for_llm.return_value = ""

    prompt = proxy._build_system_prompt("sess-1")
    assert "environment" in prompt.lower() or "sensor" in prompt.lower()


def test_system_prompt_includes_memory(proxy):
    frame = MagicMock()
    frame.to_system_context.return_value = ""
    proxy._perception.get_frame.return_value = frame
    proxy._memory.working_get.return_value = []
    proxy._memory.build_context_for_llm.return_value = "User asked about weather earlier"

    prompt = proxy._build_system_prompt("sess-1")
    assert "weather" in prompt.lower()


# ── Tool list generation ─────────────────────────────────────────

def test_get_tools_from_registry(proxy):
    proxy._skill_registry.get_all_tools.return_value = [
        {"function": {"name": "web_search__search", "description": "Search"}}
    ]
    tools = proxy._get_tools()
    assert len(tools) == 1


def test_get_tools_empty_without_registry():
    with patch("voice.realtime_proxy.os.getenv", return_value="sk-key"), \
         patch("voice.personality.VoicePersonality"):
        p = RealtimeProxy()
    assert p._get_tools() == []


# ── Audio relay ──────────────────────────────────────────────────

async def test_relay_audio_forwards_to_session(proxy):
    rs = MagicMock(spec=RealtimeSession)
    rs.connected = True
    rs.send_audio = AsyncMock()
    proxy._sessions["sid-1"] = rs
    proxy._node_to_session["node-1"] = "sid-1"

    await proxy.relay_audio("node-1", "PCM_B64==")
    rs.send_audio.assert_awaited_once_with("PCM_B64==")


# ── Graceful shutdown ────────────────────────────────────────────

async def test_shutdown_disconnects_all(proxy):
    rs = MagicMock(spec=RealtimeSession)
    rs.disconnect = AsyncMock()
    rs.node_id = "node-1"
    proxy._sessions["sid-1"] = rs
    proxy._node_to_session["node-1"] = "sid-1"

    await proxy.shutdown()
    rs.disconnect.assert_awaited_once()
    assert len(proxy._sessions) == 0
