"""
Tool execution engine for the FERAL orchestrator.

Handles tool call dispatch, safety classification, anti-loop detection,
daemon command forwarding, and subagent parallel execution.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from security.exec_approvals import ApprovalManager
from security.dangerous_tools import is_tool_allowed

if TYPE_CHECKING:
    from agents.orchestrator import Orchestrator

logger = logging.getLogger("feral.orchestrator.tool_runner")

VALID_AUTONOMY_MODES = ("strict", "hybrid", "loose")
READ_ONLY_PATTERNS = ("search", "get", "list", "query", "read", "current", "status", "forecast")


# ─────────────────────────────────────────────
# Safety Classification
# ─────────────────────────────────────────────

class SafetyLevel:
    AUTO = "auto"          # Execute immediately
    CONFIRM = "confirm"    # Ask user confirmation via SDUI
    DENY = "deny"          # Block outright


class ToolRunner:
    """Encapsulates all tool-call execution, safety gating, and anti-loop logic."""

    def __init__(
        self,
        orchestrator: "Orchestrator",
        autonomy_mode: str = "hybrid",
        approval_manager: Optional[ApprovalManager] = None,
    ):
        self._orch = orchestrator
        self._tool_repeat_state: dict[str, dict] = {}
        self._active_subagent_tasks = 0
        self._daemon_session_map: dict[str, str] = {}
        # A2 fix: futures keyed by daemon request_id so the LLM loop can
        # actually ``await`` the hardware daemon's result instead of
        # short-circuiting with a stub "command_sent_to_hardware_daemon"
        # success. Resolved from ``ui_handlers.handle_daemon_result``.
        self._pending_daemon_acks: dict[str, asyncio.Future] = {}
        self._pending_approvals: dict[str, dict] = {}
        # W3-A9: approval state must be shared across BrainState/API +
        # ToolRunner. If no manager is injected (legacy/tests), fall back
        # to local construction.
        self._approval_mgr = approval_manager or ApprovalManager()

        raw_mode = os.environ.get("FERAL_AUTONOMY", "").strip().lower() or autonomy_mode
        self._autonomy_mode = raw_mode if raw_mode in VALID_AUTONOMY_MODES else "hybrid"
        logger.info(f"ToolRunner autonomy_mode={self._autonomy_mode}")

    # ─────────────────────────────────────────────
    # Safety: Graduated Permission System
    # ─────────────────────────────────────────────

    def classify_safety(self, tool_name: str, args: dict) -> str:
        """
        Graduated safety classification:
          AUTO    — safe, execute immediately (reads, searches, notes)
          CONFIRM — potentially impactful, ask user (send message, order, schedule)
          DENY    — dangerous, block outright (format disk, delete all, unsafe robot speeds)
        """
        name_lower = tool_name.lower()

        deny_actions = ["format", "erase_all", "factory_reset", "self_destruct"]
        if any(d in name_lower for d in deny_actions):
            return SafetyLevel.DENY
        if ("robot_move" in name_lower or "actuator" in name_lower) and args.get("speed", 0) > 80:
            return SafetyLevel.DENY

        confirm_patterns = [
            "send", "post", "create", "delete", "update", "move", "grip",
            "play", "pause", "skip", "volume", "lock", "message", "order",
            "schedule", "daemon", "execute", "robot", "actuator", "motor",
        ]
        if any(p in name_lower for p in confirm_patterns):
            return SafetyLevel.CONFIRM

        auto_patterns = [
            "search", "query", "get", "list", "current", "now_playing",
            "forecast", "status", "read", "notes_memory", "web_search",
        ]
        if any(p in name_lower for p in auto_patterns):
            return SafetyLevel.AUTO

        # Default: require confirmation for unknown tools
        return SafetyLevel.CONFIRM

    def enforce_safety(self, tool_name: str, args: dict, session_id: str = "", surface: str = "websocket") -> Optional[dict]:
        """
        Returns a denial dict if the action should be blocked, a pending-approval
        dict if the user must confirm, or None if the action is allowed.
        """
        if not is_tool_allowed(tool_name, surface):
            return {
                "status": "PermissionOutcome::Deny",
                "error": "Surface Policy: Tool Blocked",
                "note": f"Tool '{tool_name}' is denied on surface '{surface}'.",
                "safety_level": "deny",
            }

        level = self.classify_safety(tool_name, args)

        if level == SafetyLevel.DENY:
            return {
                "status": "PermissionOutcome::Deny",
                "error": "Safety Protocol: Action Blocked",
                "note": f"Action '{tool_name}' with args {args} is classified as dangerous and has been blocked.",
                "safety_level": "deny",
            }

        name_lower = tool_name.lower()
        is_read_only = any(p in name_lower for p in READ_ONLY_PATTERNS)

        needs_approval = False
        if self._autonomy_mode == "strict":
            needs_approval = not is_read_only
        elif self._autonomy_mode == "hybrid":
            needs_approval = level == SafetyLevel.CONFIRM
        # loose: nothing needs approval

        if not needs_approval:
            if self._autonomy_mode == "loose" and level == SafetyLevel.CONFIRM:
                logger.info(f"Safety CONFIRM (loose mode auto-exec): {tool_name}")
            return None

        approved, reason = self._approval_mgr.check_approval(tool_name, session_id)
        if approved:
            logger.info(f"Standing approval for {tool_name}: {reason}")
            return None

        # Reuse any identical pending approval so repeated retries by the
        # model keep the same request_id instead of spawning fresh entries.
        for pending in self._pending_approvals.values():
            if (
                pending.get("session_id") == session_id
                and pending.get("tool_name") == tool_name
                and pending.get("args") == args
            ):
                return pending

        request_id = str(uuid4())
        pending = {
            "status": "pending_approval",
            "tool_name": tool_name,
            "args": args,
            "request_id": request_id,
            "session_id": session_id,
            "safety_level": level,
            "created_at": time.time(),
        }
        self._pending_approvals[request_id] = pending
        logger.info(f"Approval required ({self._autonomy_mode}): {tool_name} → request_id={request_id}")
        return pending

    # ─── Approval lifecycle ───

    def pending_for_session(self, session_id: str) -> list[dict]:
        """Return pending approvals for a session, oldest first."""
        rows = [
            p for p in self._pending_approvals.values()
            if p.get("session_id") == session_id
        ]
        rows.sort(key=lambda p: float(p.get("created_at", 0.0)))
        return rows

    def latest_pending_for_session(self, session_id: str) -> Optional[dict]:
        rows = self.pending_for_session(session_id)
        return rows[-1] if rows else None

    def pop_latest_pending_for_session(self, session_id: str) -> Optional[dict]:
        latest = self.latest_pending_for_session(session_id)
        if not latest:
            return None
        req_id = latest.get("request_id")
        if not req_id:
            return None
        return self._pending_approvals.pop(req_id, None)

    def grant_session_approval(self, tool_name: str, session_id: str) -> None:
        """Persist a per-session approval used to execute a confirmed call."""
        self._approval_mgr.grant_approval(tool_name, session_id, scope="session")

    def approve_pending(self, request_id: str) -> Optional[dict]:
        """Approve a pending request; returns tool_name + args for re-execution."""
        pending = self._pending_approvals.pop(request_id, None)
        if pending is None:
            return None
        logger.info(f"Approved pending request {request_id} for {pending['tool_name']}")
        return {"tool_name": pending["tool_name"], "args": pending["args"]}

    def deny_pending(self, request_id: str) -> Optional[dict]:
        """Deny and remove a pending request."""
        pending = self._pending_approvals.pop(request_id, None)
        if pending is None:
            return None
        logger.info(f"Denied pending request {request_id} for {pending['tool_name']}")
        return {
            "status": "PermissionOutcome::Deny",
            "tool_name": pending["tool_name"],
            "request_id": request_id,
            "note": "User denied this action.",
        }

    def set_autonomy_mode(self, mode: str) -> str:
        """Runtime toggle for autonomy mode. Returns the effective mode."""
        mode = mode.strip().lower()
        if mode not in VALID_AUTONOMY_MODES:
            logger.warning(f"Invalid autonomy mode '{mode}', keeping {self._autonomy_mode}")
            return self._autonomy_mode
        self._autonomy_mode = mode
        logger.info(f"Autonomy mode changed to: {mode}")
        return self._autonomy_mode

    @property
    def autonomy_mode(self) -> str:
        return self._autonomy_mode

    # ─────────────────────────────────────────────
    # Anti-loop Detection
    # ─────────────────────────────────────────────

    @staticmethod
    def tool_signature(tool_name: str, args: dict) -> str:
        """Create a stable signature for anti-loop detection."""
        try:
            args_key = json.dumps(args or {}, sort_keys=True, default=str)
        except Exception:
            args_key = str(args)
        return f"{tool_name}::{args_key}"

    def register_tool_attempt(self, session_id: str, tool_name: str, args: dict) -> int:
        """Track consecutive identical tool calls and return current streak."""
        signature = self.tool_signature(tool_name, args)
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
    def anti_loop_guidance(tool_name: str, streak: int) -> str:
        alt_hint = ""
        shell_tools = (
            "desktop_control__shell_command", "computer_use__bash",
            "desktop_control__shell", "shell_command",
        )
        if tool_name in shell_tools:
            alt_hint = (
                " IMPORTANT: For creating or writing files, use computer_use__write_file instead "
                "of shell echo/printf. For running programs, check if computer_use__bash or "
                "code_interpreter__execute can handle it directly."
            )
        return (
            f"STOP: You have called '{tool_name}' with the same arguments "
            f"{streak} times in a row. Do NOT repeat this call. "
            f"You MUST use a completely different tool or approach.{alt_hint}"
        )

    def clear_session(self, session_id: str):
        """Remove anti-loop state for a disconnected session."""
        self._tool_repeat_state.pop(session_id, None)

    # ─────────────────────────────────────────────
    # Daemon Command Execution
    # ─────────────────────────────────────────────

    async def execute_daemon_command(self, session_id: str, node_id: str, action: str, args: dict):
        actual_node_id = node_id.replace("daemon_", "")
        daemons = self._orch.daemons

        if actual_node_id not in daemons:
            available = list(daemons.keys()) if daemons else ["none"]
            await self._orch._send_text(session_id, f"Node '{actual_node_id}' not connected. Available: {available}")
            return

        ws = daemons[actual_node_id]
        request_id = str(uuid4())[:8]
        daemon_msg = {
            "type": "command",
            "request_id": request_id,
            "command": action,
            "args": args,
        }

        self._daemon_session_map[request_id] = session_id
        await ws.send_json(daemon_msg)
        await self._orch._send_text(session_id, f"Command sent to node '{actual_node_id}'...")

    async def execute_daemon_command_with_ack(
        self,
        session_id: str,
        node_id: str,
        action: str,
        args: dict,
        timeout: float = 30.0,
    ) -> dict:
        """Send a daemon command and wait for its ``tool_result`` ack.

        The previous behaviour returned ``{"status": "command_sent_to_hardware_daemon"}``
        immediately — a silent stub-success that let the LLM claim "I did it"
        while the daemon had either rejected the command or never received it.

        This variant:
          * registers a future in ``_pending_daemon_acks`` keyed by ``request_id``;
          * is resolved from ``ui_handlers.handle_daemon_result`` when the daemon
            sends back an ack;
          * times out with ``success: False`` after ``timeout`` seconds so a
            misbehaving daemon can't hang the LLM loop.
        """
        actual_node_id = node_id.replace("daemon_", "")
        daemons = self._orch.daemons

        if actual_node_id not in daemons:
            available = list(daemons.keys()) if daemons else ["none"]
            return {
                "success": False,
                "status_code": 503,
                "error": f"Daemon '{actual_node_id}' not connected. Available: {available}",
                "data": None,
            }

        ws = daemons[actual_node_id]
        request_id = str(uuid4())[:8]
        daemon_msg = {
            "type": "command",
            "request_id": request_id,
            "command": action,
            "args": args,
        }

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_daemon_acks[request_id] = future
        self._daemon_session_map[request_id] = session_id
        try:
            await ws.send_json(daemon_msg)
        except Exception as exc:
            self._pending_daemon_acks.pop(request_id, None)
            return {
                "success": False,
                "status_code": 500,
                "error": f"Failed to send command to daemon '{actual_node_id}': {exc}",
                "data": None,
            }

        try:
            ack = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_daemon_acks.pop(request_id, None)
            return {
                "success": False,
                "status_code": 504,
                "error": (
                    f"Daemon '{actual_node_id}' did not acknowledge {action} "
                    f"within {timeout:.0f}s."
                ),
                "data": None,
            }
        finally:
            self._pending_daemon_acks.pop(request_id, None)

        return ack if isinstance(ack, dict) else {"success": True, "data": ack}

    def resolve_daemon_ack(self, request_id: str, result: dict) -> bool:
        """Deliver a daemon ack to whichever LLM turn is waiting on it.

        Called from ``ui_handlers.handle_daemon_result``. Returns ``True`` if
        the request_id matched a pending future.
        """
        future = self._pending_daemon_acks.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(result)
        return True

    # ─────────────────────────────────────────────
    # Tool Execution (LLM loop variant)
    # ─────────────────────────────────────────────

    async def execute_tool_call_for_llm(self, session_id: str, tool_call: dict, available_skills) -> dict:
        tool_name = tool_call["name"]
        args = tool_call["args"]
        logger.info(f"  LLM Tool call: {tool_name}({json.dumps(args)[:200]})")

        mcp_client = self._orch._mcp_client
        if tool_name.startswith("mcp_") and mcp_client:
            denial = self.enforce_safety(tool_name, args, session_id=session_id)
            if denial:
                logger.warning(f"Safety gate ({denial.get('status')}): {tool_name}")
                return denial
            logger.info(f"  MCP tool: {tool_name}")
            result = await mcp_client.call_tool(tool_name, args)
            content = result.get("content", [])
            if content and isinstance(content, list):
                return {"data": "\n".join(c.get("text", str(c)) for c in content)}
            return result

        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            return {"error": f"Invalid tool reference: {tool_name}"}

        skill_id, endpoint_id = parts
        if skill_id == "subagent" and endpoint_id == "spawn_subagent":
            denial = self.enforce_safety(tool_name, args, session_id=session_id)
            if denial:
                logger.warning(f"Safety gate ({denial.get('status')}): {tool_name}")
                return denial
            return await self.spawn_subagents(session_id, args)

        logger.info(f"  Tool executing: {skill_id}__{endpoint_id}")

        streak = self.register_tool_attempt(session_id, tool_name, args)
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
            anti_loop_note = self.anti_loop_guidance(tool_name, streak)
            logger.warning(anti_loop_note)

        denial = self.enforce_safety(tool_name, args, session_id=session_id)
        if denial:
            logger.warning(f"Safety gate ({denial.get('status')}): {tool_name}")
            return denial

        if skill_id.startswith("daemon_"):
            return await self.execute_daemon_command_with_ack(
                session_id, skill_id, endpoint_id, args,
            )

        skills = self._orch.skills
        skill = skills.skills.get(skill_id)
        if not skill:
            return {"error": f"Skill not found: {skill_id}"}

        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            return {"error": f"Endpoint not found: {endpoint_id}"}

        result = await self._orch.executor.execute(
            tool_name=tool_name, args=args, skill=skill, endpoint=endpoint,
        )

        if not result.get("success"):
            logger.warning(f"PostToolUse: Action failed — {result.get('error')}")

        if anti_loop_note:
            result = dict(result)
            result["_anti_loop_guidance"] = anti_loop_note
            result["_anti_loop_streak"] = streak

        return result

    # ─────────────────────────────────────────────
    # Tool Execution (direct / UI-event variant)
    # ─────────────────────────────────────────────

    async def execute_tool_call(self, session_id: str, tool_call: dict, available_skills):
        from models.protocol import FeralMessage, SDUIPayload

        tool_name = tool_call["name"]
        args = tool_call["args"]
        logger.info(f"  Tool call: {tool_name}({json.dumps(args)[:200]})")

        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            await self._orch._send_text(session_id, f"Invalid tool reference: {tool_name}")
            return

        skill_id, endpoint_id = parts

        denial = self.enforce_safety(tool_name, args, session_id=session_id)
        if denial:
            status = denial.get("status", "blocked")
            note = denial.get("note", denial.get("error", "Action blocked by safety policy."))
            if status == "pending_approval":
                await self._orch._send_text(
                    session_id,
                    f"Approval required for '{tool_name}'. Request ID: {denial.get('request_id')}",
                )
            else:
                await self._orch._send_text(session_id, note)
            return

        if skill_id.startswith("daemon_"):
            await self.execute_daemon_command(session_id, skill_id, endpoint_id, args)
            return

        skills = self._orch.skills
        skill = skills.skills.get(skill_id)
        if not skill:
            await self._orch._send_text(session_id, f"Skill not found: {skill_id}")
            return

        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            await self._orch._send_text(session_id, f"Endpoint not found: {endpoint_id}")
            return

        result = await self._orch.executor.execute(
            tool_name=tool_name, args=args, skill=skill, endpoint=endpoint,
        )

        if result["success"] and result["data"]:
            sdui = self._orch.genui.generate(
                data=result["data"],
                skill_brand=skill.brand.model_dump(),
                ui_hint=endpoint.ui_hint,
                endpoint_id=endpoint_id,
            )
            await self._orch._send_text(session_id, f"Here's the result from {skill.brand.name}:")
            await self._orch.send(session_id, FeralMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
        else:
            error = result.get("error", "Unknown error")
            await self._orch._send_text(session_id, f"Failed to call {skill.brand.name}: {error}")

    # ─────────────────────────────────────────────
    # Subagent Parallel Execution
    # ─────────────────────────────────────────────

    async def spawn_subagents(self, session_id: str, args: dict) -> dict:
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
        llm = self._orch.llm
        if not llm or not llm.available:
            return {
                "success": False,
                "status_code": 503,
                "data": None,
                "error": "LLM unavailable; cannot spawn subagents.",
            }

        goal = str(args.get("goal", "") or "").strip()
        max_iterations = self._orch._max_iterations
        try:
            max_workers = int(args.get("max_workers", min(3, len(tasks))) or 3)
        except Exception:
            max_workers = min(3, len(tasks))
        try:
            max_iters = int(args.get("max_iterations", min(max_iterations, 8)) or 4)
        except Exception:
            max_iters = min(max_iterations, 8)
        max_workers = max(1, min(max_workers, 6))
        max_iters = max(1, min(max_iters, 12))
        sem = asyncio.Semaphore(max_workers)

        async def _run_one(i: int, task_text: str) -> dict:
            scoped_task = task_text if not goal else f"Goal: {goal}\nTask: {task_text}"
            async with sem:
                started = time.time()
                self._active_subagent_tasks += 1
                try:
                    result = await self._run_subagent_task(
                        parent_session_id=session_id,
                        task_text=scoped_task,
                        max_iterations=max_iters,
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
                finally:
                    self._active_subagent_tasks = max(0, self._active_subagent_tasks - 1)

        results = await asyncio.gather(*[_run_one(i, t) for i, t in enumerate(tasks, 1)])
        success_count = sum(1 for r in results if r.get("success"))

        return {
            "success": True,
            "status_code": 200,
            "data": {
                "goal": goal or None,
                "task_count": len(tasks),
                "max_workers": max_workers,
                "max_iterations": max_iters,
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
        orch = self._orch
        relevant_skills = await orch._route_prompt(task_text)
        tools = orch.skills.get_tools_for_skills(relevant_skills)
        if orch._mcp_client:
            mcp_tools = orch._mcp_client.to_llm_tool_definitions()
            if mcp_tools:
                tools = (tools or []) + mcp_tools

        frame = orch.perception.get_frame(parent_session_id)
        system_prompt = orch._build_system_prompt(frame, relevant_skills, parent_session_id)
        history: list[dict] = [{"role": "user", "content": task_text}]
        sub_session_id = f"{parent_session_id}:sub:{ordinal}:{str(uuid4())[:6]}"
        final_text = ""
        tool_calls_executed = 0
        iterations_used = 0

        for i in range(max_iterations):
            iterations_used = i + 1
            response = await orch.llm.chat(
                messages=[{"role": "system", "content": system_prompt}, *history],
                tools=tools if tools else None,
            )
            text_content, tool_calls = orch.llm.extract_response(response)

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
                        result_data = await self.execute_tool_call_for_llm(
                            sub_session_id, tc, relevant_skills,
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
