"""
THEORA Realtime Voice Proxy — OpenAI Realtime API Bridge
=========================================================
The Brain opens one OpenAI Realtime WebSocket session per connected
phone/glasses node.  Phone sends PCM16 audio to the Brain; the Brain
relays it to OpenAI Realtime.  OpenAI sends audio back; the Brain
relays it to the phone.  Tool calls are intercepted and executed
locally through the full skill/hardware/memory ecosystem.

The phone never talks to OpenAI directly — the Brain owns the context.
"""

from __future__ import annotations
import asyncio
import base64
import json
import logging
import os
import time
from typing import Optional, Callable, Awaitable, Any
from uuid import uuid4

import httpx

logger = logging.getLogger("theora.voice.realtime")

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
DEFAULT_MODEL = "gpt-4o-realtime-preview-2024-12-17"
SAMPLE_RATE = 24000
AUDIO_FORMAT = "pcm16"


class RealtimeSession:
    """
    Manages a single OpenAI Realtime WebSocket session on behalf of a
    connected phone/glasses node.  Handles audio relay, tool interception,
    and perception context injection.
    """

    def __init__(
        self,
        session_id: str,
        node_id: str,
        *,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        on_audio_delta: Callable[[str, str, bool], Awaitable[None]] | None = None,
        on_transcript: Callable[[str, str, bool], Awaitable[None]] | None = None,
        on_tool_call: Callable[[str, str, str, str], Awaitable[str]] | None = None,
        on_speech_started: Callable[[str], Awaitable[None]] | None = None,
        on_error: Callable[[str, str], Awaitable[None]] | None = None,
    ):
        self.session_id = session_id
        self.node_id = node_id
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
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
        self._pending_tool_calls: dict[str, dict] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self):
        """Open a WebSocket to the OpenAI Realtime API."""
        if not self._api_key:
            logger.error("Cannot start realtime session — no OPENAI_API_KEY")
            return

        try:
            import websockets
            url = f"{OPENAI_REALTIME_URL}?model={self._model}"
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Beta": "realtime=v1",
            }
            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
                max_size=10 * 1024 * 1024,
                ping_interval=20,
            )
            self._connected = True
            self._recv_task = asyncio.create_task(self._receive_loop())
            logger.info(f"Realtime session opened: {self.session_id} / node={self.node_id}")
        except Exception as e:
            logger.error(f"Failed to connect to OpenAI Realtime: {e}")
            self._connected = False

    async def configure(self, system_prompt: str = "", tools: list[dict] | None = None):
        """Send session.update with system prompt, tools, and voice/VAD config."""
        if not self._connected:
            return

        self._system_prompt = system_prompt or self._system_prompt
        if tools is not None:
            self._tools = tools

        openai_tools = []
        for t in self._tools:
            fn = t.get("function", {})
            openai_tools.append({
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })

        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": self._system_prompt,
                "voice": "sage",
                "input_audio_format": AUDIO_FORMAT,
                "output_audio_format": AUDIO_FORMAT,
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800,
                },
                "tools": openai_tools,
                "tool_choice": "auto",
                "temperature": 0.7,
                "max_response_output_tokens": 4096,
            },
        }

        await self._send(session_update)
        logger.info(f"Realtime session configured: {len(openai_tools)} tools")

    async def send_audio(self, audio_b64: str):
        """Relay PCM16 audio from the phone to OpenAI Realtime."""
        if not self._connected:
            return
        await self._send({
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        })

    async def send_text(self, text: str):
        """Send a text message into the realtime conversation."""
        if not self._connected:
            return
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        })
        await self._send({"type": "response.create"})

    async def send_tool_result(self, call_id: str, result: str):
        """Return a tool execution result to OpenAI and continue the response."""
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result,
            },
        })
        await self._send({"type": "response.create"})

    async def cancel_response(self):
        """Cancel the current response (e.g., user interrupted)."""
        if self._connected:
            await self._send({"type": "response.cancel"})

    async def inject_context(self, context_text: str):
        """Inject updated perception context as a system-level message."""
        if not self._connected or not context_text:
            return
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": context_text}],
            },
        })

    async def disconnect(self):
        """Gracefully close the realtime session."""
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
        logger.info(f"Realtime session closed: {self.session_id}")

    async def _send(self, event: dict):
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps(event))
            except Exception as e:
                logger.error(f"Realtime send error: {e}")
                self._connected = False

    async def _receive_loop(self):
        """Process incoming events from OpenAI Realtime."""
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
            logger.error(f"Realtime receive error: {e}")
            self._connected = False

    async def _handle_event(self, event: dict):
        event_type = event.get("type", "")

        if event_type == "session.created":
            logger.info("Realtime session.created — configuring...")
            await self.configure()

        elif event_type == "response.audio.delta":
            delta_b64 = event.get("delta", "")
            if delta_b64 and self._on_audio_delta:
                await self._on_audio_delta(self.session_id, delta_b64, False)

        elif event_type == "response.audio.done":
            if self._on_audio_delta:
                await self._on_audio_delta(self.session_id, "", True)

        elif event_type == "response.audio_transcript.delta":
            text = event.get("delta", "")
            if text and self._on_transcript:
                await self._on_transcript(self.session_id, text, False)

        elif event_type == "response.audio_transcript.done":
            text = event.get("transcript", "")
            if text and self._on_transcript:
                await self._on_transcript(self.session_id, text, True)

        elif event_type == "conversation.item.input_audio_transcription.completed":
            text = event.get("transcript", "")
            if text and self._on_transcript:
                await self._on_transcript(self.session_id, f"[user] {text}", True)

        elif event_type == "input_audio_buffer.speech_started":
            if self._on_speech_started:
                await self._on_speech_started(self.session_id)

        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id", "")
            name = event.get("name", "")
            arguments = event.get("arguments", "{}")
            logger.info(f"Realtime tool call: {name} (call_id={call_id})")

            if self._on_tool_call:
                result = await self._on_tool_call(self.session_id, call_id, name, arguments)
                await self.send_tool_result(call_id, result)

        elif event_type == "error":
            err = event.get("error", {})
            msg = err.get("message", str(err))
            logger.error(f"Realtime API error: {msg}")
            if self._on_error:
                await self._on_error(self.session_id, msg)

        elif event_type in ("response.done", "response.created", "rate_limits.updated"):
            pass  # informational, no action needed


class RealtimeProxy:
    """
    Manages all active RealtimeSession instances — one per phone/glasses node.
    Provides the high-level interface that the Brain server uses.
    """

    def __init__(
        self,
        *,
        skill_registry=None,
        skill_executor=None,
        memory=None,
        perception=None,
        send_to_node: Callable[[str, dict], Awaitable[None]] | None = None,
        send_to_session: Callable[[str, Any], Awaitable[None]] | None = None,
    ):
        self._sessions: dict[str, RealtimeSession] = {}
        self._node_to_session: dict[str, str] = {}
        self._skill_registry = skill_registry
        self._skill_executor = skill_executor
        self._memory = memory
        self._perception = perception
        self._send_to_node = send_to_node
        self._send_to_session = send_to_session
        self._api_key = os.getenv("OPENAI_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def get_session(self, node_id: str) -> Optional[RealtimeSession]:
        sid = self._node_to_session.get(node_id)
        return self._sessions.get(sid) if sid else None

    async def start_session(
        self,
        session_id: str,
        node_id: str,
        model: str = DEFAULT_MODEL,
    ) -> RealtimeSession:
        """Create and connect a new realtime session for a phone/glasses node."""
        system_prompt = self._build_system_prompt(session_id)
        tools = self._get_tools()

        rs = RealtimeSession(
            session_id=session_id,
            node_id=node_id,
            api_key=self._api_key,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            on_audio_delta=self._handle_audio_delta,
            on_transcript=self._handle_transcript,
            on_tool_call=self._handle_tool_call,
            on_speech_started=self._handle_speech_started,
            on_error=self._handle_error,
        )

        await rs.connect()
        self._sessions[session_id] = rs
        self._node_to_session[node_id] = session_id
        return rs

    async def stop_session(self, session_id: str):
        rs = self._sessions.pop(session_id, None)
        if rs:
            node_id = rs.node_id
            await rs.disconnect()
            self._node_to_session.pop(node_id, None)

    async def relay_audio(self, node_id: str, audio_b64: str):
        """Relay audio from a phone node to its OpenAI Realtime session."""
        rs = self.get_session(node_id)
        if rs and rs.connected:
            await rs.send_audio(audio_b64)

    async def relay_text(self, node_id: str, text: str):
        """Send text into a node's realtime session."""
        rs = self.get_session(node_id)
        if rs and rs.connected:
            await rs.send_text(text)

    async def update_context(self, node_id: str, session_id: str):
        """Inject fresh perception context into the realtime session."""
        rs = self.get_session(node_id)
        if not rs or not rs.connected:
            return
        if self._perception:
            frame = self._perception.get_frame(session_id)
            ctx = frame.to_system_context()
            if ctx:
                await rs.inject_context(f"[Updated sensor/environment context]\n{ctx}")

    async def shutdown(self):
        for sid in list(self._sessions):
            await self.stop_session(sid)

    def _build_system_prompt(self, session_id: str) -> str:
        parts = [
            "You are THEORA, a personal AI assistant with access to the user's "
            "physical environment through smart glasses, phone sensors, and connected devices. "
            "You can see what the user sees, monitor their health, control smart home devices, "
            "search the web, manage notes, and more. Be concise in voice responses. "
            "When using tools, explain what you're doing briefly.",
        ]

        if self._perception:
            frame = self._perception.get_frame(session_id)
            ctx = frame.to_system_context()
            if ctx:
                parts.append(f"\n[Current Environment]\n{ctx}")

        if self._memory:
            mem_ctx = self._memory.build_context_for_llm(session_id, max_tokens_budget=500)
            if mem_ctx:
                parts.append(f"\n[Memory Context]\n{mem_ctx}")

        return "\n".join(parts)

    def _get_tools(self) -> list[dict]:
        if self._skill_registry:
            return self._skill_registry.get_all_tools()
        return []

    @staticmethod
    def _tool_feedback_text(tool_name: str) -> str:
        """Generate natural spoken feedback while a tool is executing."""
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
        """Send transcript-style progress feedback to active voice clients."""
        if not text:
            return
        rs = self._sessions.get(session_id)
        if not rs:
            return

        if rs.node_id.startswith("webclient_") and self._send_to_session:
            from models.protocol import TheoraMessage, TranscriptPayload

            msg = TheoraMessage(
                session_id=session_id,
                hop="brain",
                type="transcript",
                payload=TranscriptPayload(
                    text=text,
                    role="assistant",
                    is_partial=False,
                ).model_dump(),
            )
            await self._send_to_session(session_id, msg)
            return

        if self._send_to_node:
            await self._send_to_node(rs.node_id, {
                "type": "transcript",
                "payload": {"text": text, "role": "assistant", "is_partial": False},
            })

    async def _handle_audio_delta(self, session_id: str, audio_b64: str, is_done: bool):
        """Forward audio from OpenAI back to the connected client (web or daemon node)."""
        rs = self._sessions.get(session_id)
        if not rs:
            return

        payload = {
            "data_b64": audio_b64,
            "encoding": AUDIO_FORMAT,
            "sample_rate": SAMPLE_RATE,
            "is_final": is_done,
        }

        if rs.node_id.startswith("webclient_") and self._send_to_session:
            from models.protocol import TheoraMessage
            msg = TheoraMessage(
                session_id=session_id, hop="brain", type="audio_response",
                payload=payload,
            )
            await self._send_to_session(session_id, msg)
        elif self._send_to_node:
            await self._send_to_node(rs.node_id, {"type": "audio_response", "payload": payload})

    async def _handle_transcript(self, session_id: str, text: str, is_final: bool):
        """Store transcripts in memory and forward to both client sessions and daemon nodes."""
        if is_final and text and self._memory:
            if text.startswith("[user] "):
                self._memory.working_push(session_id, {
                    "role": "user", "text": text[7:], "source": "voice_realtime",
                })
            else:
                self._memory.working_push(session_id, {
                    "role": "assistant", "text": text[:300], "source": "voice_realtime",
                })

        if is_final and text:
            rs = self._sessions.get(session_id)

            if self._send_to_session:
                from models.protocol import TheoraMessage, TranscriptPayload
                msg = TheoraMessage(
                    session_id=session_id, hop="brain", type="transcript",
                    payload=TranscriptPayload(
                        text=text, is_partial=not is_final,
                    ).model_dump(),
                )
                await self._send_to_session(session_id, msg)

            if rs and not rs.node_id.startswith("webclient_") and self._send_to_node:
                role = "user" if text.startswith("[user] ") else "assistant"
                await self._send_to_node(rs.node_id, {
                    "type": "transcript",
                    "payload": {"text": text, "role": role, "is_partial": False},
                })

    async def _handle_tool_call(
        self, session_id: str, call_id: str, name: str, arguments: str,
    ) -> str:
        """Execute a tool call through the local skill executor."""
        if not self._skill_executor or not self._skill_registry:
            return json.dumps({"error": "No skill executor available"})

        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            args = {}

        parts = name.split("__", 1)
        if len(parts) != 2:
            return json.dumps({"error": f"Invalid tool name format: {name}"})

        skill_id, endpoint_id = parts
        skill = self._skill_registry.skills.get(skill_id)
        if not skill:
            return json.dumps({"error": f"Skill not found: {skill_id}"})

        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            return json.dumps({"error": f"Endpoint not found: {endpoint_id}"})

        logger.info(f"Realtime tool execution: {name} -> {args}")
        await self._send_tool_feedback(session_id, self._tool_feedback_text(name))
        result = await self._skill_executor.execute(name, args, skill, endpoint)

        if self._memory:
            self._memory.working_push(session_id, {
                "role": "tool", "tool": name, "result_summary": str(result.get("data", ""))[:200],
            })

        return json.dumps(result.get("data") or {"status": result.get("error", "done")})

    async def _handle_speech_started(self, session_id: str):
        """User started speaking — cancel current response and notify client."""
        rs = self._sessions.get(session_id)
        if not rs:
            return
        await rs.cancel_response()
        payload = {"action": "stop_playback"}
        if rs.node_id.startswith("webclient_") and self._send_to_session:
            from models.protocol import TheoraMessage

            msg = TheoraMessage(
                session_id=session_id,
                hop="brain",
                type="speech_started",
                payload=payload,
            )
            await self._send_to_session(session_id, msg)
            return

        if self._send_to_node:
            await self._send_to_node(rs.node_id, {
                "type": "speech_started",
                "payload": payload,
            })

    async def _handle_error(self, session_id: str, error: str):
        logger.error(f"Realtime error [{session_id}]: {error}")
