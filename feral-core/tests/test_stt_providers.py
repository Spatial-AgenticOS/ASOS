"""
Tests for STT providers — WebSocket/HTTP contracts (mocked), auth header
presence, error surfaces.
"""

from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice.stt_providers import (
    STTProvider,
    TranscriptFragment,
    get_stt_provider,
    _PROVIDER_REGISTRY,
)


# ── Registry Tests ───────────────────────────────────────────────────

class TestSTTRegistry:
    def test_deepgram_registered(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider
        assert "deepgram" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["deepgram"] is DeepgramSTTProvider

    def test_openai_whisper_registered(self):
        from voice.stt_providers.openai_whisper import OpenAIWhisperSTTProvider
        assert "openai_whisper" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["openai_whisper"] is OpenAIWhisperSTTProvider

    def test_groq_whisper_registered(self):
        from voice.stt_providers.groq_whisper import GroqWhisperSTTProvider
        assert "groq_whisper" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["groq_whisper"] is GroqWhisperSTTProvider

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown STT provider"):
            get_stt_provider("nonexistent")


# ── Deepgram Tests ───────────────────────────────────────────────────

class TestDeepgramProvider:
    def test_requires_api_key(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
            DeepgramSTTProvider(api_key="")

    def test_init_stores_config(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider
        p = DeepgramSTTProvider(api_key="dg-key-123", model="nova-3", language="en")
        assert p._api_key == "dg-key-123"
        assert p._model == "nova-3"
        assert p._language == "en"

    @pytest.mark.asyncio
    async def test_ws_connect_uses_auth_header(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider

        provider = DeepgramSTTProvider(api_key="dg-test-key", model="nova-3")

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = AsyncMock(return_value=iter([]))
        mock_ws.close = AsyncMock()

        # The provider tries `websockets.asyncio.client.connect` first
        # (websockets 14.x+ path) and falls back to `websockets.connect`
        # (legacy 13.x). Patch BOTH so the test passes regardless of
        # the installed websockets line. Cross-version contract pinned
        # by tests/test_voice_realtime_headers.py.
        captured_calls: list = []

        async def _capture(url, **kwargs):
            captured_calls.append((url, kwargs))
            return mock_ws

        patches = []
        try:
            patches.append(patch("websockets.asyncio.client.connect", side_effect=_capture))
        except (AttributeError, ImportError):
            pass
        patches.append(patch("websockets.connect", side_effect=_capture))
        for p in patches:
            p.start()
        try:
            stream = provider.open_stream()
            task = asyncio.create_task(stream.__anext__())
            await asyncio.sleep(0.05)

            assert captured_calls, "deepgram provider never invoked websockets connect"
            url, kwargs = captured_calls[-1]
            headers = kwargs.get("additional_headers") or kwargs.get("extra_headers") or {}
            assert "Token dg-test-key" in str(headers), (
                f"Authorization header missing or malformed. Got headers={headers}"
            )
        finally:
            for p in patches:
                p.stop()

            provider._closed = True
            await provider._transcript_queue.put(None)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass

    def test_handle_results_parses_transcript(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider

        provider = DeepgramSTTProvider(api_key="dg-key")

        event = {
            "type": "Results",
            "is_final": True,
            "speech_final": True,
            "channel": {
                "alternatives": [
                    {"transcript": "hello world", "confidence": 0.98}
                ]
            },
        }

        provider._handle_results(event)
        frag = provider._transcript_queue.get_nowait()
        assert frag.text == "hello world"
        assert frag.is_final is True
        assert frag.speech_final is True
        assert frag.confidence == 0.98

    def test_handle_results_ignores_empty_transcript(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider

        provider = DeepgramSTTProvider(api_key="dg-key")
        event = {
            "type": "Results",
            "is_final": False,
            "channel": {"alternatives": [{"transcript": "", "confidence": 0.0}]},
        }
        provider._handle_results(event)
        assert provider._transcript_queue.empty()

    def test_handle_results_no_alternatives(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider

        provider = DeepgramSTTProvider(api_key="dg-key")
        event = {"type": "Results", "is_final": True, "channel": {"alternatives": []}}
        provider._handle_results(event)
        assert provider._transcript_queue.empty()

    @pytest.mark.asyncio
    async def test_send_audio_forwards_bytes(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider

        provider = DeepgramSTTProvider(api_key="dg-key")
        mock_ws = AsyncMock()
        provider._ws = mock_ws

        await provider.send_audio(b"\x00\x01\x02")
        mock_ws.send.assert_awaited_once_with(b"\x00\x01\x02")

    @pytest.mark.asyncio
    async def test_close_sends_close_stream(self):
        from voice.stt_providers.deepgram import DeepgramSTTProvider

        provider = DeepgramSTTProvider(api_key="dg-key")
        mock_ws = AsyncMock()
        provider._ws = mock_ws

        await provider.close()

        close_call = mock_ws.send.call_args
        assert json.loads(close_call[0][0]) == {"type": "CloseStream"}
        assert provider._closed


# ── OpenAI Whisper Tests ─────────────────────────────────────────────

class TestOpenAIWhisperProvider:
    def test_requires_api_key(self):
        from voice.stt_providers.openai_whisper import OpenAIWhisperSTTProvider
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIWhisperSTTProvider(api_key="")

    @pytest.mark.asyncio
    async def test_buffered_flush_sends_http_request(self):
        from voice.stt_providers.openai_whisper import OpenAIWhisperSTTProvider

        provider = OpenAIWhisperSTTProvider(api_key="sk-test-123", model="whisper-1")

        await provider.send_audio(b"\x00" * 320)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "test transcription"}
        mock_response.raise_for_status = MagicMock()

        with patch("voice.stt_providers.openai_whisper.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.post = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            await provider.flush()

            call_args = client_instance.post.call_args
            assert "Bearer sk-test-123" in str(call_args)

        frag = provider._result_queue.get_nowait()
        assert frag.text == "test transcription"
        assert frag.is_final is True

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(self):
        from voice.stt_providers.openai_whisper import OpenAIWhisperSTTProvider

        provider = OpenAIWhisperSTTProvider(api_key="sk-test")
        await provider.flush()
        assert provider._result_queue.empty()

    def test_pcm16_to_wav_header(self):
        from voice.stt_providers.openai_whisper import _pcm16_to_wav

        pcm = b"\x00" * 100
        wav = _pcm16_to_wav(pcm, sample_rate=16000)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert len(wav) == 44 + 100


# ── Groq Whisper Tests ───────────────────────────────────────────────

class TestGroqWhisperProvider:
    def test_requires_api_key(self):
        from voice.stt_providers.groq_whisper import GroqWhisperSTTProvider
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            GroqWhisperSTTProvider(api_key="")

    def test_init_stores_config(self):
        from voice.stt_providers.groq_whisper import GroqWhisperSTTProvider
        p = GroqWhisperSTTProvider(api_key="gsk-test", model="whisper-large-v3")
        assert p._api_key == "gsk-test"
        assert p._model == "whisper-large-v3"

    @pytest.mark.asyncio
    async def test_buffered_flush_uses_groq_endpoint(self):
        from voice.stt_providers.groq_whisper import GroqWhisperSTTProvider, GROQ_TRANSCRIPTION_URL

        provider = GroqWhisperSTTProvider(api_key="gsk-test-key", model="whisper-large-v3")

        await provider.send_audio(b"\x00" * 320)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "groq transcription"}
        mock_response.raise_for_status = MagicMock()

        with patch("voice.stt_providers.groq_whisper.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.post = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            await provider.flush()

            call_args = client_instance.post.call_args
            assert GROQ_TRANSCRIPTION_URL in str(call_args)
            assert "Bearer gsk-test-key" in str(call_args)

        frag = provider._result_queue.get_nowait()
        assert frag.text == "groq transcription"
        assert frag.is_final is True

    @pytest.mark.asyncio
    async def test_close_flushes_then_signals_end(self):
        from voice.stt_providers.groq_whisper import GroqWhisperSTTProvider

        provider = GroqWhisperSTTProvider(api_key="gsk-test")
        await provider.send_audio(b"\x00" * 100)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "closing text"}
        mock_response.raise_for_status = MagicMock()

        with patch("voice.stt_providers.groq_whisper.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.post = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            await provider.close()

        assert provider._closed
        frag = provider._result_queue.get_nowait()
        assert frag.text == "closing text"

        sentinel = provider._result_queue.get_nowait()
        assert sentinel is None
