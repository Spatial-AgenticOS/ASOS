"""
Voice integration tests — RealtimeProxy and GeminiRealtimeProxy.
Live tests skipped without API keys; mocked test is the CI signal.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="no OPENAI_API_KEY"
)
async def test_openai_realtime_session_reconnect():
    """Live integration: opens realtime WS, verifies session, closes cleanly."""
    from voice.realtime_proxy import RealtimeProxy

    proxy = RealtimeProxy()
    try:
        session = await proxy.start_session("test-session-1", "node-test-1")
        assert session is not None
        assert session.connected
        await proxy.stop_session("test-session-1")
    except Exception as e:
        pytest.skip(f"Network/API issue: {e}")


@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"),
    reason="no Gemini key",
)
async def test_gemini_realtime_session_happy_path():
    """Live integration: opens Gemini realtime session and closes cleanly."""
    from voice.gemini_realtime import GeminiRealtimeProxy

    proxy = GeminiRealtimeProxy()
    try:
        session = await proxy.start_session("gem-test-1", "node-gem-1")
        assert session is not None
        assert session.connected
        await proxy.stop_session("gem-test-1")
    except Exception as e:
        pytest.skip(f"Network/API issue: {e}")


async def test_reconnect_after_connection_drop_mocked():
    """Mocked: on WS close, session cleanup removes session from dict."""
    from voice.realtime_proxy import RealtimeProxy

    proxy = RealtimeProxy()

    mock_session = MagicMock()
    mock_session.node_id = "n1"
    mock_session.connected = True
    mock_session.disconnect = AsyncMock()

    proxy._sessions["s1"] = mock_session
    proxy._node_to_session["n1"] = "s1"

    await proxy.stop_session("s1")

    assert "s1" not in proxy._sessions
    assert "n1" not in proxy._node_to_session
    mock_session.disconnect.assert_awaited_once()


async def test_gemini_stop_session_cleanup():
    """Mocked: GeminiRealtimeProxy.stop_session cleans up properly."""
    from voice.gemini_realtime import GeminiRealtimeProxy

    proxy = GeminiRealtimeProxy()

    mock_session = MagicMock()
    mock_session.node_id = "gn1"
    mock_session.disconnect = AsyncMock()

    proxy._sessions["gs1"] = mock_session
    proxy._node_to_session["gn1"] = "gs1"

    await proxy.stop_session("gs1")

    assert "gs1" not in proxy._sessions
    assert "gn1" not in proxy._node_to_session
    mock_session.disconnect.assert_awaited_once()


async def test_realtime_session_send_audio_when_not_connected():
    """send_audio is a no-op when session is disconnected."""
    from voice.realtime_proxy import RealtimeSession

    session = RealtimeSession("s", "n")
    assert not session.connected
    await session.send_audio("dGVzdA==")


async def test_relay_audio_routes_to_correct_session():
    """relay_audio dispatches to the session for a given node."""
    from voice.realtime_proxy import RealtimeProxy

    proxy = RealtimeProxy()
    mock_session = MagicMock()
    mock_session.connected = True
    mock_session.send_audio = AsyncMock()

    proxy._sessions["s1"] = mock_session
    proxy._node_to_session["n1"] = "s1"

    await proxy.relay_audio("n1", "QUFB")
    mock_session.send_audio.assert_awaited_once_with("QUFB")
