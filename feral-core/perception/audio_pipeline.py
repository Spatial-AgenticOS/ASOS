"""
FERAL Audio Pipeline — STT + TTS + VAD
=========================================
Handles the full audio lifecycle:
  Client mic → opus chunks → VAD → STT (Whisper) → text
  Text response → TTS (OpenAI) → mp3 chunks → Client speaker

Supports:
  - OpenAI Whisper API for STT
  - Local STT via faster-whisper (offline, no API key required)
  - OpenAI TTS API for speech synthesis
  - Local TTS via Piper (offline, no API key required)
  - Simple energy-based VAD for utterance boundary detection

Environment variables:
  FERAL_STT_PROVIDER  — "openai" (default) | "local" | "whisper-local" | "faster-whisper"
  FERAL_STT_MODEL     — Cloud: "whisper-1" / Local: "tiny" | "base" | "small" | "medium" | "large"
  FERAL_TTS_PROVIDER  — "openai" (default) | "local" | "piper"
  FERAL_TTS_VOICE     — Cloud: "nova" / Local: "en_US-lessac-medium"
"""

from __future__ import annotations
import asyncio
import base64
import io
import logging
import os
import time
import wave
from typing import Optional

import httpx

logger = logging.getLogger("feral.audio")

STT_PROVIDER_OPENAI = "openai"
STT_PROVIDER_LOCAL = "local"

TTS_PROVIDER_OPENAI = "openai"
TTS_PROVIDER_LOCAL = "local"

_LOCAL_STT_PROVIDERS = frozenset({"local", "whisper-local", "faster-whisper"})
_LOCAL_TTS_PROVIDERS = frozenset({"local", "piper"})

_VALID_LOCAL_STT_MODELS = ("tiny", "base", "small", "medium", "large")


# ---------------------------------------------------------------------------
#  Local STT backend (faster-whisper)
# ---------------------------------------------------------------------------

class _LocalSTT:
    """Lazy-loaded local speech-to-text via faster-whisper."""

    def __init__(self):
        self._model = None
        self._model_size: str = os.getenv("FERAL_STT_MODEL", "base")
        if self._model_size not in _VALID_LOCAL_STT_MODELS:
            logger.warning(
                "Unknown local STT model '%s', falling back to 'base'",
                self._model_size,
            )
            self._model_size = "base"

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper is not installed. "
                "Install with: pip install 'feral-ai[stt]'"
            )
        logger.info("Loading local STT model: %s (first call — may download)", self._model_size)
        self._model = WhisperModel(self._model_size, compute_type="int8")
        logger.info("Local STT model loaded: %s", self._model_size)

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM16 mono audio bytes and return the text."""
        self._ensure_model()
        wav_bytes = _pcm16_to_wav(audio_bytes, sample_rate)
        segments, _info = self._model.transcribe(
            io.BytesIO(wav_bytes),
            language="en",
            beam_size=3,
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


# ---------------------------------------------------------------------------
#  Local TTS backend (Piper)
# ---------------------------------------------------------------------------

class _LocalTTS:
    """Lazy-loaded local text-to-speech via piper-tts."""

    def __init__(self):
        self._voice = None
        self._voice_name: str = os.getenv("FERAL_TTS_VOICE", "en_US-lessac-medium")

    def _ensure_voice(self):
        if self._voice is not None:
            return
        try:
            from piper import PiperVoice
        except ImportError:
            raise ImportError(
                "piper-tts is not installed. "
                "Install with: pip install 'feral-ai[tts]'"
            )
        logger.info("Loading local TTS voice: %s (first call — may download)", self._voice_name)
        self._voice = PiperVoice.load(self._voice_name)
        logger.info("Local TTS voice loaded: %s", self._voice_name)

    def synthesize(self, text: str) -> bytes:
        """Synthesize *text* to WAV audio bytes (PCM16, mono)."""
        self._ensure_voice()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._voice.synthesize(text, wf)
        return buf.getvalue()


# ---------------------------------------------------------------------------
#  Capability auto-detection
# ---------------------------------------------------------------------------

def detect_local_audio_capabilities() -> dict:
    """Probe which local audio backends are importable.

    Returns a dict suitable for ``feral doctor`` reporting::

        {
            "local_stt": True/False,
            "local_tts": True/False,
            "stt_models": ["tiny", "base", ...],
            "tts_voices": ["en_US-lessac-medium", ...],
        }
    """
    result: dict = {
        "local_stt": False,
        "local_tts": False,
        "stt_models": [],
        "tts_voices": [],
    }

    try:
        import faster_whisper  # noqa: F401
        result["local_stt"] = True
        result["stt_models"] = list(_VALID_LOCAL_STT_MODELS)
    except ImportError:
        pass

    try:
        import piper  # noqa: F401
        result["local_tts"] = True
        result["tts_voices"] = ["en_US-lessac-medium", "en_US-amy-low", "en_GB-alan-medium"]
    except ImportError:
        pass

    return result


# ---------------------------------------------------------------------------
#  Shared helpers
# ---------------------------------------------------------------------------

def _pcm16_to_wav(audio_bytes: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM16 mono audio in a WAV container."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(max(sample_rate, 8000))
        wav_file.writeframes(audio_bytes)
    return output.getvalue()


# ---------------------------------------------------------------------------
#  Main pipeline
# ---------------------------------------------------------------------------

class AudioPipeline:
    """
    Full-duplex audio pipeline for the FERAL brain.

    STT: Accumulates audio chunks, detects utterance boundaries (VAD),
         then transcribes via Whisper API or locally via faster-whisper.
    TTS: Converts text responses to audio chunks streamed back to client
         via OpenAI TTS or locally via Piper.
    """

    def __init__(self, wake_word_detector=None):
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        self._stt_provider = os.getenv("FERAL_STT_PROVIDER", STT_PROVIDER_OPENAI).lower()
        self._tts_provider = os.getenv("FERAL_TTS_PROVIDER", TTS_PROVIDER_OPENAI).lower()
        self._tts_voice = os.getenv("FERAL_TTS_VOICE", "nova")
        self._tts_model = os.getenv("FERAL_TTS_MODEL", "tts-1")
        self._stt_model = os.getenv("FERAL_STT_MODEL", "whisper-1")

        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
        )

        self._buffers: dict[str, AudioBuffer] = {}
        self._wake_word = wake_word_detector

        # Lazily-initialised local backends (created on first use)
        self._local_stt: Optional[_LocalSTT] = None
        self._local_tts: Optional[_LocalTTS] = None

        # Determine availability
        self._use_local_stt = self._stt_provider in _LOCAL_STT_PROVIDERS
        self._use_local_tts = self._tts_provider in _LOCAL_TTS_PROVIDERS

        has_cloud = bool(self._api_key)
        has_local_stt = self._use_local_stt
        has_local_tts = self._use_local_tts
        self.available = has_cloud or has_local_stt or has_local_tts

        parts = []
        if has_local_stt:
            parts.append(f"STT: local/faster-whisper ({self._stt_model})")
        elif has_cloud:
            parts.append(f"STT: openai/{self._stt_model}")
        if has_local_tts:
            parts.append(f"TTS: local/piper ({self._tts_voice})")
        elif has_cloud:
            parts.append(f"TTS: openai/{self._tts_voice}")

        if self.available:
            logger.info("Audio pipeline ready — %s", ", ".join(parts))
        else:
            logger.warning("Audio pipeline unavailable — no OPENAI_API_KEY and no local backend configured")

    # ── buffer management ──────────────────────────────────────────────

    def get_buffer(self, session_id: str) -> "AudioBuffer":
        if session_id not in self._buffers:
            self._buffers[session_id] = AudioBuffer(session_id)
        return self._buffers[session_id]

    # ── STT ────────────────────────────────────────────────────────────

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
        Accumulate an audio chunk.  When *is_final* is ``True`` or the VAD
        detects an utterance boundary, transcribe the accumulated audio.
        """
        buf = self.get_buffer(session_id)
        chunk_bytes = base64.b64decode(chunk_b64)
        buf.append(chunk_bytes, encoding, sample_rate)

        if is_final or buf.vad_triggered():
            audio_data = buf.flush()
            if not audio_data or len(audio_data) < 1000:
                return None
            return await self._transcribe(audio_data, encoding, sample_rate)

        return None

    async def _transcribe(
        self,
        audio_bytes: bytes,
        encoding: str = "opus",
        sample_rate: int = 16000,
    ) -> Optional[str]:
        """Transcribe accumulated audio via local or cloud backend."""
        if not self.available:
            return None

        # ── Local STT path ──
        if self._use_local_stt:
            return await self._transcribe_local(audio_bytes, encoding, sample_rate)

        # ── Cloud (OpenAI Whisper API) path ──
        return await self._transcribe_cloud(audio_bytes, encoding, sample_rate)

    async def _transcribe_local(
        self,
        audio_bytes: bytes,
        encoding: str,
        sample_rate: int,
    ) -> Optional[str]:
        """Run STT locally via faster-whisper with graceful fallback."""
        try:
            if self._local_stt is None:
                self._local_stt = _LocalSTT()

            pcm = audio_bytes
            if encoding.lower() != "pcm16":
                logger.debug("Local STT received %s encoding; treating as raw PCM", encoding)

            loop = asyncio.get_running_loop()
            transcript = await loop.run_in_executor(
                None, self._local_stt.transcribe, pcm, sample_rate
            )
            if transcript:
                logger.info("Local STT transcript: %s", transcript[:100])
            return transcript or None
        except ImportError:
            logger.warning(
                "faster-whisper not installed — falling back to cloud STT. "
                "Install with: pip install 'feral-ai[stt]'"
            )
            self._use_local_stt = False
            return await self._transcribe_cloud(audio_bytes, encoding, sample_rate)
        except Exception as e:
            logger.error("Local STT failed: %s — falling back to cloud", e)
            return await self._transcribe_cloud(audio_bytes, encoding, sample_rate)

    async def _transcribe_cloud(
        self,
        audio_bytes: bytes,
        encoding: str,
        sample_rate: int,
    ) -> Optional[str]:
        """Send accumulated audio to OpenAI Whisper API."""
        if not self._api_key:
            logger.error("Cloud STT unavailable — no OPENAI_API_KEY")
            return None

        encoding = (encoding or "opus").lower()
        ext_map = {"opus": "ogg", "wav": "wav", "mp3": "mp3", "webm": "webm", "ogg": "ogg", "pcm16": "wav"}
        ext = ext_map.get(encoding, "ogg")
        filename = f"audio.{ext}"
        payload_audio = audio_bytes
        if encoding == "pcm16":
            payload_audio = _pcm16_to_wav(audio_bytes, sample_rate=sample_rate)
        mime_type = "audio/wav" if ext == "wav" else f"audio/{ext}"

        try:
            files = {"file": (filename, io.BytesIO(payload_audio), mime_type)}
            data = {"model": self._stt_model, "response_format": "text"}

            resp = await self._client.post("/audio/transcriptions", files=files, data=data)
            resp.raise_for_status()
            transcript = resp.text.strip()
            logger.info("STT transcript: %s", transcript[:100])
            return transcript if transcript else None
        except Exception as e:
            logger.error("STT transcription failed: %s", e)
            return None

    # ── TTS ────────────────────────────────────────────────────────────

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

        if self._use_local_tts:
            return await self._synthesize_local(text)

        return await self._synthesize_cloud(text, voice)

    async def _synthesize_local(self, text: str) -> Optional[list[dict]]:
        """Run TTS locally via Piper with graceful fallback."""
        try:
            if self._local_tts is None:
                self._local_tts = _LocalTTS()

            loop = asyncio.get_running_loop()
            wav_bytes = await loop.run_in_executor(
                None, self._local_tts.synthesize, text[:4096]
            )

            chunk_size = 32 * 1024
            chunks = []
            for i in range(0, len(wav_bytes), chunk_size):
                segment = wav_bytes[i:i + chunk_size]
                is_final = (i + chunk_size) >= len(wav_bytes)
                chunks.append({
                    "chunk_index": len(chunks),
                    "encoding": "wav",
                    "data_b64": base64.b64encode(segment).decode("ascii"),
                    "is_final": is_final,
                })

            logger.info("Local TTS synthesized: %d bytes, %d chunks", len(wav_bytes), len(chunks))
            return chunks
        except ImportError:
            logger.warning(
                "piper-tts not installed — falling back to cloud TTS. "
                "Install with: pip install 'feral-ai[tts]'"
            )
            self._use_local_tts = False
            return await self._synthesize_cloud(text, None)
        except Exception as e:
            logger.error("Local TTS failed: %s — falling back to cloud", e)
            return await self._synthesize_cloud(text, None)

    async def _synthesize_cloud(
        self,
        text: str,
        voice: str = None,
    ) -> Optional[list[dict]]:
        """Synthesize via OpenAI TTS API."""
        if not self._api_key:
            logger.error("Cloud TTS unavailable — no OPENAI_API_KEY")
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

            logger.info("TTS synthesized: %d bytes, %d chunks", len(audio_bytes), len(chunks))
            return chunks
        except Exception as e:
            logger.error("TTS synthesis failed: %s", e)
            return None

    # ── Wake word gating ───────────────────────────────────────────────

    async def process_audio_with_wake_word(
        self,
        session_id: str,
        chunk_b64: str,
        chunk_index: int,
        is_final: bool,
        encoding: str = "opus",
        sample_rate: int = 16000,
    ) -> Optional[str]:
        """
        Wake-word-gated variant of process_audio_chunk.
        Audio only flows to STT after the wake word is detected.
        """
        if not self._wake_word or not self._wake_word.enabled:
            return await self.process_audio_chunk(session_id, chunk_b64, chunk_index, is_final, encoding, sample_rate)

        pcm_bytes = base64.b64decode(chunk_b64)
        should_process = await self._wake_word.process_frame(session_id, pcm_bytes)

        if should_process:
            return await self.process_audio_chunk(session_id, chunk_b64, chunk_index, is_final, encoding, sample_rate)

        return None

    # ── Lifecycle ──────────────────────────────────────────────────────

    def clear_session(self, session_id: str):
        self._buffers.pop(session_id, None)
        if self._wake_word:
            self._wake_word.cleanup_session(session_id)

    async def close(self):
        await self._client.aclose()


# ---------------------------------------------------------------------------
#  Audio buffer / VAD
# ---------------------------------------------------------------------------

class AudioBuffer:
    """Per-session audio chunk accumulator with simple energy-based VAD."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._chunks: list[bytes] = []
        self._encoding = "opus"
        self._sample_rate = 16000
        self._last_chunk_time = time.time()
        self._silence_threshold_sec = 1.5
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
