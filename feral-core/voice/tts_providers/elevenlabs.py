"""
ElevenLabs TTS provider for the chained voice pipeline.

Uses the ElevenLabs streaming TTS API (HTTP chunked transfer) to
synthesize speech.  Audio chunks are yielded as raw bytes for
base64-encoding and delivery to the phone client.

The streaming endpoint is::

    POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream

with chunked-transfer-encoding response.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from voice.tts_providers import TTSProvider, register_tts_provider

logger = logging.getLogger("feral.voice.tts.elevenlabs")

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

CHUNK_SIZE = 4096


@register_tts_provider("elevenlabs")
class ElevenLabsTTSProvider(TTSProvider):
    """Streaming TTS via ElevenLabs."""

    def __init__(
        self,
        *,
        api_key: str = "",
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # "Rachel" default
        model_id: str = "eleven_turbo_v2_5",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        output_format: str = "mp3_44100_128",
    ):
        if not api_key:
            raise ValueError("ElevenLabsTTSProvider requires an ELEVENLABS_API_KEY")
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._stability = stability
        self._similarity_boost = similarity_boost
        self._output_format = output_format

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Stream audio chunks from ElevenLabs TTS."""
        if not text.strip():
            return

        url = ELEVENLABS_TTS_URL.format(voice_id=self._voice_id)

        payload = {
            "text": text,
            "model_id": self._model_id,
            "voice_settings": {
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
            },
        }

        params = {"output_format": self._output_format}

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                url,
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                params=params,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    if chunk:
                        yield chunk
