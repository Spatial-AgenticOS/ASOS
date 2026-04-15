"""
FERAL Agentic Computer Use — Vision-Action Loop
==================================================
Combines screen capture, VLM analysis, and desktop automation into
an autonomous loop: screenshot -> understand -> act -> verify.

This is the component that makes FERAL capable of performing any
GUI task, surpassing single-shot tool calling by iterating until
the objective is achieved.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from skills.base import BaseSkill
from skills.impl import register_skill
from skills.impl.gui_computer_use import (
    capture_screenshot_bytes,
    detect_dpi_scale,
    scale_coordinates,
)

logger = logging.getLogger("feral.agentic_cu")

MAX_ITERATIONS = 15
SCREENSHOT_DELAY = 0.8

ACTION_SYSTEM_PROMPT = """You are an AI agent that controls a computer to accomplish tasks.
You are given a screenshot of the current screen and a task to perform.

Available actions (return EXACTLY ONE as JSON):
- {"action": "click", "x": <int>, "y": <int>, "description": "what you're clicking"}
- {"action": "double_click", "x": <int>, "y": <int>, "description": "what you're double-clicking"}
- {"action": "right_click", "x": <int>, "y": <int>, "description": "what you're right-clicking"}
- {"action": "type", "text": "<string>", "description": "what you're typing"}
- {"action": "key", "keys": "<combo>", "description": "what shortcut"} (e.g. "cmd+c", "enter", "tab")
- {"action": "scroll", "direction": "up"|"down", "amount": <int>, "description": "why scrolling"}
- {"action": "shell", "command": "<string>", "description": "shell command to run"}
- {"action": "done", "summary": "what was accomplished"}
- {"action": "failed", "reason": "why it cannot be done"}

Rules:
- Look at the screenshot carefully to determine element positions.
- Click coordinates should target the CENTER of the element you want to interact with.
- After clicking a text field, use "type" to enter text.
- Use "key" for keyboard shortcuts (cmd+a, cmd+v, enter, tab, escape, etc.).
- Use "shell" for opening apps (open -a "App Name") or running commands.
- Return "done" when the task is complete.
- Return "failed" only if the task is truly impossible after trying.
- ALWAYS return valid JSON. Nothing else.
"""


# ── Pydantic models for structured VLM action parsing ─────────────

class ClickAction(BaseModel):
    action: str
    x: int
    y: int
    description: str = ""

class TypeAction(BaseModel):
    action: str
    text: str
    description: str = ""

class KeyAction(BaseModel):
    action: str
    keys: str
    description: str = ""

class ScrollAction(BaseModel):
    action: str
    direction: str
    amount: int = 3
    description: str = ""

class ShellAction(BaseModel):
    action: str
    command: str
    description: str = ""

class DoneAction(BaseModel):
    action: str
    summary: str = ""

class FailedAction(BaseModel):
    action: str
    reason: str = ""


_ACTION_JSON_RE = re.compile(r'\{[^{}]*"action"\s*:\s*"[^"]+?"[^{}]*\}', re.DOTALL)

_ACTION_MODELS = {
    "click": ClickAction,
    "double_click": ClickAction,
    "right_click": ClickAction,
    "type": TypeAction,
    "key": KeyAction,
    "scroll": ScrollAction,
    "shell": ShellAction,
    "done": DoneAction,
    "failed": FailedAction,
}


def parse_vlm_action(raw_text: str) -> Optional[dict]:
    """Parse a VLM response into a validated action dict.

    Strategy:
    1. Try to parse the full text as JSON directly.
    2. Strip markdown fences and retry.
    3. Regex-extract the first JSON object containing "action".
    4. Validate with the appropriate Pydantic model.
    """
    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        start = 1
        if lines[0].strip().startswith("```"):
            start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        inner = lines[start:end]
        if inner and inner[0].strip().lower().startswith("json"):
            inner = inner[1:]
        cleaned = "\n".join(inner).strip()

    candidates: List[str] = [cleaned]

    regex_matches = _ACTION_JSON_RE.findall(raw_text)
    candidates.extend(regex_matches)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(data, dict) or "action" not in data:
            continue

        action_type = data["action"]
        model_cls = _ACTION_MODELS.get(action_type)
        if model_cls is None:
            return data

        try:
            validated = model_cls.model_validate(data)
            return validated.model_dump()
        except (ValidationError, Exception):
            return data

    return None


@register_skill
class AgenticComputerUseSkill(BaseSkill):
    name = "Agentic Computer Use"
    description = "Autonomous vision-action loop for GUI tasks. Takes screenshots, analyzes them with AI, and performs actions until the task is complete."
    safety_level = "WARN"

    def __init__(self) -> None:
        super().__init__(skill_id="agentic_computer_use")
        self._dpi_scale: Optional[float] = None

    @property
    def dpi_scale(self) -> float:
        if self._dpi_scale is None:
            self._dpi_scale = detect_dpi_scale()
            logger.info("Agentic CU DPI scale: %.1f", self._dpi_scale)
        return self._dpi_scale

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        if endpoint_id == "execute_task":
            return await self._execute_task(args, vault)
        return {"success": False, "status_code": 404, "data": None, "error": f"Unknown endpoint: {endpoint_id}"}

    async def _execute_task(self, args: dict, vault: dict) -> dict:
        task = args.get("task", "").strip()
        if not task:
            return {"success": False, "status_code": 400, "data": None, "error": "task description is required"}

        max_steps = min(int(args.get("max_steps", MAX_ITERATIONS)), MAX_ITERATIONS)
        steps_log: list[dict] = []

        llm = self._get_vlm(vault)
        if not llm:
            return {"success": False, "status_code": 503, "data": None, "error": "No VLM available. Set OPENAI_API_KEY or FERAL_VLM_PROVIDER."}

        for i in range(max_steps):
            screenshot_b64 = await self._capture_screen()
            if not screenshot_b64:
                steps_log.append({"step": i + 1, "error": "Screenshot capture failed"})
                break

            action = await self._decide_action(llm, task, screenshot_b64, steps_log, vault)
            if not action:
                steps_log.append({"step": i + 1, "error": "VLM returned no valid action"})
                break

            action_type = action.get("action", "")
            step_record = {"step": i + 1, "action": action_type, "detail": action.get("description", "")}

            if action_type == "done":
                step_record["summary"] = action.get("summary", "Task completed")
                steps_log.append(step_record)
                return {
                    "success": True, "status_code": 200,
                    "data": {"completed": True, "steps": len(steps_log), "log": steps_log, "summary": action.get("summary", "")},
                    "error": None,
                }

            if action_type == "failed":
                step_record["reason"] = action.get("reason", "Unknown")
                steps_log.append(step_record)
                return {
                    "success": False, "status_code": 200,
                    "data": {"completed": False, "steps": len(steps_log), "log": steps_log, "reason": action.get("reason", "")},
                    "error": action.get("reason"),
                }

            result = await self._execute_action(action)
            step_record["result"] = result
            steps_log.append(step_record)

            await asyncio.sleep(SCREENSHOT_DELAY)

        return {
            "success": False, "status_code": 200,
            "data": {"completed": False, "steps": len(steps_log), "log": steps_log, "reason": "Max iterations reached"},
            "error": "Max iterations reached without completing task",
        }

    def _get_vlm(self, vault: dict) -> Optional[Any]:
        """Get an LLM provider that supports vision."""
        try:
            from agents.llm_provider import LLMProvider
            api_key = (
                vault.get("OPENAI_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or vault.get("ANTHROPIC_API_KEY")
                or os.getenv("ANTHROPIC_API_KEY")
            )
            if not api_key:
                return None

            provider = os.getenv("FERAL_VLM_PROVIDER", "openai")
            model = os.getenv("FERAL_VLM_MODEL", "gpt-4o")
            return LLMProvider(provider=provider, model=model, api_key=api_key)
        except Exception as e:
            logger.warning(f"Failed to initialize VLM: {e}")
            return None

    async def _capture_screen(self) -> Optional[str]:
        """Capture the screen and return base64-encoded JPEG."""
        try:
            raw = await capture_screenshot_bytes()
            if raw is None:
                return None
            return base64.b64encode(raw).decode()
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    async def _decide_action(self, llm: Any, task: str, screenshot_b64: str, history: list, vault: dict) -> Optional[dict]:
        """Ask the VLM to decide the next action based on the screenshot."""
        history_text = ""
        if history:
            recent = history[-5:]
            history_text = "\n".join(
                f"Step {s['step']}: {s.get('action', '?')} - {s.get('detail', '')}"
                for s in recent
            )

        user_content = [
            {"type": "text", "text": f"Task: {task}"},
        ]
        if history_text:
            user_content.append({"type": "text", "text": f"Previous steps:\n{history_text}"})
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}", "detail": "high"},
        })
        user_content.append({"type": "text", "text": "What is the next action? Return ONLY JSON."})

        try:
            response = await llm.chat(
                messages=[
                    {"role": "system", "content": ACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            text, _ = llm.extract_response(response)
            if not text:
                return None

            return parse_vlm_action(text)
        except Exception as e:
            logger.warning(f"VLM action decision failed: {e}")
            return None

    async def _execute_action(self, action: dict) -> str:
        """Execute a single action on the computer."""
        action_type = action.get("action", "")
        try:
            if action_type == "click":
                return await self._do_click(int(action["x"]), int(action["y"]))
            elif action_type == "double_click":
                return await self._do_click(int(action["x"]), int(action["y"]), clicks=2)
            elif action_type == "right_click":
                return await self._do_click(int(action["x"]), int(action["y"]), button="right")
            elif action_type == "type":
                return await self._do_type(action.get("text", ""))
            elif action_type == "key":
                return await self._do_key(action.get("keys", ""))
            elif action_type == "scroll":
                return await self._do_scroll(action.get("direction", "down"), int(action.get("amount", 3)))
            elif action_type == "shell":
                return await self._do_shell(action.get("command", ""))
            else:
                return f"Unknown action: {action_type}"
        except Exception as e:
            return f"Action failed: {e}"

    async def _do_click(self, x: int, y: int, clicks: int = 1, button: str = "left") -> str:
        sx, sy = scale_coordinates(x, y, self.dpi_scale)
        try:
            import pyautogui
            await asyncio.to_thread(pyautogui.click, sx, sy, clicks=clicks, button=button)
            return f"Clicked ({sx}, {sy}) [raw=({x},{y}), scale={self.dpi_scale}]"
        except ImportError:
            if platform.system() == "Darwin":
                script = f'tell application "System Events" to click at {{{sx}, {sy}}}'
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e", script,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                return f"Clicked ({sx}, {sy}) via AppleScript"
            return f"pyautogui not available and no fallback for {platform.system()}"

    async def _do_type(self, text: str) -> str:
        try:
            import pyautogui
            if text.isascii():
                await asyncio.to_thread(pyautogui.write, text, interval=0.02)
            else:
                try:
                    import pyperclip
                    pyperclip.copy(text)
                    modifier = "command" if platform.system() == "Darwin" else "ctrl"
                    await asyncio.to_thread(pyautogui.hotkey, modifier, "v")
                except ImportError:
                    await asyncio.to_thread(pyautogui.write, text, interval=0.02)
            return f"Typed: {text[:50]}"
        except ImportError:
            if platform.system() == "Darwin":
                escaped = text.replace('"', '\\"')
                script = f'tell application "System Events" to keystroke "{escaped}"'
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e", script,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                return f"Typed via AppleScript: {text[:50]}"
            return f"pyautogui not available and no fallback for {platform.system()}"

    async def _do_key(self, keys: str) -> str:
        try:
            import pyautogui
            parts = [k.strip() for k in keys.split("+")]
            mapped = []
            for p in parts:
                low = p.lower()
                if low in ("cmd", "command", "meta", "super"):
                    mapped.append("command" if platform.system() == "Darwin" else "ctrl")
                elif low in ("ctrl", "control"):
                    mapped.append("ctrl")
                elif low in ("alt", "option"):
                    mapped.append("alt")
                elif low in ("shift",):
                    mapped.append("shift")
                else:
                    mapped.append(low)
            await asyncio.to_thread(pyautogui.hotkey, *mapped)
            return f"Key combo: {keys}"
        except ImportError:
            return f"pyautogui not available for key combo: {keys}"

    async def _do_scroll(self, direction: str, amount: int) -> str:
        try:
            import pyautogui
            scroll_amount = amount if direction == "up" else -amount
            await asyncio.to_thread(pyautogui.scroll, scroll_amount)
            return f"Scrolled {direction} by {amount}"
        except ImportError:
            return "pyautogui not available for scroll"

    async def _do_shell(self, command: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        output = (stdout or b"").decode()[:500]
        err = (stderr or b"").decode()[:200]
        return f"exit={proc.returncode} out={output}" + (f" err={err}" if err else "")
