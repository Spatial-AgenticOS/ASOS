"""Pinning tests for the v2026.5.31 voice resilience contract.

Audit-r11 baseline:
  * OpenAI Realtime closes the WS with code 1013 + reason
    ``insufficient_quota`` when the loaded key runs out of credit.
    Prior behaviour: brain swallowed the close in
    ``RealtimeSession._receive_loop``, flipped ``_connected=False``,
    and emitted ZERO frames. Every voice surface (iOS, WebUI desktop,
    WebUI phone) went silent with no banner.
  * Fixed contract:
    1. ``_receive_loop`` forwards the exception to the per-session
       ``on_error`` callback.
    2. ``RealtimeProxy._handle_error`` classifies the error
       (``insufficient_quota``/``1013`` -> ``openai_realtime_quota``)
       and calls ``VoiceRouter.handle_realtime_failure``.
    3. ``VoiceRouter`` emits ONE ``voice_status state=degraded``
       frame, marks the session degraded, and routes all subsequent
       assistant turns through ``synthesize_assistant_speech`` (mp3
       ``tts_chunk`` frames).
    4. When the fallback TTS also fails (no key, network down) the
       router emits ``voice_status state=unavailable`` so the client
       can render a banner instead of silent failure.

These tests run without network access and without ``OPENAI_API_KEY``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from voice.realtime_proxy import RealtimeProxy, RealtimeSession
from voice.router import VoiceRouter


# ── helpers ─────────────────────────────────────────────────────────


def _capture_sender():
    """Return ``(sender, list)`` where ``sender(session_id, msg)`` records
    each emitted ``FeralMessage`` (or raw dict for the node path) into
    ``list``. The whisper fallback exercises both paths so we capture
    both with the same recorder."""
    captured: list[tuple[str, object]] = []

    async def _send(session_id, msg):
        captured.append((session_id, msg))

    return _send, captured


@pytest.fixture()
def fallback_router(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    audio = MagicMock()
    audio.synthesize_speech = AsyncMock(return_value=[
        {"chunk_index": 0, "encoding": "mp3", "data_b64": "QQ==", "is_final": True},
    ])
    sender, captured = _capture_sender()
    router = VoiceRouter(
        realtime_proxy=MagicMock(available=True, _node_to_session={}),
        audio_pipeline=audio,
        send_to_session=sender,
    )
    return router, audio, captured


# ── voice_status emission ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_realtime_failure_emits_voice_status(fallback_router, monkeypatch):
    """quota error -> state=degraded + reason=openai_realtime_quota."""
    router, _audio, captured = fallback_router
    # Force the whisper fallback path so degraded (not unavailable) is emitted.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    await router.handle_realtime_failure(
        session_id="sess-1",
        reason="openai_realtime_quota",
        detail="received 1013 (insufficient_quota)",
    )

    assert router.is_session_degraded("sess-1")
    voice_status = [
        msg for (sid, msg) in captured
        if getattr(msg, "type", None) == "voice_status"
    ]
    assert len(voice_status) == 1, "expected exactly one voice_status frame"
    payload = voice_status[0].payload
    assert payload["state"] == "degraded"
    assert payload["reason"] == "openai_realtime_quota"
    assert payload["fallback_provider"] == "whisper"


@pytest.mark.asyncio
async def test_handle_realtime_failure_is_idempotent(fallback_router, monkeypatch):
    """Two quota errors on the same session emit one banner — clients render once."""
    router, _audio, captured = fallback_router
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    await router.handle_realtime_failure(session_id="s2", reason="openai_realtime_quota")
    await router.handle_realtime_failure(session_id="s2", reason="openai_realtime_quota")

    voice_status = [
        msg for (_, msg) in captured if getattr(msg, "type", None) == "voice_status"
    ]
    assert len(voice_status) == 1


@pytest.mark.asyncio
async def test_handle_realtime_failure_emits_unavailable_when_no_fallback(
    fallback_router, monkeypatch,
):
    """No OPENAI_API_KEY + ``audio.fallback_tts_providers=[]`` -> unavailable."""
    router, _audio, captured = fallback_router
    # The bundled default now includes ``whisper`` so explicitly null
    # out the chain to exercise the "nothing left" branch. Real users
    # land here when they have no OpenAI key AND no alt-TTS configured.
    monkeypatch.setattr(
        "config.loader.load_settings",
        lambda: {"audio": {"fallback_tts_providers": []}},
        raising=False,
    )

    await router.handle_realtime_failure(
        session_id="s3",
        reason="openai_realtime_quota",
    )

    payload = next(
        msg.payload for (_, msg) in captured
        if getattr(msg, "type", None) == "voice_status"
    )
    assert payload["state"] == "unavailable"
    assert payload["fallback_provider"] == ""


# ── whisper TTS fallback ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_assistant_speech_emits_tts_chunk(fallback_router, monkeypatch):
    """After degrade, assistant turns synthesise mp3 chunks on the session."""
    router, audio, captured = fallback_router
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    await router.handle_realtime_failure(session_id="s4", reason="openai_realtime_quota")

    delivered = await router.synthesize_assistant_speech("s4", "Hello there.")
    assert delivered is True

    audio.synthesize_speech.assert_awaited_once()
    tts_chunks = [
        msg for (_, msg) in captured if getattr(msg, "type", None) == "tts_chunk"
    ]
    assert len(tts_chunks) == 1
    payload = tts_chunks[0].payload
    assert payload["encoding"] == "mp3"
    assert payload["data_b64"]
    assert payload["is_final"] is True


@pytest.mark.asyncio
async def test_fallback_failure_emits_unavailable(monkeypatch):
    """Whisper synth returning None bumps the session to unavailable."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    audio = MagicMock()
    audio.synthesize_speech = AsyncMock(return_value=None)
    sender, captured = _capture_sender()
    router = VoiceRouter(audio_pipeline=audio, send_to_session=sender)

    await router.handle_realtime_failure(session_id="s5", reason="openai_realtime_quota")
    delivered = await router.synthesize_assistant_speech("s5", "Hi")
    assert delivered is False

    voice_status = [
        msg.payload for (_, msg) in captured
        if getattr(msg, "type", None) == "voice_status"
    ]
    # First one is `degraded` from handle_realtime_failure, last is `unavailable`.
    assert voice_status[-1]["state"] == "unavailable"
    assert voice_status[-1]["reason"] == "fallback_tts_failed"


# ── RealtimeProxy classifier ────────────────────────────────────────


@pytest.mark.asyncio
async def test_realtime_proxy_classifies_quota_to_router(monkeypatch):
    """Proxy receives ``insufficient_quota`` text and routes to fallback."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    proxy = RealtimeProxy()
    router = MagicMock()
    router.handle_realtime_failure = AsyncMock()
    proxy.attach_fallback_router(router)

    await proxy._handle_error(
        "sess-quota",
        "received 1013 (insufficient_quota) ('You exceeded your current quota')",
    )

    router.handle_realtime_failure.assert_awaited_once()
    call = router.handle_realtime_failure.call_args
    assert call.kwargs["session_id"] == "sess-quota"
    assert call.kwargs["reason"] == "openai_realtime_quota"


@pytest.mark.asyncio
async def test_realtime_proxy_classifies_auth_error():
    proxy = RealtimeProxy()
    router = MagicMock()
    router.handle_realtime_failure = AsyncMock()
    proxy.attach_fallback_router(router)

    await proxy._handle_error("sess-auth", "401 Unauthorized: invalid_api_key")

    assert router.handle_realtime_failure.call_args.kwargs["reason"] == "openai_realtime_auth"


@pytest.mark.asyncio
async def test_realtime_proxy_handle_error_no_router_is_safe():
    """When no fallback router is attached, _handle_error must not raise."""
    proxy = RealtimeProxy()
    # Should not raise even without attach_fallback_router being called.
    await proxy._handle_error("sess-x", "some random failure")


# ── receive loop wiring ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_receive_loop_pipes_exception_to_on_error():
    """The receive loop must forward upstream WS errors to ``on_error``
    so the classifier can run. Pinned by the regression flow above."""

    class _DummyWS:
        def __init__(self):
            self._yielded = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            raise RuntimeError("received 1013 (insufficient_quota) — closed")

        async def close(self):
            pass

    captured: list[str] = []

    async def on_error(sid, err):
        captured.append(err)

    rs = RealtimeSession(
        session_id="s",
        node_id="n",
        api_key="sk-test",
        on_error=on_error,
    )
    rs._ws = _DummyWS()
    rs._connected = True

    await rs._receive_loop()
    assert captured, "_receive_loop should have invoked on_error"
    assert "insufficient_quota" in captured[0]
