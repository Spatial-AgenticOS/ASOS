"""
THEORA Orchestrator — The Agentic Brain (v0.4.0)
==================================================
The core OS loop. Receives fused multimodal perception →
matches skills → calls LLM with tools → executes → generates UI →
logs execution → updates memory → responds with voice + visuals.

v0.4.0:
  - Self-learning agent (knowledge extraction, session summarization)
  - Execution-log-aware skill routing with penalty scores
  - Streaming LLM responses (token-by-token text + SDUI patches)
  - Gesture-aware context injection
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional, Callable, Awaitable, TYPE_CHECKING
from uuid import uuid4

from fastapi import WebSocket

from models.protocol import (
    TheoraMessage,
    TextResponsePayload,
    SDUIPayload,
    TTSChunkPayload,
    ExecuteCommandPayload,
    VisionRequestPayload,
)
from models.skill_manifest import SkillManifest
from skills.registry import SkillRegistry
from skills.executor import SkillExecutor
from agents.llm_provider import LLMProvider
from agents.genui_generator import GenUIGenerator
from perception.fusion import PerceptionEngine, PerceptionFrame

if TYPE_CHECKING:
    from api.server import VisionBuffer
    from memory.store import MemoryStore
    from perception.audio_pipeline import AudioPipeline
    from agents.learner import Learner
    from agents.multi_agent import MultiAgentOrchestrator

logger = logging.getLogger("theora.orchestrator")


# ─────────────────────────────────────────────
# Safety Classification
# ─────────────────────────────────────────────

class SafetyLevel:
    AUTO = "auto"          # Execute immediately
    CONFIRM = "confirm"    # Ask user confirmation via SDUI
    DENY = "deny"          # Block outright


class Orchestrator:
    """
    The core agentic loop — fully wired to perception, memory, and safety.
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        send_to_client: Callable[[str, TheoraMessage], Awaitable[None]],
        daemons: dict[str, WebSocket],
        memory: "MemoryStore" = None,
        vision_buffer: "VisionBuffer" = None,
        perception: PerceptionEngine = None,
        learner: "Learner" = None,
    ):
        self.skills = skill_registry
        self.send = send_to_client
        self.daemons = daemons
        self.memory = memory
        self.vision_buffer = vision_buffer
        self.perception = perception or PerceptionEngine()
        self.learner = learner

        # Components — use shared LLM if provided
        self.llm = None  # set via set_llm() from BrainState
        self.executor = SkillExecutor(daemons=daemons)
        self.genui = GenUIGenerator()
        self._mcp_client = None

        # State
        self.biometric_state: dict[str, dict] = {}
        self.conversation_history: dict[str, list[dict]] = {}
        self._pending_daemon_results: dict[str, asyncio.Future] = {}
        self._pending_frame_futures: dict[str, asyncio.Future] = {}
        self._daemon_session_map: dict[str, str] = {}
        self._pending_confirmations: dict[str, dict] = {}

        # Multi-agent
        self._multi_agent_enabled = os.environ.get("THEORA_MULTI_AGENT", "false").lower() in ("true", "1", "yes")
        self._multi_agent: Optional["MultiAgentOrchestrator"] = None

        # Vision config
        self._vision_enabled = os.environ.get("THEORA_VISION_ENABLED", "").lower() in ("true", "1", "yes")

        # Proactive loop config
        self._proactive_enabled = os.environ.get("THEORA_PROACTIVE", "").lower() in ("true", "1", "yes")
        self._last_proactive_check: dict[str, float] = {}
        self._proactive_cooldown = 60.0  # min seconds between proactive triggers per session

        # Streaming config
        self._streaming_enabled = os.environ.get("THEORA_STREAMING", "true").lower() in ("true", "1", "yes")
        try:
            self._max_iterations = max(1, min(int(os.environ.get("THEORA_MAX_ITERATIONS", "15")), 30))
        except ValueError:
            self._max_iterations = 15

        # Anti-loop guard (same tool + args repeated in a row)
        self._tool_repeat_state: dict[str, dict] = {}

        self.executor.load_vault_from_env()

    def set_llm(self, llm: LLMProvider):
        """Set the shared LLM provider — avoids duplicate connections."""
        self.llm = llm
        if self._multi_agent_enabled:
            self._init_multi_agent()

    def set_vault(self, vault):
        """Wire the BlindVault into the skill executor for secure key injection."""
        self.executor.set_blind_vault(vault)

    def set_mcp_client(self, mcp_client):
        """Wire the MCP client so its tools are available to the LLM."""
        self._mcp_client = mcp_client

    def _init_multi_agent(self):
        """Lazy-init the multi-agent orchestrator once LLM is available."""
        try:
            from agents.multi_agent import MultiAgentOrchestrator
            self._multi_agent = MultiAgentOrchestrator(
                llm=self.llm,
                skill_registry=self.skills,
                skill_executor=self.executor,
                memory=self.memory,
                perception=self.perception,
                send_to_client=self.send,
            )
            logger.info("Multi-agent orchestrator initialized with workers: %s", list(self._multi_agent._workers.keys()))
        except Exception as e:
            logger.warning(f"Multi-agent init failed, falling back to single-agent: {e}")
            self._multi_agent_enabled = False

    # ─────────────────────────────────────────────
    # Core Command Handler
    # ─────────────────────────────────────────────

    def update_biometric(self, session_id: str, biometric: dict):
        self.biometric_state[session_id] = biometric

    async def handle_command(self, session_id: str, text: str, context: Optional[dict] = None):
        """Process a user command through the full agentic pipeline."""
        logger.info(f"[{session_id[:8]}] Command: {text}")

        # Record in episodic memory
        if self.memory:
            self.memory.episode_save(
                session_id=session_id,
                event_type="user_command",
                summary=text[:200],
                detail=json.dumps(context or {}),
            )

        # Multi-agent path: route through specialist workers
        if self._multi_agent_enabled and self._multi_agent and self.llm and self.llm.available:
            source = (context or {}).get("source", "")
            if source != "proactive":
                try:
                    response_text = await self._multi_agent.run(session_id, text, context)
                    if response_text:
                        await self._try_send_sdui(session_id, response_text)
                        if self.memory:
                            self.memory.working_push(session_id, {"role": "assistant", "text": response_text[:300]})
                        if self.learner:
                            asyncio.ensure_future(self.learner.on_message(session_id, "user", text))
                        return
                except Exception as e:
                    logger.warning(f"Multi-agent failed, falling back to single-agent: {e}")

        # Step 1: Semantic Tool Routing
        relevant_skills = await self._route_prompt(text)
        tools = self.skills.get_tools_for_skills(relevant_skills)

        # Merge MCP tools so the LLM can call external MCP servers
        if self._mcp_client:
            mcp_tools = self._mcp_client.to_llm_tool_definitions()
            if mcp_tools:
                tools = (tools or []) + mcp_tools

        if relevant_skills:
            logger.info(f"  Matched: {[s.brand.name for s in relevant_skills]}")

        # Direct mode (no LLM)
        if not self.llm.available:
            await self._direct_execute(session_id, text, relevant_skills)
            return

        # Full Agentic Mode
        perception_frame = self.perception.get_frame(session_id)
        system_prompt = self._build_system_prompt(perception_frame, relevant_skills, session_id)

        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []

        user_content = perception_frame.to_llm_user_content(text)
        user_message = {"role": "user", "content": user_content}
        self.conversation_history[session_id].append(user_message)

        history = self._compact_context(self.conversation_history[session_id].copy())

        max_iterations = self._max_iterations
        for _ in range(max_iterations):
            messages = [
                {"role": "system", "content": system_prompt},
                *history,
            ]

            try:
                response = await self.llm.chat(messages=messages, tools=tools if tools else None)
                text_content, tool_calls = self.llm.extract_response(response)

                assistant_msg = {"role": "assistant"}
                if text_content:
                    assistant_msg["content"] = text_content

                if "choices" in response and response["choices"]:
                    raw_msg = response["choices"][0].get("message", {})
                    if raw_msg.get("tool_calls"):
                        assistant_msg["tool_calls"] = raw_msg["tool_calls"]

                history.append(assistant_msg)

            except Exception as e:
                logger.error(f"LLM failed: {e}")
                await self._direct_execute(session_id, text, relevant_skills)
                return

            if tool_calls:
                for tc in tool_calls:
                    t_start = time.time()
                    result_data = await self._execute_tool_call_for_llm(session_id, tc, relevant_skills)
                    latency_ms = (time.time() - t_start) * 1000

                    # Log execution
                    if self.memory:
                        parts = tc["name"].split("__", 1)
                        skill_id = parts[0] if len(parts) == 2 else tc["name"]
                        endpoint_id = parts[1] if len(parts) == 2 else ""
                        self.memory.log_execution(
                            session_id=session_id,
                            skill_id=skill_id,
                            endpoint_id=endpoint_id,
                            args=tc.get("args", {}),
                            result_status="success" if result_data.get("success") or result_data.get("status") == "command_sent_to_hardware_daemon" else "failure",
                            result_summary=json.dumps(result_data)[:300],
                            latency_ms=latency_ms,
                        )

                    history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "content": json.dumps(result_data, default=str)[:2000]
                    })
                    anti_loop_guidance = result_data.get("_anti_loop_guidance")
                    if anti_loop_guidance:
                        history.append({"role": "system", "content": anti_loop_guidance})
            elif text_content:
                if self.memory:
                    self.memory.working_push(session_id, {"role": "assistant", "text": text_content[:300]})

                await self._send_text(session_id, text_content)
                break
            else:
                break

        self.conversation_history[session_id] = history[-20:]

        # Self-learning: notify learner of new messages
        if self.learner:
            asyncio.ensure_future(self.learner.on_message(session_id, "user", text))

    async def handle_command_stream(self, session_id: str, text: str, context: Optional[dict] = None):
        """
        Streaming variant of handle_command. Sends text deltas in real-time
        so the client gets token-by-token output.
        Falls back to non-streaming if LLM doesn't support it.
        """
        if not self._streaming_enabled or not self.llm.available:
            await self.handle_command(session_id, text, context)
            return

        if self.memory:
            self.memory.episode_save(
                session_id=session_id, event_type="user_command",
                summary=text[:200], detail=json.dumps(context or {}),
            )

        relevant_skills = await self._route_prompt(text)
        tools = self.skills.get_tools_for_skills(relevant_skills)

        if self._mcp_client:
            mcp_tools = self._mcp_client.to_llm_tool_definitions()
            if mcp_tools:
                tools = (tools or []) + mcp_tools

        perception_frame = self.perception.get_frame(session_id)
        system_prompt = self._build_system_prompt(perception_frame, relevant_skills, session_id)

        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []

        user_content = perception_frame.to_llm_user_content(text)
        self.conversation_history[session_id].append({"role": "user", "content": user_content})
        history = self._compact_context(self.conversation_history[session_id].copy())
        from models.protocol import StreamDeltaPayload

        got_final_text = False
        for _ in range(self._max_iterations):
            messages = [{"role": "system", "content": system_prompt}, *history]
            stream_id = str(uuid4())[:8]
            accumulated_text = ""
            streamed_text = False
            tool_calls_received = []

            try:
                async for delta in self.llm.chat_stream(messages=messages, tools=tools if tools else None):
                    if delta["type"] == "text_delta":
                        piece = delta.get("content", "")
                        if not piece:
                            continue
                        streamed_text = True
                        accumulated_text += piece
                        await self.send(session_id, TheoraMessage(
                            session_id=session_id, hop="brain", type="stream_delta",
                            payload=StreamDeltaPayload(
                                delta=piece, stream_id=stream_id, is_final=False,
                            ).model_dump(),
                        ))
                    elif delta["type"] == "tool_call_delta":
                        tc = delta.get("tool_call") or {}
                        if tc:
                            tool_calls_received.append(tc)
                    elif delta["type"] == "done":
                        if streamed_text:
                            await self.send(session_id, TheoraMessage(
                                session_id=session_id, hop="brain", type="stream_delta",
                                payload=StreamDeltaPayload(
                                    delta="", stream_id=stream_id, is_final=True,
                                ).model_dump(),
                            ))
                    elif delta["type"] == "error":
                        await self._send_text(session_id, f"Stream error: {delta.get('content', 'unknown')}")
                        return
            except Exception as e:
                logger.error(f"Streaming failed, falling back: {e}")
                await self.handle_command(session_id, text, context)
                return

            normalized_tool_calls = [
                tc for tc in tool_calls_received
                if isinstance(tc, dict) and tc.get("name")
            ]

            if accumulated_text or normalized_tool_calls:
                assistant_msg = {"role": "assistant"}
                if accumulated_text:
                    assistant_msg["content"] = accumulated_text
                if normalized_tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.get("id", str(uuid4())[:8]),
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("args", {})),
                            },
                        }
                        for tc in normalized_tool_calls
                    ]
                history.append(assistant_msg)

            if normalized_tool_calls:
                for tc in normalized_tool_calls:
                    t_start = time.time()
                    result_data = await self._execute_tool_call_for_llm(session_id, tc, relevant_skills)
                    latency_ms = (time.time() - t_start) * 1000
                    if self.memory:
                        parts = tc["name"].split("__", 1)
                        skill_id = parts[0] if len(parts) == 2 else tc["name"]
                        endpoint_id = parts[1] if len(parts) == 2 else ""
                        self.memory.log_execution(
                            session_id=session_id, skill_id=skill_id,
                            endpoint_id=endpoint_id, args=tc.get("args", {}),
                            result_status="success" if result_data.get("success") or result_data.get("status") == "command_sent_to_hardware_daemon" else "failure",
                            result_summary=json.dumps(result_data)[:300],
                            latency_ms=latency_ms,
                        )
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", str(uuid4())[:8]),
                        "name": tc["name"],
                        "content": json.dumps(result_data, default=str)[:2000],
                    })
                    anti_loop_guidance = result_data.get("_anti_loop_guidance")
                    if anti_loop_guidance:
                        history.append({"role": "system", "content": anti_loop_guidance})

                    # GenUI: generate rich UI for tool results when applicable
                    await self._try_genui_for_result(session_id, tc, result_data)
                continue

            if accumulated_text:
                got_final_text = True
                if self.memory:
                    self.memory.working_push(session_id, {"role": "assistant", "text": accumulated_text[:300]})
                break

            break

        if not got_final_text:
            await self._send_text(session_id, "I processed your request but have no text response.")

        self.conversation_history[session_id] = history[-20:]
        if self.learner:
            asyncio.ensure_future(self.learner.on_message(session_id, "user", text))

    # ─────────────────────────────────────────────
    # Proactive Agent Loop
    # ─────────────────────────────────────────────

    async def check_proactive_triggers(self, session_id: str):
        """
        Called periodically. Examines context changes and decides whether
        to proactively act without user prompt.

        Triggers:
          - Health anomaly (HR > 150 sustained, SpO2 < 90)
          - Battery critical (< 10%)
          - Context-inferred actions (e.g., calendar + GPS = late for meeting)
        """
        if not self._proactive_enabled or not self.llm.available:
            return

        now = time.time()
        last = self._last_proactive_check.get(session_id, 0)
        if now - last < self._proactive_cooldown:
            return
        self._last_proactive_check[session_id] = now

        frame = self.perception.get_frame(session_id)
        alerts = []

        if frame.heart_rate > 150:
            alerts.append(f"HEALTH ALERT: User heart rate is {frame.heart_rate} BPM — critically elevated.")
        if frame.spo2_pct and frame.spo2_pct < 90:
            alerts.append(f"HEALTH ALERT: SpO2 is {frame.spo2_pct}% — dangerously low.")
        if frame.battery_pct < 10:
            alerts.append(f"DEVICE: Battery critically low at {frame.battery_pct}%.")

        if not alerts:
            return

        alert_text = " ".join(alerts)
        logger.info(f"[{session_id[:8]}] Proactive trigger: {alert_text}")

        if self.memory:
            self.memory.episode_save(
                session_id=session_id,
                event_type="proactive_alert",
                summary=alert_text,
                importance=0.9,
            )

        # Generate a proactive response
        await self.handle_command(
            session_id=session_id,
            text=f"[SYSTEM PROACTIVE ALERT] {alert_text} Take appropriate action and notify the user.",
            context={"source": "proactive", "alerts": alerts},
        )

    async def on_session_disconnect(self, session_id: str):
        """Called when a client disconnects. Summarize and learn."""
        if self.learner:
            await self.learner.extract_knowledge(session_id)
            await self.learner.summarize_session(session_id)
        self.conversation_history.pop(session_id, None)
        self._last_proactive_check.pop(session_id, None)
        self._tool_repeat_state.pop(session_id, None)

    # ─────────────────────────────────────────────
    # Skill Routing
    # ─────────────────────────────────────────────

    async def _route_prompt(self, text: str) -> list[SkillManifest]:
        if not self.skills.skills:
            return []

        if not self.llm.available or len(self.skills.skills) <= 5:
            results = self.skills.find_skills_for_query(text, top_k=5)
            return self._apply_routing_penalties(results)

        prompt = "You are a Semantic Tool Router. Select up to 5 relevant tool IDs for the user's query.\n"
        prompt += "Available Tools:\n"
        for skill_id, skill in self.skills.skills.items():
            prompt += f"- {skill_id}: {skill.description}\n"

        prompt += f"\nUser Query: {text}\n"
        prompt += "\nOutput ONLY a JSON list of strings (tool IDs). [] if none match. No markdown."

        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}], tools=None)
            text_content, _ = self.llm.extract_response(response)

            cleaned = text_content.strip()
            if cleaned.startswith("```json"): cleaned = cleaned[7:-3].strip()
            elif cleaned.startswith("```"): cleaned = cleaned[3:-3].strip()

            skill_ids = json.loads(cleaned)

            relevant = []
            for sid in skill_ids:
                if isinstance(sid, str) and sid in self.skills.skills:
                    relevant.append(self.skills.skills[sid])
            results = relevant[:5] if relevant else self.skills.find_skills_for_query(text, top_k=5)
            return self._apply_routing_penalties(results)
        except Exception as e:
            logger.warning(f"RoutePrompt failed, falling back to heuristic: {e}")
            results = self.skills.find_skills_for_query(text, top_k=5)
            return self._apply_routing_penalties(results)

    def _apply_routing_penalties(self, skills: list[SkillManifest]) -> list[SkillManifest]:
        """
        Re-rank skills based on execution log reliability.
        Skills with poor track records get demoted.
        """
        if not self.learner or not skills:
            return skills

        penalties = self.learner.get_routing_penalties()
        if not penalties:
            return skills

        penalized = []
        for skill in skills:
            penalty = penalties.get(skill.skill_id, 1.0)
            if penalty < 0.2:
                logger.info(f"Routing penalty: skipping {skill.skill_id} (penalty={penalty})")
                continue
            penalized.append(skill)

        return penalized if penalized else skills[:1]

    # ─────────────────────────────────────────────
    # Context Management
    # ─────────────────────────────────────────────

    def _compact_context(self, history: list[dict]) -> list[dict]:
        max_messages = 15
        if len(history) <= max_messages:
            return history
        logger.info(f"Compacting context window from {len(history)} to {max_messages}")
        return history[-max_messages:]

    # ─────────────────────────────────────────────
    # Safety: Graduated Permission System
    # ─────────────────────────────────────────────

    def _classify_safety(self, tool_name: str, args: dict) -> str:
        """
        Graduated safety classification:
          AUTO    — safe, execute immediately (reads, searches, notes)
          CONFIRM — potentially impactful, ask user (send message, order, schedule)
          DENY    — dangerous, block outright (format disk, delete all, unsafe robot speeds)
        """
        name_lower = tool_name.lower()

        # DENY: dangerous hardware with unsafe parameters
        deny_actions = ["format", "erase_all", "factory_reset", "self_destruct"]
        if any(d in name_lower for d in deny_actions):
            return SafetyLevel.DENY
        if ("robot_move" in name_lower or "actuator" in name_lower) and args.get("speed", 0) > 80:
            return SafetyLevel.DENY

        # AUTO: reads, searches, queries, notes, status checks
        auto_patterns = [
            "search", "query", "get", "list", "current", "now_playing",
            "forecast", "status", "read", "notes_memory", "web_search",
        ]
        if any(p in name_lower for p in auto_patterns):
            return SafetyLevel.AUTO

        # CONFIRM: anything that writes, sends, modifies, or controls hardware
        confirm_patterns = [
            "send", "post", "create", "delete", "update", "move", "grip",
            "play", "pause", "skip", "volume", "lock", "message", "order",
            "schedule", "daemon", "execute", "robot", "actuator", "motor",
        ]
        if any(p in name_lower for p in confirm_patterns):
            return SafetyLevel.CONFIRM

        return SafetyLevel.AUTO

    def _enforce_safety(self, tool_name: str, args: dict) -> Optional[dict]:
        """
        Returns a denial dict if the action should be blocked.
        Returns None if the action is allowed to proceed.
        """
        level = self._classify_safety(tool_name, args)

        if level == SafetyLevel.DENY:
            return {
                "status": "PermissionOutcome::Deny",
                "error": "Safety Protocol: Action Blocked",
                "note": f"Action '{tool_name}' with args {args} is classified as dangerous and has been blocked.",
                "safety_level": "deny",
            }

        if level == SafetyLevel.CONFIRM:
            # For now, auto-approve CONFIRM level but log a warning.
            # In production, this would send an SDUI confirmation dialog and await response.
            logger.info(f"Safety CONFIRM: {tool_name} — auto-approved (production would ask user)")
            return None

        return None  # AUTO — proceed

    # ─────────────────────────────────────────────
    # Vision
    # ─────────────────────────────────────────────

    async def request_frame(self, node_id: str, resolution: str = "640x480",
                            quality: int = 80, reason: str = "", timeout: float = 10.0) -> Optional[dict]:
        ws = self.daemons.get(node_id)
        if not ws:
            logger.warning(f"Cannot request frame: node {node_id} not connected")
            return None

        msg_id = str(uuid4())[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_frame_futures[msg_id] = future

        request_msg = TheoraMessage(
            msg_id=msg_id, hop="brain", type="vision_request",
            payload=VisionRequestPayload(resolution=resolution, quality=quality, reason=reason).model_dump(),
        )
        await ws.send_json(request_msg.model_dump())

        try:
            frame = await asyncio.wait_for(future, timeout=timeout)
            return frame
        except asyncio.TimeoutError:
            self._pending_frame_futures.pop(msg_id, None)
            return None

    def resolve_pending_frame(self, msg_id: str, frame_payload: dict):
        future = self._pending_frame_futures.pop(msg_id, None)
        if future and not future.done():
            future.set_result(frame_payload)

    # ─────────────────────────────────────────────
    # Tool Execution
    # ─────────────────────────────────────────────

    @staticmethod
    def _tool_signature(tool_name: str, args: dict) -> str:
        """Create a stable signature for anti-loop detection."""
        try:
            args_key = json.dumps(args or {}, sort_keys=True, default=str)
        except Exception:
            args_key = str(args)
        return f"{tool_name}::{args_key}"

    def _register_tool_attempt(self, session_id: str, tool_name: str, args: dict) -> int:
        """Track consecutive identical tool calls and return current streak."""
        signature = self._tool_signature(tool_name, args)
        state = self._tool_repeat_state.get(session_id)
        if state and state.get("signature") == signature:
            count = int(state.get("count", 0)) + 1
        else:
            count = 1
        self._tool_repeat_state[session_id] = {
            "signature": signature,
            "count": count,
            "tool_name": tool_name,
        }
        return count

    @staticmethod
    def _anti_loop_guidance(tool_name: str, streak: int) -> str:
        return (
            f"System guard: You have called '{tool_name}' with the same arguments "
            f"{streak} times in a row. Do not repeat this action again. "
            "Try a different tool, adjust parameters, or explain the blocker to the user."
        )

    async def _spawn_subagents_for_task(self, session_id: str, args: dict) -> dict:
        """Run multiple sub-tasks in parallel with isolated subagent contexts."""
        tasks_arg = args.get("tasks")
        if isinstance(tasks_arg, str):
            tasks = [tasks_arg]
        elif isinstance(tasks_arg, list):
            tasks = [str(t).strip() for t in tasks_arg if str(t).strip()]
        else:
            single = str(args.get("task", "")).strip()
            tasks = [single] if single else []

        if not tasks:
            return {
                "success": False,
                "status_code": 400,
                "data": None,
                "error": "Provide 'tasks' (array) or 'task' (string) for subagent execution.",
            }
        if not self.llm or not self.llm.available:
            return {
                "success": False,
                "status_code": 503,
                "data": None,
                "error": "LLM unavailable; cannot spawn subagents.",
            }

        goal = str(args.get("goal", "") or "").strip()
        try:
            max_workers = int(args.get("max_workers", min(3, len(tasks))) or 3)
        except Exception:
            max_workers = min(3, len(tasks))
        try:
            max_iterations = int(args.get("max_iterations", min(self._max_iterations, 8)) or 4)
        except Exception:
            max_iterations = min(self._max_iterations, 8)
        max_workers = max(1, min(max_workers, 6))
        max_iterations = max(1, min(max_iterations, 12))
        sem = asyncio.Semaphore(max_workers)

        async def _run_one(i: int, task_text: str) -> dict:
            scoped_task = task_text if not goal else f"Goal: {goal}\nTask: {task_text}"
            async with sem:
                started = time.time()
                try:
                    result = await self._run_subagent_task(
                        parent_session_id=session_id,
                        task_text=scoped_task,
                        max_iterations=max_iterations,
                        ordinal=i,
                    )
                    result["elapsed_ms"] = round((time.time() - started) * 1000, 2)
                    return result
                except Exception as e:
                    return {
                        "task_index": i,
                        "task": task_text,
                        "success": False,
                        "result": "",
                        "error": str(e),
                        "iterations": 0,
                        "tool_calls_executed": 0,
                        "elapsed_ms": round((time.time() - started) * 1000, 2),
                    }

        results = await asyncio.gather(*[_run_one(i, t) for i, t in enumerate(tasks, 1)])
        success_count = sum(1 for r in results if r.get("success"))

        return {
            "success": True,
            "status_code": 200,
            "data": {
                "goal": goal or None,
                "task_count": len(tasks),
                "max_workers": max_workers,
                "max_iterations": max_iterations,
                "success_count": success_count,
                "results": results,
            },
            "error": None,
        }

    async def _run_subagent_task(
        self,
        *,
        parent_session_id: str,
        task_text: str,
        max_iterations: int,
        ordinal: int,
    ) -> dict:
        """Execute one subagent task with isolated history and full tool access."""
        relevant_skills = await self._route_prompt(task_text)
        tools = self.skills.get_tools_for_skills(relevant_skills)
        if self._mcp_client:
            mcp_tools = self._mcp_client.to_llm_tool_definitions()
            if mcp_tools:
                tools = (tools or []) + mcp_tools

        frame = self.perception.get_frame(parent_session_id)
        system_prompt = self._build_system_prompt(frame, relevant_skills, parent_session_id)
        history: list[dict] = [{"role": "user", "content": task_text}]
        sub_session_id = f"{parent_session_id}:sub:{ordinal}:{str(uuid4())[:6]}"
        final_text = ""
        tool_calls_executed = 0
        iterations_used = 0

        for i in range(max_iterations):
            iterations_used = i + 1
            response = await self.llm.chat(
                messages=[{"role": "system", "content": system_prompt}, *history],
                tools=tools if tools else None,
            )
            text_content, tool_calls = self.llm.extract_response(response)

            assistant_msg = {"role": "assistant"}
            if text_content:
                assistant_msg["content"] = text_content
            if "choices" in response and response["choices"]:
                raw_msg = response["choices"][0].get("message", {})
                if raw_msg.get("tool_calls"):
                    assistant_msg["tool_calls"] = raw_msg["tool_calls"]
            if len(assistant_msg) > 1:
                history.append(assistant_msg)

            if tool_calls:
                for tc in tool_calls:
                    if tc.get("name", "").startswith("subagent__"):
                        result_data = {
                            "success": False,
                            "error": "Nested subagent spawning is blocked to prevent recursion loops.",
                        }
                    else:
                        result_data = await self._execute_tool_call_for_llm(
                            sub_session_id,
                            tc,
                            relevant_skills,
                        )
                    tool_calls_executed += 1
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", str(uuid4())[:8]),
                        "name": tc.get("name", ""),
                        "content": json.dumps(result_data, default=str)[:2000],
                    })
                continue

            if text_content:
                final_text = text_content
            break

        if not final_text:
            final_text = "No final answer produced by subagent."

        return {
            "task_index": ordinal,
            "task": task_text,
            "success": True,
            "result": final_text,
            "error": None,
            "iterations": iterations_used,
            "tool_calls_executed": tool_calls_executed,
        }

    async def _execute_tool_call_for_llm(self, session_id: str, tool_call: dict, available_skills: list[SkillManifest]) -> dict:
        tool_name = tool_call["name"]
        args = tool_call["args"]
        logger.info(f"  LLM Tool call: {tool_name}({json.dumps(args)[:200]})")

        # Route MCP tool calls through the MCP client
        if tool_name.startswith("mcp_") and self._mcp_client:
            logger.info(f"  MCP tool: {tool_name}")
            result = await self._mcp_client.call_tool(tool_name, args)
            content = result.get("content", [])
            if content and isinstance(content, list):
                return {"data": "\n".join(c.get("text", str(c)) for c in content)}
            return result

        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            return {"error": f"Invalid tool reference: {tool_name}"}

        skill_id, endpoint_id = parts
        if skill_id == "subagent" and endpoint_id == "spawn_subagent":
            return await self._spawn_subagents_for_task(session_id, args)

        logger.info(f"  Tool executing: {skill_id}__{endpoint_id}")

        streak = self._register_tool_attempt(session_id, tool_name, args)
        anti_loop_note = None
        if streak >= 5:
            message = (
                f"Anti-loop guard: blocked repeated call '{tool_name}' with identical "
                f"arguments ({streak}x in a row)."
            )
            logger.warning(message)
            return {
                "success": False,
                "error": message,
                "anti_loop_blocked": True,
                "anti_loop_streak": streak,
            }
        if streak >= 3:
            anti_loop_note = self._anti_loop_guidance(tool_name, streak)
            logger.warning(anti_loop_note)

        # Safety check
        denial = self._enforce_safety(tool_name, args)
        if denial:
            logger.warning(f"Safety denial: {tool_name}")
            return denial

        if skill_id.startswith("daemon_"):
            await self._execute_daemon_command(session_id, skill_id, endpoint_id, args)
            return {"status": "command_sent_to_hardware_daemon", "note": "Command is executing asynchronously on the device."}

        skill = self.skills.skills.get(skill_id)
        if not skill:
            return {"error": f"Skill not found: {skill_id}"}

        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            return {"error": f"Endpoint not found: {endpoint_id}"}

        result = await self.executor.execute(
            tool_name=tool_name, args=args, skill=skill, endpoint=endpoint,
        )

        if not result.get("success"):
            logger.warning(f"PostToolUse: Action failed — {result.get('error')}")
        elif result.get("data"):
            try:
                sdui = self.genui.generate(
                    data=result["data"],
                    skill_brand=skill.brand.model_dump(),
                    ui_hint=endpoint.ui_hint,
                    endpoint_id=endpoint_id,
                )
                await self.send(session_id, TheoraMessage(
                    session_id=session_id, hop="brain", type="sdui",
                    payload=SDUIPayload(root=sdui).model_dump(),
                ))
            except Exception as e:
                logger.debug(f"GenUI generation skipped for {tool_name}: {e}")

        if anti_loop_note:
            result = dict(result)
            result["_anti_loop_guidance"] = anti_loop_note
            result["_anti_loop_streak"] = streak

        return result

    async def _execute_tool_call(self, session_id: str, tool_call: dict, available_skills: list[SkillManifest]):
        tool_name = tool_call["name"]
        args = tool_call["args"]
        logger.info(f"  Tool call: {tool_name}({json.dumps(args)[:200]})")

        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            await self._send_text(session_id, f"Invalid tool reference: {tool_name}")
            return

        skill_id, endpoint_id = parts

        if skill_id.startswith("daemon_"):
            await self._execute_daemon_command(session_id, skill_id, endpoint_id, args)
            return

        skill = self.skills.skills.get(skill_id)
        if not skill:
            await self._send_text(session_id, f"Skill not found: {skill_id}")
            return

        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            await self._send_text(session_id, f"Endpoint not found: {endpoint_id}")
            return

        result = await self.executor.execute(
            tool_name=tool_name, args=args, skill=skill, endpoint=endpoint,
        )

        if result["success"] and result["data"]:
            sdui = self.genui.generate(
                data=result["data"],
                skill_brand=skill.brand.model_dump(),
                ui_hint=endpoint.ui_hint,
                endpoint_id=endpoint_id,
            )
            await self._send_text(session_id, f"Here's the result from {skill.brand.name}:")
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
        else:
            error = result.get("error", "Unknown error")
            await self._send_text(session_id, f"Failed to call {skill.brand.name}: {error}")

    async def _execute_daemon_command(self, session_id: str, node_id: str, action: str, args: dict):
        actual_node_id = node_id.replace("daemon_", "")

        if actual_node_id not in self.daemons:
            available = list(self.daemons.keys()) if self.daemons else ["none"]
            await self._send_text(session_id, f"Node '{actual_node_id}' not connected. Available: {available}")
            return

        ws = self.daemons[actual_node_id]
        request_id = str(uuid4())[:8]
        daemon_msg = {
            "type": "command",
            "request_id": request_id,
            "command": action,
            "args": args,
        }

        self._daemon_session_map[request_id] = session_id
        await ws.send_json(daemon_msg)
        await self._send_text(session_id, f"Command sent to node '{actual_node_id}'...")

    # ─────────────────────────────────────────────
    # Direct Execution (no LLM)
    # ─────────────────────────────────────────────

    async def _direct_execute(self, session_id: str, text: str, skills: list[SkillManifest]):
        if not skills:
            all_skills = list(self.skills.skills.values())
            sdui = {
                "type": "VStack", "spacing": 16, "padding": 20,
                "children": [
                    {"type": "Text", "value": "THEORA Brain", "style": "headline", "color": "#6c5ce7"},
                    {"type": "Text", "value": f'No matching skill for: "{text}"', "style": "body"},
                    {"type": "Divider"},
                    {"type": "Text", "value": "Available Skills:", "style": "subtitle"},
                    *[
                        {"type": "Card", "corner_radius": 12, "children": [
                            {"type": "Text", "value": s.brand.name, "style": "subtitle", "color": s.brand.primary_color},
                            {"type": "Text", "value": s.description, "style": "caption"},
                            {"type": "Text", "value": f"Try: \"{s.trigger_phrases[0]}\"" if s.trigger_phrases else "", "style": "caption"},
                        ]}
                        for s in all_skills
                    ],
                    {"type": "Divider"},
                    {"type": "Badge", "label": "Direct Mode — Set OPENAI_API_KEY for full agent reasoning", "color": "#fdcb6e", "text_color": "#2d3436"},
                ],
            }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        skill = skills[0]
        endpoint = skill.endpoints[0] if skill.endpoints else None
        if not endpoint:
            await self._send_text(session_id, f"Skill '{skill.brand.name}' has no endpoints.")
            return

        if skill.skill_id == "notes_memory":
            await self._handle_memory_direct(session_id, text, skill)
            return

        if skill.requires_daemon:
            await self._handle_daemon_direct(session_id, text, skill)
            return

        await self._send_text(session_id, f"Direct mode: calling {skill.brand.name}...")
        args = self._extract_args_from_text(text, endpoint)

        result = await self.executor.execute(
            tool_name=f"{skill.skill_id}__{endpoint.id}", args=args, skill=skill, endpoint=endpoint,
        )

        if result["success"] and result["data"]:
            sdui = self.genui.generate(
                data=result["data"], skill_brand=skill.brand.model_dump(),
                ui_hint=endpoint.ui_hint, endpoint_id=endpoint.id,
            )
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
        else:
            sdui = {
                "type": "VStack", "spacing": 16, "padding": 20,
                "children": [
                    {"type": "HStack", "spacing": 10, "children": [
                        {"type": "Icon", "name": "sparkles", "size": 22, "color": skill.brand.primary_color},
                        {"type": "Text", "value": skill.brand.name, "style": "headline", "color": skill.brand.primary_color},
                    ]},
                    {"type": "Divider"},
                    {"type": "Text", "value": f"Endpoint: {endpoint.method} {endpoint.url}", "style": "caption"},
                    {"type": "Text", "value": endpoint.description, "style": "body"},
                    {"type": "Divider"},
                    {"type": "Text", "value": f"Error: {result.get('error', 'Unknown')}", "style": "body", "color": "#e17055"},
                    {"type": "Text", "value": f"Set THEORA_KEY_{skill.skill_id} env var to provide the API key", "style": "caption"},
                    *[
                        {"type": "Button", "action_id": f"call_{skill.skill_id}__{ep.id}", "label": ep.id.replace('_', ' ').title(), "style": "secondary"}
                        for ep in skill.endpoints
                    ],
                ],
            }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))

    # ─────────────────────────────────────────────
    # Memory Direct Mode
    # ─────────────────────────────────────────────

    async def _handle_memory_direct(self, session_id: str, text: str, skill):
        if not self.memory:
            await self._send_text(session_id, "Memory system not available.")
            return

        text_lower = text.lower()

        list_patterns = ["my notes", "recent notes", "recent memories", "list notes", "show notes", "show memories", "all notes"]
        search_patterns = ["recall", "what did i", "what was", "find ", "search notes", "search memories"]
        save_patterns = ["remember", "save", "write down", "don't forget", "store", "note that", "note this"]
        knowledge_patterns = ["i am ", "my name is ", "i live ", "i work ", "i like ", "my favorite"]

        # Knowledge extraction
        if any(p in text_lower for p in knowledge_patterns):
            self.memory.knowledge_store(
                subject="user", predicate="stated", obj=text[:300], source="conversation",
            )
            sdui = {
                "type": "VStack", "spacing": 16, "padding": 20,
                "children": [
                    {"type": "HStack", "spacing": 10, "children": [
                        {"type": "Icon", "name": "brain", "size": 28, "color": "#a29bfe"},
                        {"type": "Text", "value": "Learned", "style": "headline", "color": "#a29bfe"},
                    ]},
                    {"type": "Text", "value": f"I'll remember: {text[:200]}", "style": "body"},
                ],
            }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        if any(p in text_lower for p in list_patterns):
            results = self.memory.list_recent(limit=5)
            if results:
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "note.text", "size": 22, "color": "#FDCB6E"},
                            {"type": "Text", "value": f"Recent Notes ({len(results)})", "style": "headline", "color": "#FDCB6E"},
                        ]},
                        {"type": "Divider"},
                        *[
                            {"type": "Card", "corner_radius": 10, "children": [
                                {"type": "Text", "value": r["content"], "style": "body"},
                                {"type": "Badge", "label": f"ID: {r['id']}", "color": "#636e72"},
                            ]}
                            for r in results
                        ],
                    ],
                }
            else:
                sdui = {
                    "type": "VStack", "spacing": 16, "padding": 20,
                    "children": [
                        {"type": "Text", "value": "No notes yet", "style": "headline", "color": "#FDCB6E"},
                        {"type": "Text", "value": "Say 'remember that...' to save your first note.", "style": "body"},
                    ],
                }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        elif any(p in text_lower for p in search_patterns):
            query = text
            for phrase in ["recall ", "what did i save about ", "search notes for ", "search memories for ", "find "]:
                if text_lower.startswith(phrase):
                    query = text[len(phrase):].strip()
                    break

            results = self.memory.search(query=query, limit=5)
            if results:
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "Text", "value": f"Found {len(results)} memories", "style": "headline", "color": "#FDCB6E"},
                        {"type": "Divider"},
                        *[
                            {"type": "Card", "corner_radius": 10, "children": [
                                {"type": "Text", "value": r["content"], "style": "body"},
                                {"type": "HStack", "spacing": 8, "children": [
                                    {"type": "Badge", "label": f"ID: {r['id']}", "color": "#636e72"},
                                    {"type": "Badge", "label": r["importance"], "color": "#6c5ce7"},
                                ]},
                            ]}
                            for r in results
                        ],
                    ],
                }
            else:
                sdui = {
                    "type": "VStack", "spacing": 16, "padding": 20,
                    "children": [
                        {"type": "Text", "value": f"No memories found for: \"{query}\"", "style": "body"},
                        {"type": "Text", "value": "Try saving something first.", "style": "caption"},
                    ],
                }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        elif any(p in text_lower for p in save_patterns):
            content = text
            for phrase in ["remember that ", "remember ", "save a note ", "save note ", "note that ", "note ", "write down ", "don't forget "]:
                if text_lower.startswith(phrase):
                    content = text[len(phrase):].strip()
                    break

            result = self.memory.save(content=content, source="voice")
            sdui = {
                "type": "VStack", "spacing": 16, "padding": 20,
                "children": [
                    {"type": "HStack", "spacing": 10, "children": [
                        {"type": "Icon", "name": "checkmark.circle.fill", "size": 28, "color": "#00b894"},
                        {"type": "Text", "value": "Saved to Memory", "style": "headline", "color": "#00b894"},
                    ]},
                    {"type": "Divider"},
                    {"type": "Card", "corner_radius": 12, "children": [
                        {"type": "Text", "value": result["content"], "style": "body"},
                        {"type": "HStack", "spacing": 8, "children": [
                            {"type": "Badge", "label": f"ID: {result['id']}", "color": "#636e72"},
                            {"type": "Badge", "label": result["importance"], "color": "#6c5ce7"},
                        ]},
                    ]},
                    {"type": "Text", "value": f"Total memories: {self.memory.count()}", "style": "caption"},
                ],
            }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        # Fallback
        results = self.memory.list_recent(limit=5)
        sdui = {
            "type": "VStack", "spacing": 12, "padding": 20,
            "children": [
                {"type": "HStack", "spacing": 10, "children": [
                    {"type": "Icon", "name": "note.text", "size": 22, "color": "#FDCB6E"},
                    {"type": "Text", "value": f"Recent Notes ({len(results)})", "style": "headline", "color": "#FDCB6E"},
                ]},
                {"type": "Divider"},
                *(
                    [
                        {"type": "Card", "corner_radius": 10, "children": [
                            {"type": "Text", "value": r["content"], "style": "body"},
                            {"type": "Badge", "label": f"ID: {r['id']}", "color": "#636e72"},
                        ]}
                        for r in results
                    ] if results else [
                        {"type": "Text", "value": "No notes yet. Say 'remember that...' to start.", "style": "body"},
                    ]
                ),
            ],
        }
        await self.send(session_id, TheoraMessage(
            session_id=session_id, hop="brain", type="sdui",
            payload=SDUIPayload(root=sdui).model_dump(),
        ))

    async def _handle_daemon_direct(self, session_id: str, text: str, skill):
        if not self.daemons:
            await self._send_text(session_id, "No daemon connected.")
            return

        node_id = list(self.daemons.keys())[0]
        text_lower = text.lower()

        executor = "shell"
        action = ""

        app_map = {
            "chrome": "Google Chrome", "safari": "Safari", "terminal": "Terminal",
            "vscode": "Visual Studio Code", "code": "Visual Studio Code",
            "spotify": "Spotify", "finder": "Finder", "notes": "Notes",
            "messages": "Messages", "slack": "Slack", "discord": "Discord",
            "firefox": "Firefox", "arc": "Arc", "iterm": "iTerm",
        }

        for keyword, app_name in app_map.items():
            if keyword in text_lower and ("open" in text_lower or "launch" in text_lower):
                executor = "applescript"
                action = f'tell application "{app_name}" to activate'
                break

        if not action:
            if "volume" in text_lower or "mute" in text_lower:
                if "mute" in text_lower:
                    action = "osascript -e 'set volume output muted true'"
                elif "up" in text_lower or "higher" in text_lower or "louder" in text_lower:
                    action = "osascript -e 'set volume output volume ((output volume of (get volume settings)) + 15)'"
                elif "down" in text_lower or "lower" in text_lower or "quieter" in text_lower:
                    action = "osascript -e 'set volume output volume ((output volume of (get volume settings)) - 15)'"
                else:
                    nums = re.findall(r'\d+', text)
                    vol = nums[0] if nums else "50"
                    action = f"osascript -e 'set volume output volume {vol}'"
            elif "lock" in text_lower:
                action = "pmset displaysleepnow"
            elif "screenshot" in text_lower or "screen" in text_lower:
                action = "screencapture -x /tmp/theora_screenshot.png && echo 'Screenshot saved'"
            elif "dark mode" in text_lower:
                executor = "applescript"
                action = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'
            elif "run" in text_lower:
                action = text_lower.replace("run ", "", 1).strip()

        if not action:
            await self._send_text(session_id, f"Matched Desktop Control but couldn't parse: '{text}'")
            return

        await self._send_text(session_id, f"Sending to daemon: [{executor}] {action[:80]}...")
        await self._execute_daemon_command(session_id, f"daemon_{node_id}", executor, {"command": action, "script": action})

    def _extract_args_from_text(self, text: str, endpoint) -> dict:
        args = {}
        stop_words = {"the", "in", "at", "for", "what", "is", "whats", "what's",
                       "weather", "how", "get", "show", "me", "my", "of", "a", "an",
                       "please", "can", "you", "tell", "about", "find", "search"}
        content_words = [w for w in text.split() if w.lower() not in stop_words]
        subject = " ".join(content_words) if content_words else text

        for param in endpoint.params:
            if param.default:
                args[param.name] = param.default
            if param.name in ("q", "query", "text", "search", "message"):
                args[param.name] = text
            elif param.name in ("city", "location", "place", "address"):
                args[param.name] = subject or text
            elif param.name == "lat" and "lon" in [p.name for p in endpoint.params]:
                pass  # skip — needs geocoding which direct mode can't do
        return args

    # ─────────────────────────────────────────────
    # UI Events & Daemon Results
    # ─────────────────────────────────────────────

    async def handle_ui_event(self, session_id: str, action_id: str, event: str, value=None):
        logger.info(f"[{session_id[:8]}] UI: {event} → {action_id} = {value}")

        if action_id.startswith("call_"):
            tool_ref = action_id[5:]
            await self._execute_tool_call(session_id, {"name": tool_ref, "args": {}}, [])
        elif action_id.startswith("confirm_"):
            confirmation_id = action_id[8:]
            pending = self._pending_confirmations.pop(confirmation_id, None)
            if pending:
                logger.info(f"User confirmed action: {confirmation_id}")
                # Re-execute the confirmed action
                await self._execute_tool_call(session_id, pending["tool_call"], pending.get("skills", []))
        else:
            await self.handle_command(
                session_id,
                f"The user interacted with '{action_id}' (event: {event}, value: {value}). What should happen next?",
            )

    async def handle_daemon_result(self, node_id: str, result: dict, session_id: str = None):
        request_id = result.get("request_id", "")
        success = result.get("success", False)
        data = result.get("data", {})
        output = data.get("output", "") if isinstance(data, dict) else str(data)
        error = data.get("error", "") if isinstance(data, dict) else ""
        # Fallback to legacy field names
        if not output:
            output = result.get("stdout", "")
        if not error:
            error = result.get("stderr", result.get("error", ""))
        status = "success" if success else result.get("status", "error")
        logger.info(f"Daemon {node_id} → {status}: {str(output)[:200]}")

        if not session_id:
            if request_id and request_id in self._daemon_session_map:
                session_id = self._daemon_session_map.pop(request_id)
            else:
                for req_id, sid in list(self._daemon_session_map.items()):
                    session_id = sid
                    del self._daemon_session_map[req_id]
                    break

        if session_id:
            if status == "success":
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "checkmark.circle.fill", "size": 24, "color": "#00b894"},
                            {"type": "Text", "value": "Command Executed", "style": "headline", "color": "#00b894"},
                        ]},
                        {"type": "Divider"},
                        {"type": "Text", "value": str(output)[:500] if output else "Done.", "style": "body"},
                    ],
                }
            elif status == "denied":
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "xmark.shield.fill", "size": 24, "color": "#e17055"},
                            {"type": "Text", "value": "Command Denied", "style": "headline", "color": "#e17055"},
                        ]},
                        {"type": "Divider"},
                        {"type": "Text", "value": error or "Blocked by security policy", "style": "body", "color": "#e17055"},
                    ],
                }
            else:
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "exclamationmark.triangle.fill", "size": 24, "color": "#fdcb6e"},
                            {"type": "Text", "value": "Command Error", "style": "headline", "color": "#fdcb6e"},
                        ]},
                        {"type": "Divider"},
                        {"type": "Text", "value": error or str(output) or "Unknown error", "style": "body"},
                    ],
                }

            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))

    # ─────────────────────────────────────────────
    # Response Helpers
    # ─────────────────────────────────────────────

    async def _send_text(self, session_id: str, text: str):
        await self.send(session_id, TheoraMessage(
            session_id=session_id, hop="brain", type="text_response",
            payload=TextResponsePayload(text=text).model_dump(),
        ))

    async def _try_send_sdui(self, session_id: str, text: str):
        """Try to parse text as SDUI JSON, fall back to plain text."""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:-3].strip()
            elif cleaned.startswith("```\n"):
                cleaned = cleaned[4:-3].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:-3].strip()
            sdui = json.loads(cleaned)
            if "type" in sdui:
                await self.send(session_id, TheoraMessage(
                    session_id=session_id, hop="brain", type="sdui",
                    payload=SDUIPayload(root=sdui).model_dump(),
                ))
                return
        except json.JSONDecodeError:
            pass
        await self._send_text(session_id, text)

    async def _try_genui_for_result(self, session_id: str, tool_call: dict, result_data: dict):
        """Generate and send SDUI for tool results when the data is rich enough."""
        try:
            from genui.generator import GenUIEngine
        except ImportError:
            return

        if not isinstance(result_data, dict):
            return

        # Only generate UI for data-rich results (not simple status messages)
        has_rich_data = any(k in result_data for k in (
            "lat", "latitude", "lon", "longitude", "image_url", "image_b64",
            "results", "chart_data", "data", "items", "markers",
        ))
        if not has_rich_data and len(result_data) < 3:
            return

        # Resolve GenUI engine from state (accessible via self._genui_engine or import)
        genui = getattr(self, '_genui_engine', None)
        if not genui:
            try:
                genui = GenUIEngine()
            except Exception:
                return

        parts = tool_call["name"].split("__", 1)
        skill_id = parts[0] if len(parts) == 2 else tool_call["name"]
        endpoint_id = parts[1] if len(parts) == 2 else ""
        skill = self.skills.skills.get(skill_id)
        brand = getattr(skill, "brand", None) or {}

        ui_hint = None
        if any(k in result_data for k in ("lat", "latitude", "longitude")):
            ui_hint = "map"
        elif "chart_data" in result_data:
            ui_hint = "chart"

        try:
            sdui = await genui.generate_for_data(
                data=result_data, skill_brand=brand,
                ui_hint=ui_hint, endpoint_id=endpoint_id,
            )
            if sdui and "type" in sdui:
                from models.protocol import SDUIPayload
                await self.send(session_id, TheoraMessage(
                    session_id=session_id, hop="brain", type="sdui",
                    payload=SDUIPayload(root=sdui).model_dump(),
                ))
        except Exception as e:
            logger.debug(f"GenUI generation for {tool_call['name']} skipped: {e}")

    # ─────────────────────────────────────────────
    # System Prompt Builder
    # ─────────────────────────────────────────────

    def _build_system_prompt(self, frame: PerceptionFrame, skills: list[SkillManifest], session_id: str = "") -> str:
        # Load custom identity if available
        identity = self._load_identity()

        prompt = identity + "\n\n"

        prompt += (
            "## How to respond\n"
            "- Respond in natural, conversational language. Be concise and helpful.\n"
            "- When the user asks a question, answer directly. No JSON, no UI markup.\n"
            "- Use tools when you need external data (weather, web search, device control, etc.).\n"
            "- After a tool call, summarize the result in plain language.\n"
            "- Be proactive — if you notice something relevant in sensor data or context, mention it.\n"
        )

        # Perception Context
        perception_context = frame.to_system_context()
        if perception_context and perception_context != "No sensor data available.":
            prompt += f"\n## Live Perception\n{perception_context}\n"

        # Memory Context
        if self.memory and session_id:
            memory_context = self.memory.build_context_for_llm(session_id, max_tokens_budget=800)
            if memory_context:
                prompt += f"\n## Memory\n{memory_context}\n"

        # Available skills
        if skills:
            skill_summary = ", ".join(s.brand.name for s in skills)
            prompt += f"\nRelevant skills: {skill_summary}\n"

        # Connected nodes
        if frame.connected_nodes:
            prompt += f"\nConnected devices: {frame.connected_nodes}\n"

        return prompt

    def _load_identity(self) -> str:
        """Load agent identity from ~/.theora/identity.yaml or use defaults."""
        identity_paths = [
            Path(os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))) / "identity.yaml",
            Path(os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))) / "identity.yml",
        ]

        for p in identity_paths:
            if p.exists():
                try:
                    import yaml
                    with open(p) as f:
                        data = yaml.safe_load(f) or {}
                    name = data.get("name", "THEORA")
                    tagline = data.get("tagline", "")
                    personality = data.get("personality", "")
                    rules = data.get("rules", [])
                    greeting_style = data.get("greeting_style", "")

                    parts = [f"You are {name}."]
                    if tagline:
                        parts.append(tagline)
                    if personality:
                        parts.append(f"\n## Personality\n{personality}")
                    if rules:
                        parts.append("\n## Rules\n" + "\n".join(f"- {r}" for r in rules))
                    if greeting_style:
                        parts.append(f"\n## Communication Style\n{greeting_style}")

                    return "\n".join(parts)
                except Exception as e:
                    logger.warning(f"Failed to load identity: {e}")

        return (
            "You are THEORA, a personal AI operating system.\n"
            "You run locally on the user's devices — phone, laptop, wearables, smart home.\n"
            "You can see through connected cameras, hear through microphones, read health sensors, "
            "and control smart home devices.\n"
            "You are helpful, direct, and privacy-first. Everything stays on-device unless the user says otherwise.\n"
            "You learn the user's preferences over time and get better at anticipating their needs."
        )
