"""
OpenAI Whisper STT provider (buffered, non-streaming).

Uses ``POST /v1/audio/transcriptions`` with ``whisper-1`` or
``gpt-4o-transcribe``.

**Latency tradeoff**: This provider buffers all audio until
``flush()`` or ``close()`` is called, then sends a single HTTP
request.  This adds end-of-utterance latency proportional to the
audio length, but produces higher-quality transcripts than
incremental streaming for short utterances.  For latency-sensitive
use cases, prefer the Deepgram streaming provider.
"""

from __future__ import annotations

import asyncio
import io
import logging
import struct
from typing import AsyncIterator

import httpx

from voice.stt_providers import (
    STTProvider,
    TranscriptFragment,
    register_stt_provider,
)

logger = logging.getLogger("feral.voice.stt.openai_whisper")

OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM16 bytes in a minimal WAV header."""
    data_len = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_len,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        sample_rate * channels * sample_width,
        channels * sample_width,
        sample_width * 8,
        b"data",
        data_len,
    )
    return header + pcm_bytes


@register_stt_provider("openai_whisper")
class OpenAIWhisperSTTProvider(STTProvider):
    """Buffered STT via OpenAI Whisper API."""

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "whisper-1",
        language: str = "en",
        sample_rate: int = 16000,
    ):
        if not api_key:
            raise ValueError("OpenAIWhisperSTTProvider requires an OPENAI_API_KEY")
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
                    OPENAI_TRANSCRIPTION_URL,
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
                "OpenAI Whisper transcription failed: %s %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            raise
        except Exception:
            logger.exception("OpenAI Whisper transcription error")
            raise

    async def close(self) -> None:
        """Flush remaining audio and signal stream end."""
        if self._closed:
            return
        self._closed = True
        await self.flush()
        await self._result_queue.put(None)
