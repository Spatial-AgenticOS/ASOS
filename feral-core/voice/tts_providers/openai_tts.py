"""
OpenAI TTS provider for the chained voice pipeline.

Uses ``POST /v1/audio/speech`` with ``gpt-4o-mini-tts`` (primary)
or ``tts-1`` (fallback).  Streams MP3 audio chunks back for
base64-encoding and delivery to the phone client.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from voice.tts_providers import TTSProvider, register_tts_provider

logger = logging.getLogger("feral.voice.tts.openai")

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

CHUNK_SIZE = 4096


@register_tts_provider("openai")
class OpenAITTSProvider(TTSProvider):
    """Streaming TTS via OpenAI's audio/speech endpoint."""

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        speed: float = 1.0,
        response_format: str = "mp3",
    ):
        if not api_key:
            raise ValueError("OpenAITTSProvider requires an OPENAI_API_KEY")
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._speed = speed
        self._response_format = response_format

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Stream audio chunks from OpenAI TTS."""
        if not text.strip():
            return

        payload = {
            "model": self._model,
            "input": text,
            "voice": self._voice,
            "speed": self._speed,
            "response_format": self._response_format,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                OPENAI_TTS_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    if chunk:
                        yield chunk
