"""
FERAL Wake Word Detector — "Hey FERAL"
==========================================
Local wake word detection gating audio flow to the Brain.
Uses openwakeword for ML-based detection with fallback to
energy-based keyword spotting.

States: LISTENING → ACTIVATED → TIMEOUT → LISTENING
"""

from __future__ import annotations
import asyncio
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("feral.wake_word")


class WakeState(str, Enum):
    LISTENING = "listening"
    ACTIVATED = "activated"
    TIMEOUT = "timeout"


@dataclass
class WakeWordEvent:
    timestamp: float
    confidence: float
    phrase: str
    pre_roll_b64: str = ""


@dataclass
class WakeWordConfig:
    enabled: bool = True
    phrase: str = "hey feral"
    sensitivity: float = 0.5
    timeout_seconds: float = 10.0
    pre_roll_ms: int = 500


class WakeWordDetector:
    """
    Streams raw PCM16 frames.  While in LISTENING state, only wake word
    detection runs (minimal CPU).  On detection, transitions to ACTIVATED
    and all subsequent audio flows through to the Brain until TIMEOUT.
    """

    def __init__(self, config: WakeWordConfig = None):
        self._config = config or WakeWordConfig(
            enabled=os.getenv("FERAL_WAKE_WORD", "false").lower() in ("true", "1", "yes"),
            phrase=os.getenv("FERAL_WAKE_PHRASE", "hey feral"),
            sensitivity=float(os.getenv("FERAL_WAKE_SENSITIVITY", "0.5")),
            timeout_seconds=float(os.getenv("FERAL_WAKE_TIMEOUT", "10")),
        )

        self._states: dict[str, WakeState] = {}
        self._activated_at: dict[str, float] = {}
        self._last_audio_at: dict[str, float] = {}
        self._pre_roll_buffer: dict[str, list[bytes]] = {}
        self._oww_model = None

        self._on_wake: Optional[Callable[[str, WakeWordEvent], Awaitable[None]]] = None

        if self._config.enabled:
            self._try_load_oww()

        logger.info(f"WakeWordDetector: enabled={self._config.enabled}, phrase='{self._config.phrase}'")

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def _try_load_oww(self):
        """Attempt to load openwakeword; graceful fallback to energy-based."""
        try:
            import openwakeword
            from openwakeword.model import Model as OWWModel

            model_name = os.getenv("FERAL_WAKE_MODEL", "hey_jarvis_v0.1")

            try:
                openwakeword.utils.download_models([model_name])
            except Exception:
                pass

            self._oww_model = OWWModel(
                wakeword_models=[model_name],
                inference_framework="onnx",
            )
            logger.info(f"openwakeword loaded (model={model_name}) — ML-based wake word detection active")
        except ImportError:
            logger.info(
                "openwakeword not installed — using energy-based fallback. "
                "Install with: pip install openwakeword onnxruntime"
            )
        except Exception as e:
            logger.warning(f"openwakeword init failed: {e} — using energy-based fallback")

    def set_on_wake(self, callback: Callable[[str, WakeWordEvent], Awaitable[None]]):
        self._on_wake = callback

    def get_state(self, session_id: str) -> WakeState:
        self._check_timeout(session_id)
        return self._states.get(session_id, WakeState.LISTENING)

    def force_activate(self, session_id: str):
        """Manually activate (e.g. button press)."""
        self._states[session_id] = WakeState.ACTIVATED
        self._activated_at[session_id] = time.time()
        self._last_audio_at[session_id] = time.time()

    def force_deactivate(self, session_id: str):
        self._states[session_id] = WakeState.LISTENING

    async def process_frame(self, session_id: str, pcm16_bytes: bytes) -> bool:
        """
        Process a PCM16 audio frame.
        Returns True if the audio should flow through to the Brain.
        """
        if not self._config.enabled:
            return True

        self._check_timeout(session_id)
        state = self._states.get(session_id, WakeState.LISTENING)

        if state == WakeState.ACTIVATED:
            self._last_audio_at[session_id] = time.time()
            return True

        # Maintain pre-roll buffer (last 500ms of audio at 24kHz PCM16 = ~24000 bytes)
        pre_roll = self._pre_roll_buffer.setdefault(session_id, [])
        pre_roll.append(pcm16_bytes)
        max_pre_roll_chunks = max(1, (self._config.pre_roll_ms * 24000 * 2) // (len(pcm16_bytes) * 1000)) if pcm16_bytes else 10
        while len(pre_roll) > max_pre_roll_chunks:
            pre_roll.pop(0)

        detected = False
        confidence = 0.0

        if self._oww_model is not None:
            detected, confidence = self._detect_oww(pcm16_bytes)
        else:
            detected, confidence = self._detect_energy(pcm16_bytes)

        if detected and confidence >= self._config.sensitivity:
            import base64
            pre_roll_audio = b"".join(pre_roll)
            event = WakeWordEvent(
                timestamp=time.time(),
                confidence=confidence,
                phrase=self._config.phrase,
                pre_roll_b64=base64.b64encode(pre_roll_audio).decode("ascii"),
            )

            self._states[session_id] = WakeState.ACTIVATED
            self._activated_at[session_id] = time.time()
            self._last_audio_at[session_id] = time.time()
            self._pre_roll_buffer.pop(session_id, None)

            logger.info(f"Wake word detected for {session_id[:8]} (confidence={confidence:.2f})")

            if self._on_wake:
                await self._on_wake(session_id, event)

            return True

        return False

    def _detect_oww(self, pcm16_bytes: bytes) -> tuple[bool, float]:
        """Use openwakeword ML model for detection."""
        try:
            import numpy as np
            audio_array = np.frombuffer(pcm16_bytes, dtype=np.int16)
            predictions = self._oww_model.predict(audio_array)
            for model_name, score in predictions.items():
                if score > self._config.sensitivity:
                    return True, float(score)
            return False, 0.0
        except Exception as e:
            logger.debug(f"OWW detection error: {e}")
            return False, 0.0

    def _detect_energy(self, pcm16_bytes: bytes) -> tuple[bool, float]:
        """
        Simple energy-based detection — not a true wake word detector,
        but detects loud audio that could be the wake phrase.
        This is a placeholder; real deployment uses openwakeword.
        """
        if len(pcm16_bytes) < 4:
            return False, 0.0

        n_samples = len(pcm16_bytes) // 2
        total_energy = 0.0
        for i in range(0, n_samples * 2, 2):
            sample = struct.unpack_from("<h", pcm16_bytes, i)[0]
            total_energy += abs(sample)

        avg_energy = total_energy / n_samples if n_samples > 0 else 0
        normalized = min(avg_energy / 3000.0, 1.0)

        return normalized > 0.7, normalized

    def _check_timeout(self, session_id: str):
        state = self._states.get(session_id)
        if state != WakeState.ACTIVATED:
            return

        last_audio = self._last_audio_at.get(session_id, 0)
        if time.time() - last_audio > self._config.timeout_seconds:
            self._states[session_id] = WakeState.LISTENING
            logger.info(f"Wake word timeout for {session_id[:8]} — returning to LISTENING")

    def cleanup_session(self, session_id: str):
        self._states.pop(session_id, None)
        self._activated_at.pop(session_id, None)
        self._last_audio_at.pop(session_id, None)
        self._pre_roll_buffer.pop(session_id, None)

    @property
    def stats(self) -> dict:
        return {
            "enabled": self._config.enabled,
            "phrase": self._config.phrase,
            "active_sessions": sum(1 for s in self._states.values() if s == WakeState.ACTIVATED),
            "using_ml": self._oww_model is not None,
        }
