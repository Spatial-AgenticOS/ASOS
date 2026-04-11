"""
FERAL Voice Router — Dual-Path Audio Routing
===============================================
Routes audio based on source capabilities:
  - Phone/glasses with realtime support → RealtimeProxy (OpenAI Realtime API)
  - Web client / channels → AudioPipeline (Whisper STT → Orchestrator → TTS)
"""

from __future__ import annotations
import logging
import os
from typing import Optional, Any, Callable, Awaitable

logger = logging.getLogger("feral.voice.router")


class VoiceRouter:
    """
    Central audio routing layer.  Both web clients and daemon nodes can
    declare voice capabilities via a `voice_config` message.  The router
    uses that declaration to choose between the OpenAI Realtime path and
    the classic Whisper+TTS path.
    """

    def __init__(
        self,
        *,
        realtime_proxy=None,
        audio_pipeline=None,
        orchestrator=None,
        memory=None,
        perception=None,
        wake_word_detector=None,
        send_to_session: Callable[[str, Any], Awaitable[None]] | None = None,
        send_to_node: Callable[[str, dict], Awaitable[None]] | None = None,
    ):
        self._realtime = realtime_proxy
        self._audio = audio_pipeline
        self._orchestrator = orchestrator
        self._memory = memory
        self._perception = perception
        self._wake_word = wake_word_detector
        self._send_to_session = send_to_session
        self._send_to_node = send_to_node

        self._node_voice_config: dict[str, dict] = {}
        self._node_session_map: dict[str, str] = {}
        self._session_voice_mode: dict[str, str] = {}

    def register_voice_config(self, node_id: str, config: dict):
        """Store a node's voice capabilities.  Called when a `voice_config` message arrives."""
        self._node_voice_config[node_id] = config
        logger.info(f"Voice config for {node_id}: {config}")

    def set_session_voice_mode(self, session_id: str, mode: str):
        """Set the voice mode for a web client session (realtime | whisper | disabled)."""
        self._session_voice_mode[session_id] = mode
        logger.info(f"Session {session_id[:8]} voice mode: {mode}")

    def bind_node_to_session(self, node_id: str, session_id: str):
        self._node_session_map[node_id] = session_id

    def should_use_realtime(self, node_id: str) -> bool:
        """Decide whether a node should use the OpenAI Realtime path."""
        if not self._realtime or not self._realtime.available:
            return False

        cfg = self._node_voice_config.get(node_id, {})

        if cfg.get("mode") == "whisper":
            return False
        if cfg.get("supports_realtime") is True:
            return True

        return False

    def session_uses_realtime(self, session_id: str) -> bool:
        """Check if a web client session should use the Realtime path."""
        if not self._realtime or not self._realtime.available:
            return False
        return self._session_voice_mode.get(session_id) == "realtime"

    async def handle_audio_from_node(
        self,
        node_id: str,
        session_id: str,
        audio_b64: str,
        chunk_index: int = 0,
        is_final: bool = False,
        encoding: str = "pcm16",
        sample_rate: int = 24000,
    ):
        """
        Route incoming audio from a daemon/phone node.
        If the node uses realtime, relay to OpenAI.
        Otherwise, accumulate in Whisper pipeline.
        """
        # Wake word gate for node audio
        if self._wake_word and self._wake_word.enabled:
            import base64
            pcm_bytes = base64.b64decode(audio_b64)
            should_process = await self._wake_word.process_frame(session_id, pcm_bytes)
            if not should_process:
                return

        if self.should_use_realtime(node_id):
            rs = self._realtime.get_session(node_id)
            if not rs:
                rs = await self._realtime.start_session(session_id, node_id)
            if rs and rs.connected:
                await rs.send_audio(audio_b64)
            return

        await self._handle_whisper_path(
            session_id=session_id,
            audio_b64=audio_b64,
            chunk_index=chunk_index,
            is_final=is_final,
            encoding=encoding,
            sample_rate=sample_rate,
            source_node_id=node_id,
        )

    async def handle_audio_from_client(
        self,
        session_id: str,
        audio_b64: str,
        chunk_index: int = 0,
        is_final: bool = False,
        encoding: str = "pcm16",
        sample_rate: int = 24000,
    ):
        """
        Route audio from the web client.
        If session is in realtime mode → OpenAI Realtime API (bi-directional voice + tools).
        Otherwise → classic Whisper STT + Orchestrator + TTS.
        """
        if self.session_uses_realtime(session_id):
            client_node = f"webclient_{session_id[:8]}"
            rs = self._realtime.get_session(client_node)
            if not rs:
                rs = await self._realtime.start_session(session_id, client_node)
            if rs and rs.connected:
                await rs.send_audio(audio_b64)
            return

        await self._handle_whisper_path(
            session_id=session_id,
            audio_b64=audio_b64,
            chunk_index=chunk_index,
            is_final=is_final,
            encoding=encoding,
            sample_rate=sample_rate,
        )

    async def _handle_whisper_path(
        self,
        session_id: str,
        audio_b64: str,
        chunk_index: int,
        is_final: bool,
        encoding: str,
        sample_rate: int,
        source_node_id: str = "",
    ):
        """Classic STT → Orchestrator → TTS flow."""
        if not self._audio:
            return

        transcript = await self._audio.process_audio_chunk(
            session_id=session_id,
            chunk_b64=audio_b64,
            chunk_index=chunk_index,
            is_final=is_final,
            encoding=encoding,
            sample_rate=sample_rate,
        )

        if not transcript:
            return

        from models.protocol import FeralMessage, TranscriptPayload
        if self._send_to_session:
            msg = FeralMessage(
                session_id=session_id, hop="brain", type="transcript",
                payload=TranscriptPayload(text=transcript, is_partial=False).model_dump(),
            )
            await self._send_to_session(session_id, msg)

        if source_node_id and self._send_to_node:
            await self._send_to_node(source_node_id, {
                "type": "transcript",
                "payload": {"text": transcript, "role": "user", "is_partial": False},
            })

        if self._memory:
            self._memory.working_push(session_id, {
                "role": "user", "text": transcript, "source": "voice",
            })

        if self._perception:
            self._perception.update_audio_context(session_id, transcript=transcript)

        if self._orchestrator:
            await self._orchestrator.handle_command_stream(
                session_id=session_id,
                text=transcript,
                context={"source": "voice", "node_id": source_node_id} if source_node_id else {"source": "voice"},
            )

            tts_text = self._get_last_assistant_text(session_id)
            if tts_text and self._audio:
                chunks = await self._audio.synthesize_speech(tts_text)
                if chunks:
                    for chunk in chunks:
                        tts_msg = FeralMessage(
                            session_id=session_id, hop="brain", type="tts_chunk",
                            payload=chunk,
                        )
                        if self._send_to_session:
                            await self._send_to_session(session_id, tts_msg)
                        if source_node_id and self._send_to_node:
                            await self._send_to_node(source_node_id, {
                                "type": "tts_chunk",
                                "payload": chunk,
                            })

    def _get_last_assistant_text(self, session_id: str) -> str:
        """Pull the latest assistant response from working memory for TTS."""
        if not self._memory:
            return ""
        history = self._memory.working_get(session_id) or []
        for msg in reversed(history):
            if msg.get("role") == "assistant":
                return msg.get("text", "")[:1000]
        return ""

    async def handle_text_from_node(self, node_id: str, session_id: str, text: str):
        """Route a text command from a node — if realtime is active, send as text there."""
        if self.should_use_realtime(node_id):
            rs = self._realtime.get_session(node_id)
            if rs and rs.connected:
                await rs.send_text(text)
                return

        if self._orchestrator:
            await self._orchestrator.handle_command_stream(
                session_id=session_id,
                text=text,
                context={"source": "node_text", "node_id": node_id},
            )

    async def handle_text_from_client_voice(self, session_id: str, text: str):
        """Route a text message into an active realtime voice session (typed while voice is on)."""
        if self.session_uses_realtime(session_id):
            client_node = f"webclient_{session_id[:8]}"
            rs = self._realtime.get_session(client_node) if self._realtime else None
            if rs and rs.connected:
                await rs.send_text(text)
                return
        if self._orchestrator:
            await self._orchestrator.handle_command_stream(
                session_id=session_id, text=text, context={"source": "voice_text"},
            )

    async def stop_session_voice(self, session_id: str):
        """Stop realtime voice for a web client session."""
        client_node = f"webclient_{session_id[:8]}"
        if self._realtime:
            sid_for_node = self._realtime._node_to_session.get(client_node)
            if sid_for_node:
                await self._realtime.stop_session(sid_for_node)
        self._session_voice_mode.pop(session_id, None)
        logger.info(f"Voice stopped for session {session_id[:8]}")

    async def shutdown(self):
        if self._realtime:
            await self._realtime.shutdown()
