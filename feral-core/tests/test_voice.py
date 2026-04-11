"""
Unit tests for Gemini realtime voice proxy (`voice.gemini_realtime`).

Exercises session bookkeeping, lifecycle hooks, and safe audio relay when
no session exists.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice.gemini_realtime import GeminiRealtimeProxy, GeminiRealtimeSession


class TestGeminiRealtimeProxy:
    """Tests for `GeminiRealtimeProxy`."""

    def test_init_initializes_session_dict(self) -> None:
        """Constructor allocates empty session and node maps."""
        proxy = GeminiRealtimeProxy()
        assert proxy._sessions == {}
        assert proxy._node_to_session == {}

    def test_has_session_unknown_false_after_manual_add_true(self) -> None:
        """`has_session` tracks `_sessions` membership."""
        proxy = GeminiRealtimeProxy()
        assert proxy.has_session("missing") is False
        proxy._sessions["sid-1"] = MagicMock()
        assert proxy.has_session("sid-1") is True

    @pytest.mark.asyncio
    async def test_start_session_creates_entry_mock_websocket(self) -> None:
        """`start_session` registers the session after connect (websocket mocked)."""
        with patch("voice.gemini_realtime.os.getenv", return_value="fake-key"):
            proxy = GeminiRealtimeProxy()
        with patch.object(GeminiRealtimeSession, "connect", new_callable=AsyncMock):
            sess = await proxy.start_session("sess-a", "node-a")
        assert isinstance(sess, GeminiRealtimeSession)
        assert proxy.has_session("sess-a")
        assert proxy._node_to_session.get("node-a") == "sess-a"

    @pytest.mark.asyncio
    async def test_relay_audio_no_session_no_error(self) -> None:
        """Relaying audio without a matching session is a silent no-op."""
        proxy = GeminiRealtimeProxy()
        await proxy.relay_audio("nonexistent-session", "AAA=")
        # No exception; internal lookup yields nothing to forward.

    @pytest.mark.asyncio
    async def test_relay_audio_forwards_when_session_connected(self) -> None:
        """Audio is passed to `GeminiRealtimeSession.send_audio` when connected."""
        proxy = GeminiRealtimeProxy()
        gs = MagicMock(spec=GeminiRealtimeSession)
        gs.connected = True
        gs.send_audio = AsyncMock()
        proxy._sessions["live-sid"] = gs
        await proxy.relay_audio("live-sid", "PCM64=")
        gs.send_audio.assert_awaited_once_with("PCM64=")
