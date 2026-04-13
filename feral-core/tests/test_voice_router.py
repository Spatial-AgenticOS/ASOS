"""Tests for voice.router — VoiceRouter triple-path audio routing."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice.router import VoiceRouter


@pytest.fixture()
def mock_realtime():
    rt = MagicMock()
    rt.available = True
    rt.get_session = MagicMock(return_value=None)
    rt.start_session = AsyncMock()
    rt._node_to_session = {}
    rt.shutdown = AsyncMock()
    return rt


@pytest.fixture()
def mock_gemini():
    gm = MagicMock()
    gm.available = True
    gm.get_session = MagicMock(return_value=None)
    gm.start_session = AsyncMock()
    gm._node_to_session = {}
    gm.shutdown = AsyncMock()
    return gm


@pytest.fixture()
def router(mock_realtime, mock_gemini):
    r = VoiceRouter(
        realtime_proxy=mock_realtime,
        audio_pipeline=MagicMock(),
        orchestrator=MagicMock(),
    )
    r.set_gemini_proxy(mock_gemini)
    return r


# ── Provider selection ───────────────────────────────────────────

def test_default_provider_openai_when_supports_realtime(router):
    router.register_voice_config("n1", {"supports_realtime": True})
    assert router._resolve_provider("n1") == "openai"


def test_gemini_via_env(router, monkeypatch):
    monkeypatch.setenv("FERAL_VOICE_PROVIDER", "gemini")
    router.register_voice_config("n1", {"supports_realtime": True})
    assert router._resolve_provider("n1") == "gemini"


def test_node_specific_provider_config(router):
    router.register_voice_config("n1", {"voice_provider": "gemini"})
    assert router._resolve_provider("n1") == "gemini"


def test_whisper_fallback_no_proxy():
    r = VoiceRouter()
    assert r._resolve_provider("any") == "whisper"


# ── Session voice mode ───────────────────────────────────────────

def test_session_voice_mode_switching(router):
    router.set_session_voice_mode("s1", "realtime")
    assert router._resolve_session_provider("s1") == "openai"

    router.set_session_voice_mode("s1", "whisper")
    assert router._resolve_session_provider("s1") == "whisper"


def test_session_uses_realtime(router):
    router.set_session_voice_mode("s1", "realtime")
    assert router.session_uses_realtime("s1") is True
    assert router.session_uses_realtime("unknown") is False


# ── Wake word gating ─────────────────────────────────────────────

async def test_wake_word_blocks_audio():
    wake = MagicMock()
    wake.enabled = True
    wake.process_frame = AsyncMock(return_value=False)

    r = VoiceRouter(wake_word_detector=wake)
    r.register_voice_config("n1", {"supports_realtime": True})

    await r.handle_audio_from_node("n1", "s1", base64.b64encode(b"\x00" * 100).decode())
    wake.process_frame.assert_awaited_once()


# ── handle_audio dispatching ─────────────────────────────────────

async def test_handle_audio_dispatches_openai(router, mock_realtime):
    sess = MagicMock(connected=True, send_audio=AsyncMock())
    mock_realtime.get_session.return_value = sess
    router.register_voice_config("n1", {"supports_realtime": True})

    await router.handle_audio_from_node("n1", "s1", "AAAA==")
    sess.send_audio.assert_awaited_once_with("AAAA==")


async def test_handle_audio_dispatches_whisper(mock_realtime):
    pipeline = MagicMock()
    pipeline.process_audio_chunk = AsyncMock(return_value=None)

    r = VoiceRouter(realtime_proxy=mock_realtime, audio_pipeline=pipeline)
    await r.handle_audio_from_node("n1", "s1", "AAAA==")
    pipeline.process_audio_chunk.assert_awaited_once()


# ── Graceful no-proxy ────────────────────────────────────────────

async def test_graceful_no_audio_pipeline():
    r = VoiceRouter()
    await r.handle_audio_from_node("n1", "s1", "AAAA==")


async def test_shutdown_delegates(router, mock_realtime, mock_gemini):
    await router.shutdown()
    mock_realtime.shutdown.assert_awaited_once()
    mock_gemini.shutdown.assert_awaited_once()
