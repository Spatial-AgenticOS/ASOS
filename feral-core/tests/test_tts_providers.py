"""
Tests for TTS providers — chunked output (mocked), voice parameter passing,
error handling.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice.tts_providers import (
    TTSProvider,
    get_tts_provider,
    _PROVIDER_REGISTRY,
)


# ── Registry Tests ───────────────────────────────────────────────────

class TestTTSRegistry:
    def test_openai_registered(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider
        assert "openai" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["openai"] is OpenAITTSProvider

    def test_elevenlabs_registered(self):
        from voice.tts_providers.elevenlabs import ElevenLabsTTSProvider
        assert "elevenlabs" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["elevenlabs"] is ElevenLabsTTSProvider

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown TTS provider"):
            get_tts_provider("nonexistent")


# ── OpenAI TTS Tests ─────────────────────────────────────────────────

class TestOpenAITTSProvider:
    def test_requires_api_key(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAITTSProvider(api_key="")

    def test_init_stores_params(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider
        p = OpenAITTSProvider(
            api_key="sk-test", model="gpt-4o-mini-tts", voice="nova", speed=1.2
        )
        assert p._api_key == "sk-test"
        assert p._model == "gpt-4o-mini-tts"
        assert p._voice == "nova"
        assert p._speed == 1.2

    @pytest.mark.asyncio
    async def test_synthesize_streams_chunks(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider

        provider = OpenAITTSProvider(api_key="sk-test", model="tts-1", voice="alloy")

        chunk1 = b"\xff\xfb\x90\x00" * 100
        chunk2 = b"\xff\xfb\x90\x01" * 100

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_bytes(size):
            yield chunk1
            yield chunk2

        mock_response.aiter_bytes = fake_aiter_bytes

        mock_client = AsyncMock()
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voice.tts_providers.openai_tts.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in provider.synthesize("Hello there"):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0] == chunk1
        assert chunks[1] == chunk2

    @pytest.mark.asyncio
    async def test_synthesize_sends_auth_header(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider

        provider = OpenAITTSProvider(api_key="sk-auth-test", model="tts-1", voice="alloy")

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_bytes(size):
            yield b"audio"

        mock_response.aiter_bytes = fake_aiter_bytes

        mock_client = AsyncMock()
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voice.tts_providers.openai_tts.httpx.AsyncClient", return_value=mock_client):
            async for _ in provider.synthesize("test"):
                pass

        call_args = mock_client.stream.call_args
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer sk-auth-test"

    @pytest.mark.asyncio
    async def test_synthesize_sends_voice_param(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider

        provider = OpenAITTSProvider(api_key="sk-test", model="tts-1", voice="shimmer")

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_bytes(size):
            yield b"audio"

        mock_response.aiter_bytes = fake_aiter_bytes

        mock_client = AsyncMock()
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voice.tts_providers.openai_tts.httpx.AsyncClient", return_value=mock_client):
            async for _ in provider.synthesize("test"):
                pass

        call_args = mock_client.stream.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload["voice"] == "shimmer"
        assert payload["model"] == "tts-1"

    @pytest.mark.asyncio
    async def test_empty_text_yields_nothing(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider

        provider = OpenAITTSProvider(api_key="sk-test")
        chunks = []
        async for chunk in provider.synthesize(""):
            chunks.append(chunk)
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_whitespace_text_yields_nothing(self):
        from voice.tts_providers.openai_tts import OpenAITTSProvider

        provider = OpenAITTSProvider(api_key="sk-test")
        chunks = []
        async for chunk in provider.synthesize("   "):
            chunks.append(chunk)
        assert len(chunks) == 0


# ── ElevenLabs Tests ─────────────────────────────────────────────────

class TestElevenLabsTTSProvider:
    def test_requires_api_key(self):
        from voice.tts_providers.elevenlabs import ElevenLabsTTSProvider
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            ElevenLabsTTSProvider(api_key="")

    def test_init_stores_params(self):
        from voice.tts_providers.elevenlabs import ElevenLabsTTSProvider
        p = ElevenLabsTTSProvider(
            api_key="el-key",
            voice_id="custom-voice-id",
            model_id="eleven_turbo_v2_5",
            stability=0.7,
        )
        assert p._api_key == "el-key"
        assert p._voice_id == "custom-voice-id"
        assert p._model_id == "eleven_turbo_v2_5"
        assert p._stability == 0.7

    @pytest.mark.asyncio
    async def test_synthesize_streams_chunks(self):
        from voice.tts_providers.elevenlabs import ElevenLabsTTSProvider

        provider = ElevenLabsTTSProvider(api_key="el-test-key", voice_id="test-voice")

        chunk1 = b"\x00\x01" * 200
        chunk2 = b"\x02\x03" * 200

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_bytes(size):
            yield chunk1
            yield chunk2

        mock_response.aiter_bytes = fake_aiter_bytes

        mock_client = AsyncMock()
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voice.tts_providers.elevenlabs.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in provider.synthesize("Testing ElevenLabs"):
                chunks.append(chunk)

        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_synthesize_uses_xi_api_key_header(self):
        from voice.tts_providers.elevenlabs import ElevenLabsTTSProvider

        provider = ElevenLabsTTSProvider(api_key="el-auth-key", voice_id="v1")

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_bytes(size):
            yield b"audio"

        mock_response.aiter_bytes = fake_aiter_bytes

        mock_client = AsyncMock()
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voice.tts_providers.elevenlabs.httpx.AsyncClient", return_value=mock_client):
            async for _ in provider.synthesize("test"):
                pass

        call_args = mock_client.stream.call_args
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("xi-api-key") == "el-auth-key"

    @pytest.mark.asyncio
    async def test_synthesize_includes_voice_settings(self):
        from voice.tts_providers.elevenlabs import ElevenLabsTTSProvider

        provider = ElevenLabsTTSProvider(
            api_key="el-key", voice_id="v1", stability=0.8, similarity_boost=0.9
        )

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        async def fake_aiter_bytes(size):
            yield b"audio"

        mock_response.aiter_bytes = fake_aiter_bytes

        mock_client = AsyncMock()
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voice.tts_providers.elevenlabs.httpx.AsyncClient", return_value=mock_client):
            async for _ in provider.synthesize("test"):
                pass

        call_args = mock_client.stream.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload["voice_settings"]["stability"] == 0.8
        assert payload["voice_settings"]["similarity_boost"] == 0.9

    @pytest.mark.asyncio
    async def test_empty_text_yields_nothing(self):
        from voice.tts_providers.elevenlabs import ElevenLabsTTSProvider

        provider = ElevenLabsTTSProvider(api_key="el-key")
        chunks = []
        async for chunk in provider.synthesize(""):
            chunks.append(chunk)
        assert len(chunks) == 0
