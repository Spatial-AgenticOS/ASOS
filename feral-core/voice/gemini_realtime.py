"""
FERAL Gemini Multimodal Live — Realtime Voice via Google's API
================================================================
Single-WebSocket realtime voice using Gemini's Multimodal Live API.
Same pattern as OpenAI Realtime: audio in/out, function calling.
"""

from __future__ import annotations
import asyncio
import base64
import json
import logging
import os
from typing import Optional, Callable, Awaitable
from uuid import uuid4

logger = logging.getLogger("feral.voice.gemini_realtime")

GEMINI_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
SAMPLE_RATE = 24000
AUDIO_FORMAT = "pcm16"


class GeminiRealtimeSession:
    """
    Single Gemini Multimodal Live session over WebSocket.
    Audio in/out with function calling support.
    """

    def __init__(
        self,
        session_id: str,
        node_id: str,
        *,
        api_key: str = "",
        model: str = "gemini-2.0-flash-exp",
        system_prompt: str = "",
        tools: list[dict] | None = None,
        on_audio_delta: Callable | None = None,
        on_transcript: Callable | None = None,
        on_tool_call: Callable | None = None,
        on_speech_started: Callable | None = None,
        on_error: Callable | None = None,
    ):
        self.session_id = session_id
        self.node_id = node_id
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = model
        self._system_prompt = system_prompt
        self._tools = tools or []

        self._on_audio_delta = on_audio_delta
        self._on_transcript = on_transcript
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
            url = f"{GEMINI_WS_URL}?key={self._api_key}"
            self._ws = await websockets.connect(
                url,
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

    async def _send_setup(self):
        """Send initial setup message with model config and tools."""
        gemini_tools = []
        for t in self._tools:
            fn = t.get("function", {})
            gemini_tools.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })

        setup = {
            "setup": {
                "model": f"models/{self._model}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}
                    },
                },
                "systemInstruction": {
                    "parts": [{"text": self._system_prompt}]
                },
                "tools": [{"functionDeclarations": gemini_tools}] if gemini_tools else [],
            }
        }
        await self._send(setup)

    async def send_audio(self, audio_b64: str):
        if not self._connected:
            return
        await self._send({
            "realtimeInput": {
                "mediaChunks": [{
                    "mimeType": "audio/pcm;rate=24000",
                    "data": audio_b64,
                }]
            }
        })

    async def send_text(self, text: str):
        if not self._connected:
            return
        await self._send({
            "clientContent": {
                "turns": [{"role": "user", "parts": [{"text": text}]}],
                "turnComplete": True,
            }
        })

    async def send_tool_response(self, function_responses: list[dict]):
        await self._send({
            "toolResponse": {
                "functionResponses": function_responses,
            }
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

        server_content = event.get("serverContent", {})
        if server_content:
            parts = server_content.get("modelTurn", {}).get("parts", [])
            for part in parts:
                if "inlineData" in part:
                    inline = part["inlineData"]
                    if inline.get("mimeType", "").startswith("audio/"):
                        if self._on_audio_delta:
                            await self._on_audio_delta(
                                self.session_id, inline.get("data", ""), False,
                            )
                elif "text" in part:
                    if self._on_transcript:
                        await self._on_transcript(
                            self.session_id, part["text"],
                            not server_content.get("turnComplete", False),
                        )

            if server_content.get("turnComplete"):
                if self._on_audio_delta:
                    await self._on_audio_delta(self.session_id, "", True)

            if server_content.get("interrupted"):
                if self._on_speech_started:
                    await self._on_speech_started(self.session_id)

        tool_call = event.get("toolCall", {})
        if tool_call:
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
                        "response": json.loads(result) if isinstance(result, str) else result,
                        "id": call_id,
                    }])

        if "error" in event:
            error = event["error"]
            msg = error.get("message", str(error))
            logger.error(f"Gemini API error: {msg}")
            if self._on_error:
                await self._on_error(self.session_id, msg)


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
        self._api_key = os.getenv("GEMINI_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def start_session(
        self,
        session_id: str,
        node_id: str,
        model: str = "gemini-2.0-flash-exp",
        system_prompt: str = "",
        on_audio_delta: Callable | None = None,
        on_transcript: Callable | None = None,
        on_tool_call: Callable | None = None,
        on_speech_started: Callable | None = None,
        on_error: Callable | None = None,
    ) -> GeminiRealtimeSession:
        _sys_prompt = system_prompt or self._build_system_prompt(session_id)
        tools = self._get_tools()

        gs = GeminiRealtimeSession(
            session_id=session_id,
            node_id=node_id,
            api_key=self._api_key,
            model=model,
            system_prompt=_sys_prompt,
            tools=tools,
            on_audio_delta=on_audio_delta or self._handle_audio_delta,
            on_transcript=on_transcript or self._handle_transcript,
            on_tool_call=on_tool_call or self._handle_tool_call,
            on_speech_started=on_speech_started or self._handle_speech_started,
            on_error=on_error or self._handle_error,
        )

        await gs.connect()
        self._sessions[session_id] = gs
        self._node_to_session[node_id] = session_id
        return gs

    async def stop_session(self, session_id: str):
        gs = self._sessions.pop(session_id, None)
        if gs:
            self._node_to_session.pop(gs.node_id, None)
            await gs.disconnect()

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    async def relay_audio(self, session_id_or_node: str, audio_b64: str):
        gs = self._sessions.get(session_id_or_node)
        if not gs:
            sid = self._node_to_session.get(session_id_or_node)
            gs = self._sessions.get(sid) if sid else None
        if gs and gs.connected:
            await gs.send_audio(audio_b64)

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
            "sample_rate": SAMPLE_RATE, "is_final": is_done,
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
