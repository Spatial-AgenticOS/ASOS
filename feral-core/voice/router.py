"""
FERAL Voice Router — Triple-Path Audio Routing
===============================================
Routes audio based on source capabilities and provider config:
  - Gemini realtime → GeminiRealtimeProxy (Gemini BidiGenerateContent)
  - OpenAI realtime → RealtimeProxy (OpenAI Realtime API)
  - Whisper path    → AudioPipeline (Whisper STT → Orchestrator → TTS)
"""

from __future__ import annotations
import logging
import os
from typing import Any, Callable, Awaitable

logger = logging.getLogger("feral.voice.router")

_ENV_VOICE_PROVIDER = "FERAL_VOICE_PROVIDER"


class VoiceRouter:
    """
    Central audio routing layer.  Both web clients and daemon nodes can
    declare voice capabilities via a `voice_config` message.  The router
    uses that declaration to choose between the Gemini Realtime path,
    the OpenAI Realtime path, and the classic Whisper+TTS path.
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
        self._gemini: Any = None
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

    def set_gemini_proxy(self, proxy) -> None:
        """Inject GeminiRealtimeProxy after construction (set from api/state.py)."""
        self._gemini = proxy

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

    # ------------------------------------------------------------------
    # Provider selection helpers
    # ------------------------------------------------------------------

    def _resolve_provider(self, node_id: str) -> str:
        """Return 'gemini', 'openai', or 'whisper' for a given node."""
        cfg = self._node_voice_config.get(node_id, {})

        if cfg.get("mode") == "whisper":
            return "whisper"

        explicit = cfg.get("voice_provider", "").lower()
        if explicit == "gemini":
            if self._gemini and self._gemini.available:
                return "gemini"
        if explicit == "openai":
            if self._realtime and self._realtime.available:
                return "openai"

        env_provider = os.getenv(_ENV_VOICE_PROVIDER, "").lower()
        if env_provider == "gemini" and self._gemini and self._gemini.available:
            return "gemini"

        if cfg.get("supports_realtime") is True:
            if self._realtime and self._realtime.available:
                return "openai"

        return "whisper"

    def _resolve_session_provider(self, session_id: str) -> str:
        """Return 'gemini', 'openai', or 'whisper' for a web-client session."""
        mode = self._session_voice_mode.get(session_id, "")
        if mode != "realtime":
            return "whisper"

        env_provider = os.getenv(_ENV_VOICE_PROVIDER, "").lower()
        if env_provider == "gemini" and self._gemini and self._gemini.available:
            return "gemini"

        if self._realtime and self._realtime.available:
            return "openai"
        return "whisper"

    def should_use_realtime(self, node_id: str) -> bool:
        """Decide whether a node should use any realtime path (OpenAI or Gemini)."""
        return self._resolve_provider(node_id) in ("openai", "gemini")

    def session_uses_realtime(self, session_id: str) -> bool:
        """Check if a web client session should use a realtime path."""
        return self._resolve_session_provider(session_id) in ("openai", "gemini")

    # ------------------------------------------------------------------
    # Audio from daemon / phone nodes
    # ------------------------------------------------------------------

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
        if self._wake_word and self._wake_word.enabled:
            import base64
            pcm_bytes = base64.b64decode(audio_b64)
            should_process = await self._wake_word.process_frame(session_id, pcm_bytes)
            if not should_process:
                return

        provider = self._resolve_provider(node_id)

        if provider == "gemini":
            await self._handle_gemini_node(node_id, session_id, audio_b64)
            return

        if provider == "openai":
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

    # ------------------------------------------------------------------
    # Audio from web clients
    # ------------------------------------------------------------------

    async def handle_audio_from_client(
        self,
        session_id: str,
        audio_b64: str,
        chunk_index: int = 0,
        is_final: bool = False,
        encoding: str = "pcm16",
        sample_rate: int = 24000,
    ):
        provider = self._resolve_session_provider(session_id)
        client_node = f"webclient_{session_id[:8]}"

        if provider == "gemini":
            await self._handle_gemini_client(session_id, client_node, audio_b64)
            return

        if provider == "openai":
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

    # ------------------------------------------------------------------
    # Gemini relay helpers
    # ------------------------------------------------------------------

    async def _handle_gemini_node(self, node_id: str, session_id: str, audio_b64: str):
        gs = self._gemini.get_session(node_id)
        if not gs:
            gs = await self._gemini.start_session(session_id, node_id)
        if gs and gs.connected:
            await gs.send_audio(audio_b64)

    async def _handle_gemini_client(self, session_id: str, client_node: str, audio_b64: str):
        gs = self._gemini.get_session(client_node)
        if not gs:
            gs = await self._gemini.start_session(session_id, client_node)
        if gs and gs.connected:
            await gs.send_audio(audio_b64)

    async def handle_audio_for_gemini(
        self,
        session_id: str,
        audio_b64: str,
        *,
        node_id: str = "",
    ):
        """
        Public entry-point for callers that know they want the Gemini path.
        Resolves or creates a session, then relays audio.
        """
        if not self._gemini or not self._gemini.available:
            logger.warning("handle_audio_for_gemini called but Gemini proxy unavailable")
            return
        lookup = node_id or session_id
        gs = self._gemini.get_session(lookup)
        if not gs:
            _node = node_id or f"webclient_{session_id[:8]}"
            gs = await self._gemini.start_session(session_id, _node)
        if gs and gs.connected:
            await gs.send_audio(audio_b64)

    # ------------------------------------------------------------------
    # Whisper STT → Orchestrator → TTS  (unchanged)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Text routing
    # ------------------------------------------------------------------

    async def handle_text_from_node(self, node_id: str, session_id: str, text: str):
        """Route a text command from a node — if realtime is active, send as text there."""
        provider = self._resolve_provider(node_id)

        if provider == "gemini":
            gs = self._gemini.get_session(node_id) if self._gemini else None
            if gs and gs.connected:
                await gs.send_text(text)
                return

        if provider == "openai":
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
        """Route a text message into an active realtime voice session."""
        provider = self._resolve_session_provider(session_id)
        client_node = f"webclient_{session_id[:8]}"

        if provider == "gemini":
            gs = self._gemini.get_session(client_node) if self._gemini else None
            if gs and gs.connected:
                await gs.send_text(text)
                return

        if provider == "openai":
            rs = self._realtime.get_session(client_node) if self._realtime else None
            if rs and rs.connected:
                await rs.send_text(text)
                return

        if self._orchestrator:
            await self._orchestrator.handle_command_stream(
                session_id=session_id, text=text, context={"source": "voice_text"},
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def stop_session_voice(self, session_id: str):
        """Stop realtime voice for a web client session."""
        client_node = f"webclient_{session_id[:8]}"

        if self._gemini:
            gsid = self._gemini._node_to_session.get(client_node)
            if gsid:
                await self._gemini.stop_session(gsid)

        if self._realtime:
            sid_for_node = self._realtime._node_to_session.get(client_node)
            if sid_for_node:
                await self._realtime.stop_session(sid_for_node)

        self._session_voice_mode.pop(session_id, None)
        logger.info(f"Voice stopped for session {session_id[:8]}")

    # --- Subagent A (realtime GA) additions ---
    async def open_session(self, session_id: str, mode: str, provider_opts: dict | None = None):
        """High-level entry point for opening a voice session by mode.

        Dispatches ``mode="openai_realtime"`` to the updated GA proxy.
        Other modes are wired by their respective subagents.
        """
        opts = provider_opts or {}
        if mode == "openai_realtime":
            if not self._realtime or not self._realtime.available:
                logger.warning("openai_realtime requested but proxy unavailable")
                return None
            node_id = opts.get("node_id", f"webclient_{session_id[:8]}")
            model = opts.get("model", "gpt-realtime")
            voice = opts.get("voice", "marin")
            rs = await self._realtime.start_session(
                session_id, node_id, model=model, voice=voice,
            )
            return rs
        logger.debug("open_session: mode=%s not handled by Subagent A", mode)
        return None
    # --- end Subagent A additions ---

    async def shutdown(self):
        if self._realtime:
            await self._realtime.shutdown()
        if self._gemini:
            await self._gemini.shutdown()
