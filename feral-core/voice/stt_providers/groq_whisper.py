"""
Groq Whisper STT provider (buffered, non-streaming).

Uses Groq's ``POST /openai/v1/audio/transcriptions`` endpoint with
``whisper-large-v3``.

**Latency tradeoff**: Same buffered pattern as the OpenAI Whisper
provider — audio is accumulated until ``flush()`` or ``close()``
is called.  Groq's inference is typically faster than OpenAI's
Whisper endpoint, making this a good middle ground between
streaming Deepgram and buffered OpenAI Whisper.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import AsyncIterator

import httpx

from voice.stt_providers import (
    STTProvider,
    TranscriptFragment,
    register_stt_provider,
)
from voice.stt_providers.openai_whisper import _pcm16_to_wav

logger = logging.getLogger("feral.voice.stt.groq_whisper")

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


@register_stt_provider("groq_whisper")
class GroqWhisperSTTProvider(STTProvider):
    """Buffered STT via Groq's Whisper API."""

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "whisper-large-v3",
        language: str = "en",
        sample_rate: int = 16000,
    ):
        if not api_key:
            raise ValueError("GroqWhisperSTTProvider requires a GROQ_API_KEY")
        self._api_key = api_key
        self._model = model
        self._language = language
        self._sample_rate = sample_rate
        self._buffer = bytearray()
        self._result_queue: asyncio.Queue[TranscriptFragment | None] = asyncio.Queue()
        self._closed = False

    async def open_stream(self) -> AsyncIterator[TranscriptFragment]:
        """Yield transcript fragments (one final fragment after flush/close)."""
        try:
            while True:
                fragment = await self._result_queue.get()
                if fragment is None:
                    break
                yield fragment
        finally:
            self._closed = True

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Accumulate audio into the internal buffer."""
        if not self._closed:
            self._buffer.extend(audio_bytes)

    async def flush(self) -> None:
        """Transcribe accumulated audio and emit the result."""
        if not self._buffer:
            return

        pcm_data = bytes(self._buffer)
        self._buffer.clear()

        wav_data = _pcm16_to_wav(pcm_data, sample_rate=self._sample_rate)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    GROQ_TRANSCRIPTION_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": ("audio.wav", io.BytesIO(wav_data), "audio/wav")},
                    data={
                        "model": self._model,
                        "language": self._language,
                        "response_format": "json",
                    },
                )
                response.raise_for_status()
                result = response.json()
                text = result.get("text", "").strip()

                if text:
                    await self._result_queue.put(
                        TranscriptFragment(
                            text=text,
                            is_partial=False,
                            is_final=True,
                            speech_final=True,
                        )
                    )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Groq Whisper transcription failed: %s %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            raise
        except Exception:
            logger.exception("Groq Whisper transcription error")
            raise

    async def close(self) -> None:
        """Flush remaining audio and signal stream end."""
        if self._closed:
            return
        self._closed = True
        await self.flush()
        await self._result_queue.put(None)
