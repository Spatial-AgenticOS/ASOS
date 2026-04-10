"""
THEORA Agentic Computer Use — Vision-Action Loop
==================================================
Combines screen capture, VLM analysis, and desktop automation into
an autonomous loop: screenshot -> understand -> act -> verify.

This is the component that makes THEORA capable of performing any
GUI task, surpassing single-shot tool calling by iterating until
the objective is achieved.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("theora.agentic_cu")

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


@register_skill
class AgenticComputerUseSkill(BaseSkill):
    name = "Agentic Computer Use"
    description = "Autonomous vision-action loop for GUI tasks. Takes screenshots, analyzes them with AI, and performs actions until the task is complete."
    safety_level = "WARN"

    def __init__(self) -> None:
        super().__init__(skill_id="agentic_computer_use")

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
            return {"success": False, "status_code": 503, "data": None, "error": "No VLM available. Set OPENAI_API_KEY or THEORA_VLM_PROVIDER."}

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

            provider = os.getenv("THEORA_VLM_PROVIDER", "openai")
            model = os.getenv("THEORA_VLM_MODEL", "gpt-4o")
            return LLMProvider(provider=provider, model=model, api_key=api_key)
        except Exception as e:
            logger.warning(f"Failed to initialize VLM: {e}")
            return None

    async def _capture_screen(self) -> Optional[str]:
        """Capture the screen and return base64-encoded JPEG."""
        try:
            import platform
            if platform.system() == "Darwin":
                import tempfile
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                tmp.close()
                proc = await asyncio.create_subprocess_exec(
                    "screencapture", "-x", "-t", "jpg", tmp.name,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                with open(tmp.name, "rb") as f:
                    data = f.read()
                os.unlink(tmp.name)

                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(data))
                    if img.width > 1920:
                        ratio = 1920 / img.width
                        img = img.resize((1920, int(img.height * ratio)), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=70)
                    data = buf.getvalue()
                except ImportError:
                    pass

                return base64.b64encode(data).decode()
            else:
                logger.warning("Agentic computer use: unsupported platform for screenshot")
                return None
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

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
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
        try:
            import pyautogui
            pyautogui.click(x, y, clicks=clicks, button=button)
            return f"Clicked ({x}, {y})"
        except ImportError:
            script = f'tell application "System Events" to click at {{{x}, {y}}}'
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            return f"Clicked ({x}, {y}) via AppleScript"

    async def _do_type(self, text: str) -> str:
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=0.02) if text.isascii() else pyautogui.write(text)
            return f"Typed: {text[:50]}"
        except ImportError:
            escaped = text.replace('"', '\\"')
            script = f'tell application "System Events" to keystroke "{escaped}"'
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            return f"Typed via AppleScript: {text[:50]}"

    async def _do_key(self, keys: str) -> str:
        try:
            import pyautogui
            parts = [k.strip() for k in keys.split("+")]
            pyautogui.hotkey(*parts)
            return f"Key combo: {keys}"
        except ImportError:
            return f"pyautogui not available for key combo: {keys}"

    async def _do_scroll(self, direction: str, amount: int) -> str:
        try:
            import pyautogui
            scroll_amount = amount if direction == "up" else -amount
            pyautogui.scroll(scroll_amount)
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
