"""
FERAL Gemini Multimodal Live — Realtime Voice via Google's API
================================================================
Single-WebSocket realtime voice using Gemini's BidiGenerateContent API.
Same pattern as OpenAI Realtime: audio in/out, function calling, transcriptions.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from typing import Optional, Callable
from uuid import uuid4

logger = logging.getLogger("feral.voice.gemini")

GEMINI_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
DEFAULT_MODEL = "gemini-2.0-flash-live-001"
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
AUDIO_FORMAT = "pcm16"


class GeminiRealtimeSession:
    """
    Single Gemini Multimodal Live session over WebSocket.
    Audio/video in, audio out, with function-calling support.
    """

    def __init__(
        self,
        session_id: str,
        node_id: str,
        *,
        api_key: str = "",
        model: str = "",
        system_prompt: str = "",
        tools: list[dict] | None = None,
        on_audio_delta: Callable | None = None,
        on_transcript: Callable | None = None,
        on_input_transcript: Callable | None = None,
        on_tool_call: Callable | None = None,
        on_speech_started: Callable | None = None,
        on_error: Callable | None = None,
    ):
        self.session_id = session_id
        self.node_id = node_id
        self._api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self._model = model or os.getenv("FERAL_GEMINI_LIVE_MODEL", DEFAULT_MODEL)
        self._system_prompt = system_prompt
        self._tools = tools or []

        self._on_audio_delta = on_audio_delta
        self._on_transcript = on_transcript
        self._on_input_transcript = on_input_transcript
        self._on_tool_call = on_tool_call
        self._on_speech_started = on_speech_started
        self._on_error = on_error

        self._ws = None
        self._connected = False
        self._recv_task: Optional[asyncio.Task] = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self):
        if not self._api_key:
            logger.error("Cannot start Gemini realtime — no GEMINI_API_KEY")
            return

        try:
            import websockets
            headers = {"x-goog-api-key": self._api_key}
            self._ws = await self._connect_with_retry(
                GEMINI_WS_URL,
                additional_headers=headers,
                max_size=10 * 1024 * 1024,
                ping_interval=20,
            )
            self._connected = True
            self._recv_task = asyncio.create_task(self._receive_loop())

            await self._send_setup()
            logger.info(f"Gemini realtime session opened: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to connect to Gemini realtime: {e}")
            self._connected = False

    @staticmethod
    async def _connect_with_retry(url, **kwargs):
        import websockets
        for attempt in range(3):
            try:
                return await websockets.connect(url, **kwargs)
            except Exception:
                if attempt == 2:
                    raise
                logger.warning("Gemini WS connect failed (attempt %d/3) — retrying", attempt + 1)
                await asyncio.sleep(2 ** attempt)

    async def _send_setup(self):
        """Send initial config message with model, system instruction, and tools."""
        function_declarations = []
        for t in self._tools:
            fn = t.get("function", {})
            function_declarations.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })

        config: dict = {
            "model": f"models/{self._model}",
            "responseModalities": ["AUDIO"],
            "systemInstruction": {
                "parts": [{"text": self._system_prompt}],
            },
        }
        if function_declarations:
            config["tools"] = [{"functionDeclarations": function_declarations}]

        await self._send({"config": config})

    async def send_audio(self, audio_b64: str):
        """Stream a chunk of PCM16 audio at 16 kHz to Gemini."""
        if not self._connected:
            return
        t0 = time.monotonic()
        await self._send({
            "realtimeInput": {
                "audio": {
                    "data": audio_b64,
                    "mimeType": f"audio/pcm;rate={INPUT_SAMPLE_RATE}",
                },
            },
        })
        logger.debug("audio_chunk sent session=%s latency_ms=%.1f", self.session_id, (time.monotonic() - t0) * 1000)

    async def send_video(self, frame_b64: str, mime_type: str = "image/jpeg"):
        """Stream a video/image frame to Gemini for multimodal context."""
        if not self._connected:
            return
        await self._send({
            "realtimeInput": {
                "video": {
                    "data": frame_b64,
                    "mimeType": mime_type,
                },
            },
        })

    async def send_text(self, text: str):
        """Send a text message into the live session."""
        if not self._connected:
            return
        await self._send({
            "realtimeInput": {
                "text": text,
            },
        })

    async def send_tool_response(self, function_responses: list[dict]):
        """Return tool results to the model so it can continue generating."""
        await self._send({
            "toolResponse": {
                "functionResponses": function_responses,
            },
        })

    async def disconnect(self):
        self._connected = False
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        logger.info(f"Gemini realtime session closed: {self.session_id}")

    async def _send(self, message: dict):
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps(message))
            except Exception as e:
                logger.error(f"Gemini send error: {e}")
                self._connected = False

    async def _receive_loop(self):
        try:
            async for raw_msg in self._ws:
                try:
                    event = json.loads(raw_msg)
                    await self._handle_event(event)
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"Gemini receive error: {e}")
            self._connected = False

    async def _handle_event(self, event: dict):
        if "setupComplete" in event:
            logger.info("Gemini setup complete")
            return

        server_content = event.get("serverContent")
        if server_content:
            await self._handle_server_content(server_content)

        tool_call = event.get("toolCall")
        if tool_call:
            await self._handle_tool_call_event(tool_call)

        if "error" in event:
            error = event["error"]
            msg = error.get("message", str(error))
            logger.error(f"Gemini API error: {msg}")
            if self._on_error:
                await self._on_error(self.session_id, msg)

    async def _handle_server_content(self, sc: dict):
        parts = sc.get("modelTurn", {}).get("parts", [])
        for part in parts:
            if "inlineData" in part:
                inline = part["inlineData"]
                if inline.get("mimeType", "").startswith("audio/"):
                    if self._on_audio_delta:
                        await self._on_audio_delta(
                            self.session_id, inline.get("data", ""), False,
                        )

        input_tx = sc.get("inputTranscription", {}).get("text")
        if input_tx and self._on_input_transcript:
            await self._on_input_transcript(self.session_id, input_tx)

        output_tx = sc.get("outputTranscription", {}).get("text")
        if output_tx and self._on_transcript:
            await self._on_transcript(self.session_id, output_tx, True)

        if sc.get("turnComplete"):
            if self._on_transcript:
                await self._on_transcript(self.session_id, "", False)
            if self._on_audio_delta:
                await self._on_audio_delta(self.session_id, "", True)

        if sc.get("interrupted"):
            if self._on_speech_started:
                await self._on_speech_started(self.session_id)

    async def _handle_tool_call_event(self, tool_call: dict):
        function_calls = tool_call.get("functionCalls", [])
        for fc in function_calls:
            name = fc.get("name", "")
            args = json.dumps(fc.get("args", {}))
            call_id = fc.get("id", str(uuid4())[:8])
            logger.info(f"Gemini tool call: {name}")
            if self._on_tool_call:
                result = await self._on_tool_call(
                    self.session_id, call_id, name, args,
                )
                await self.send_tool_response([{
                    "name": name,
                    "id": call_id,
                    "response": json.loads(result) if isinstance(result, str) else result,
                }])


class GeminiRealtimeProxy:
    """Manages Gemini realtime sessions, mirrors RealtimeProxy interface."""

    def __init__(
        self,
        *,
        skill_registry=None,
        skill_executor=None,
        memory=None,
        perception=None,
        send_to_node=None,
        send_to_session=None,
    ):
        self._sessions: dict[str, GeminiRealtimeSession] = {}
        self._node_to_session: dict[str, str] = {}
        self._skill_registry = skill_registry
        self._skill_executor = skill_executor
        self._memory = memory
        self._perception = perception
        self._send_to_node = send_to_node
        self._send_to_session = send_to_session
        self._api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def get_session(self, node_id: str) -> GeminiRealtimeSession | None:
        """Look up session by node_id (mirrors RealtimeProxy.get_session)."""
        sid = self._node_to_session.get(node_id)
        return self._sessions.get(sid) if sid else None

    async def start_session(
        self,
        session_id: str,
        node_id: str,
        model: str = "",
        system_prompt: str = "",
        on_audio_delta: Callable | None = None,
        on_transcript: Callable | None = None,
        on_tool_call: Callable | None = None,
        on_speech_started: Callable | None = None,
        on_error: Callable | None = None,
    ) -> GeminiRealtimeSession:
        _sys_prompt = system_prompt or self._build_system_prompt(session_id)
        _model = model or os.getenv("FERAL_GEMINI_LIVE_MODEL", DEFAULT_MODEL)
        tools = self._get_tools()

        gs = GeminiRealtimeSession(
            session_id=session_id,
            node_id=node_id,
            api_key=self._api_key,
            model=_model,
            system_prompt=_sys_prompt,
            tools=tools,
            on_audio_delta=on_audio_delta or self._handle_audio_delta,
            on_transcript=on_transcript or self._handle_transcript,
            on_input_transcript=self._handle_input_transcript,
            on_tool_call=on_tool_call or self._handle_tool_call,
            on_speech_started=on_speech_started or self._handle_speech_started,
            on_error=on_error or self._handle_error,
        )

        await gs.connect()
        if not getattr(gs, 'connected', False) and not getattr(gs, '_ws', None):
            logger.warning("Gemini voice session failed to connect for %s", session_id)
            return None
        self._sessions[session_id] = gs
        self._node_to_session[node_id] = session_id

        try:
            from api.state import state
            if state.orchestrator:
                for sid in list(state.sessions.keys()):
                    await state.orchestrator._emit_brain_event(sid, "voice_session", {
                        "active": True, "provider": "gemini", "session_id": session_id,
                    })
        except Exception:
            pass

        return gs

    async def stop_session(self, session_id: str):
        gs = self._sessions.pop(session_id, None)
        if gs:
            self._node_to_session.pop(gs.node_id, None)
            await gs.disconnect()

            try:
                from api.state import state
                if state.orchestrator:
                    for sid in list(state.sessions.keys()):
                        await state.orchestrator._emit_brain_event(sid, "voice_session", {
                            "active": False, "provider": "gemini", "session_id": session_id,
                        })
            except Exception:
                pass

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    async def relay_audio(self, session_id_or_node: str, audio_b64: str):
        gs = self._sessions.get(session_id_or_node)
        if not gs:
            sid = self._node_to_session.get(session_id_or_node)
            gs = self._sessions.get(sid) if sid else None
        if gs and gs.connected:
            await gs.send_audio(audio_b64)

    async def relay_video(self, session_id_or_node: str, frame_b64: str, mime_type: str = "image/jpeg"):
        """Forward a video/image frame to an active Gemini session."""
        gs = self._sessions.get(session_id_or_node)
        if not gs:
            sid = self._node_to_session.get(session_id_or_node)
            gs = self._sessions.get(sid) if sid else None
        if gs and gs.connected:
            await gs.send_video(frame_b64, mime_type)

    async def shutdown(self):
        for sid in list(self._sessions):
            await self.stop_session(sid)

    def _build_system_prompt(self, session_id: str) -> str:
        parts = [
            "You are FERAL, a personal AI operating system. "
            "You run locally on the user's devices and can control hardware, "
            "search the web, manage memory, and more. Be concise in voice."
        ]
        if self._memory:
            ctx = self._memory.build_context_for_llm(session_id, max_tokens_budget=400)
            if ctx:
                parts.append(f"\n[Memory]\n{ctx}")
        return "\n".join(parts)

    def _get_tools(self) -> list[dict]:
        if self._skill_registry:
            return self._skill_registry.get_all_tools()
        return []

    @staticmethod
    def _tool_feedback_text(tool_name: str) -> str:
        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            return "Working on that now."
        skill_id, endpoint_id = parts
        if skill_id == "web_search":
            return "Searching the web now."
        if skill_id == "weather_current":
            return "Checking the weather."
        if skill_id == "browser":
            return f"Using the browser to {endpoint_id.replace('_', ' ')}."
        if skill_id == "computer_use" and endpoint_id == "bash":
            return "Running a command on your computer."
        return f"Running {endpoint_id.replace('_', ' ')}."

    async def _send_tool_feedback(self, session_id: str, text: str):
        if not text:
            return
        gs = self._sessions.get(session_id)
        if not gs:
            return
        if gs.node_id.startswith("webclient_") and self._send_to_session:
            from models.protocol import FeralMessage

            msg = FeralMessage(
                session_id=session_id,
                hop="brain",
                type="transcript",
                payload={"text": text, "role": "assistant", "is_partial": False},
            )
            await self._send_to_session(session_id, msg)
            return
        if self._send_to_node:
            await self._send_to_node(gs.node_id, {
                "type": "transcript",
                "payload": {"text": text, "role": "assistant", "is_partial": False},
            })

    async def _handle_audio_delta(self, session_id: str, audio_b64: str, is_done: bool):
        gs = self._sessions.get(session_id)
        if not gs:
            return
        payload = {
            "data_b64": audio_b64, "encoding": AUDIO_FORMAT,
            "sample_rate": OUTPUT_SAMPLE_RATE, "is_final": is_done,
        }
        if gs.node_id.startswith("webclient_") and self._send_to_session:
            from models.protocol import FeralMessage
            msg = FeralMessage(
                session_id=session_id, hop="brain", type="audio_response",
                payload=payload,
            )
            await self._send_to_session(session_id, msg)
        elif self._send_to_node:
            await self._send_to_node(gs.node_id, {"type": "audio_response", "payload": payload})

    async def _handle_transcript(self, session_id: str, text: str, is_partial: bool):
        if not is_partial and text and self._memory:
            self._memory.working_push(session_id, {
                "role": "assistant", "text": text[:300], "source": "gemini_realtime",
            })

    async def _handle_input_transcript(self, session_id: str, text: str):
        """Handle user-speech transcription returned by Gemini."""
        if text and self._memory:
            self._memory.working_push(session_id, {
                "role": "user", "text": text[:300], "source": "gemini_realtime_input",
            })
        gs = self._sessions.get(session_id)
        if not gs:
            return
        payload = {"text": text, "role": "user", "is_partial": False}
        if gs.node_id.startswith("webclient_") and self._send_to_session:
            from models.protocol import FeralMessage
            msg = FeralMessage(
                session_id=session_id, hop="brain", type="transcript",
                payload=payload,
            )
            await self._send_to_session(session_id, msg)
        elif self._send_to_node:
            await self._send_to_node(gs.node_id, {"type": "transcript", "payload": payload})

    async def _handle_tool_call(self, session_id: str, call_id: str, name: str, arguments: str) -> str:
        if not self._skill_executor or not self._skill_registry:
            return json.dumps({"error": "No skill executor"})
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            args = {}
        parts = name.split("__", 1)
        if len(parts) != 2:
            return json.dumps({"error": f"Invalid tool: {name}"})
        skill_id, endpoint_id = parts
        skill = self._skill_registry.skills.get(skill_id)
        if not skill:
            return json.dumps({"error": f"Skill not found: {skill_id}"})
        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            return json.dumps({"error": f"Endpoint not found: {endpoint_id}"})
        await self._send_tool_feedback(session_id, self._tool_feedback_text(name))
        result = await self._skill_executor.execute(name, args, skill, endpoint)
        return json.dumps(result.get("data") or {"status": result.get("error", "done")})

    async def _handle_speech_started(self, session_id: str):
        gs = self._sessions.get(session_id)
        if not gs:
            return
        payload = {"action": "stop_playback"}
        if gs.node_id.startswith("webclient_") and self._send_to_session:
            from models.protocol import FeralMessage

            msg = FeralMessage(
                session_id=session_id,
                hop="brain",
                type="speech_started",
                payload=payload,
            )
            await self._send_to_session(session_id, msg)
            return
        if self._send_to_node:
            await self._send_to_node(gs.node_id, {
                "type": "speech_started", "payload": payload,
            })

    async def _handle_error(self, session_id: str, error: str):
        logger.error(f"Gemini error [{session_id}]: {error}")
