"""
THEORA Audio Pipeline — STT + TTS + VAD
=========================================
Handles the full audio lifecycle:
  Client mic → opus chunks → VAD → STT (Whisper) → text
  Text response → TTS (OpenAI) → mp3 chunks → Client speaker

Supports:
  - OpenAI Whisper API for STT
  - OpenAI TTS API for speech synthesis
  - Simple energy-based VAD for utterance boundary detection
"""

from __future__ import annotations
import asyncio
import base64
import io
import logging
import os
import time
from typing import Optional, Callable, Awaitable
from uuid import uuid4

import httpx

logger = logging.getLogger("theora.audio")

# Supported STT providers
STT_PROVIDER_OPENAI = "openai"
STT_PROVIDER_LOCAL = "local"

# Supported TTS providers
TTS_PROVIDER_OPENAI = "openai"


class AudioPipeline:
    """
    Full-duplex audio pipeline for the THEORA brain.

    STT: Accumulates audio chunks, detects utterance boundaries (VAD),
         then transcribes via Whisper API.
    TTS: Converts text responses to mp3 audio chunks streamed back to client.
    """

    def __init__(self):
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        self._stt_provider = os.getenv("THEORA_STT_PROVIDER", STT_PROVIDER_OPENAI)
        self._tts_provider = os.getenv("THEORA_TTS_PROVIDER", TTS_PROVIDER_OPENAI)
        self._tts_voice = os.getenv("THEORA_TTS_VOICE", "nova")
        self._tts_model = os.getenv("THEORA_TTS_MODEL", "tts-1")
        self._stt_model = os.getenv("THEORA_STT_MODEL", "whisper-1")

        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={
                "Authorization": f"Bearer {self._api_key}",
            },
            timeout=30.0,
        )

        # Per-session audio buffers for chunk accumulation
        self._buffers: dict[str, AudioBuffer] = {}

        self.available = bool(self._api_key)
        if self.available:
            logger.info(f"Audio pipeline ready — STT: {self._stt_provider}/{self._stt_model}, TTS: {self._tts_provider}/{self._tts_voice}")
        else:
            logger.warning("Audio pipeline unavailable — no OPENAI_API_KEY set")

    def get_buffer(self, session_id: str) -> "AudioBuffer":
        if session_id not in self._buffers:
            self._buffers[session_id] = AudioBuffer(session_id)
        return self._buffers[session_id]

    async def process_audio_chunk(
        self,
        session_id: str,
        chunk_b64: str,
        chunk_index: int,
        is_final: bool,
        encoding: str = "opus",
        sample_rate: int = 16000,
    ) -> Optional[str]:
        """
        Accumulate an audio chunk.  When is_final=True or the VAD detects
        an utterance boundary, transcribe the accumulated audio.

        Returns the transcript text or None if still accumulating.
        """
        buf = self.get_buffer(session_id)
        chunk_bytes = base64.b64decode(chunk_b64)
        buf.append(chunk_bytes, encoding, sample_rate)

        if is_final or buf.vad_triggered():
            audio_data = buf.flush()
            if not audio_data or len(audio_data) < 1000:
                return None
            transcript = await self._transcribe(audio_data, encoding)
            return transcript

        return None

    async def _transcribe(self, audio_bytes: bytes, encoding: str = "opus") -> Optional[str]:
        """Send accumulated audio to Whisper API for transcription."""
        if not self.available:
            return None

        ext_map = {"opus": "ogg", "wav": "wav", "mp3": "mp3", "webm": "webm", "ogg": "ogg"}
        ext = ext_map.get(encoding, "ogg")
        filename = f"audio.{ext}"

        try:
            files = {"file": (filename, io.BytesIO(audio_bytes), f"audio/{ext}")}
            data = {"model": self._stt_model, "response_format": "text"}

            resp = await self._client.post(
                "/audio/transcriptions",
                files=files,
                data=data,
            )
            resp.raise_for_status()
            transcript = resp.text.strip()
            logger.info(f"STT transcript: {transcript[:100]}")
            return transcript if transcript else None

        except Exception as e:
            logger.error(f"STT transcription failed: {e}")
            return None

    async def synthesize_speech(
        self,
        text: str,
        voice: str = None,
    ) -> Optional[list[dict]]:
        """
        Convert text to speech audio chunks.
        Returns a list of chunk dicts: [{chunk_index, encoding, data_b64, is_final}]
        """
        if not self.available or not text.strip():
            return None

        voice = voice or self._tts_voice

        try:
            resp = await self._client.post(
                "/audio/speech",
                json={
                    "model": self._tts_model,
                    "input": text[:4096],
                    "voice": voice,
                    "response_format": "mp3",
                },
            )
            resp.raise_for_status()
            audio_bytes = resp.content

            # Split into chunks for streaming (32KB each)
            chunk_size = 32 * 1024
            chunks = []
            for i in range(0, len(audio_bytes), chunk_size):
                segment = audio_bytes[i:i + chunk_size]
                is_final = (i + chunk_size) >= len(audio_bytes)
                chunks.append({
                    "chunk_index": len(chunks),
                    "encoding": "mp3",
                    "data_b64": base64.b64encode(segment).decode("ascii"),
                    "is_final": is_final,
                })

            logger.info(f"TTS synthesized: {len(audio_bytes)} bytes, {len(chunks)} chunks")
            return chunks

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            return None

    def clear_session(self, session_id: str):
        self._buffers.pop(session_id, None)

    async def close(self):
        await self._client.aclose()


class AudioBuffer:
    """Per-session audio chunk accumulator with simple energy-based VAD."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._chunks: list[bytes] = []
        self._encoding = "opus"
        self._sample_rate = 16000
        self._last_chunk_time = time.time()
        self._silence_threshold_sec = 1.5  # seconds of silence → utterance boundary
        self._total_bytes = 0

    def append(self, chunk: bytes, encoding: str, sample_rate: int):
        self._chunks.append(chunk)
        self._encoding = encoding
        self._sample_rate = sample_rate
        self._last_chunk_time = time.time()
        self._total_bytes += len(chunk)

    def vad_triggered(self) -> bool:
        """Simple VAD: silence gap detection + minimum buffer size."""
        if not self._chunks:
            return False
        elapsed = time.time() - self._last_chunk_time
        return elapsed > self._silence_threshold_sec and self._total_bytes > 2000

    def flush(self) -> bytes:
        """Return all accumulated audio and reset."""
        if not self._chunks:
            return b""
        audio = b"".join(self._chunks)
        self._chunks.clear()
        self._total_bytes = 0
        return audio
