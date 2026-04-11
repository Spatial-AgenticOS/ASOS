"""
Refusal detection and action-intent fallback for the FERAL orchestrator.

Detects when the LLM refuses to act, builds direct action-intent tool calls
for common operations (open app, open URL, create file, etc.), and executes
fallback paths when the LLM won't cooperate.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.orchestrator import Orchestrator
    from models.skill_manifest import SkillManifest

logger = logging.getLogger("feral.orchestrator.refusal")


class RefusalHandler:
    """Detects LLM refusals and provides fallback action-intent execution."""

    REFUSAL_PHRASES = (
        "i can't",
        "i cannot",
        "i am unable",
        "i'm unable",
        "not possible",
        "unfortunately i",
        "i don't have the ability",
        "cannot do that",
        "can't do that",
        "can't create",
        "cannot create",
    )

    ACTION_INTENT_WORDS = {
        "create", "open", "make", "write", "run", "play", "generate", "send",
        "install", "build", "edit", "delete", "move", "copy", "search", "find",
        "start", "stop", "launch", "record", "download", "upload",
    }

    DESTRUCTIVE_ACTION_WORDS = {
        "delete", "remove", "erase", "destroy", "wipe", "format", "factory reset",
        "shutdown", "reboot", "kill", "terminate", "rm -rf",
    }

    COMMON_APP_NAMES = {
        "music": "Music",
        "spotify": "Spotify",
        "safari": "Safari",
        "chrome": "Google Chrome",
        "terminal": "Terminal",
        "notes": "Notes",
        "finder": "Finder",
        "mail": "Mail",
        "calendar": "Calendar",
        "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "slack": "Slack",
    }

    def __init__(self, orchestrator: "Orchestrator"):
        self._orch = orchestrator

    # ─────────────────────────────────────────────
    # Detection helpers
    # ─────────────────────────────────────────────

    def is_refusal(self, text: str) -> bool:
        if not text:
            return False
        normalized = re.sub(r"\s+", " ", text.lower()).strip()
        return any(phrase in normalized for phrase in self.REFUSAL_PHRASES)

    def query_implies_action(self, text: str) -> bool:
        normalized = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        words = [w for w in normalized.split() if w]
        if len(words) >= 6:
            return True
        return any(word in self.ACTION_INTENT_WORDS for word in words)

    def action_text_is_destructive(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(token in lowered for token in self.DESTRUCTIVE_ACTION_WORDS)

    @staticmethod
    def extract_first_url(text: str) -> str:
        match = re.search(r"(https?://[^\s]+)", text or "", flags=re.IGNORECASE)
        if not match:
            return ""
        return match.group(1).rstrip(").,;!?")

    def extract_open_app_name(self, text: str) -> str:
        lowered = (text or "").lower()
        for hint, app in self.COMMON_APP_NAMES.items():
            if any(phrase in lowered for phrase in (f"open {hint}", f"launch {hint}", f"start {hint}")):
                return app

        match = re.search(r"(?:open|launch|start)\s+([a-z0-9 ._+-]{2,40})(?:\s+app(?:lication)?)?", lowered)
        if not match:
            return ""
        candidate = match.group(1).strip(" ._+-")
        if not candidate:
            return ""
        return " ".join(w.capitalize() for w in candidate.split())

    @staticmethod
    def capability_key(text: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
        return normalized[:180]

    # ─────────────────────────────────────────────
    # Action intent construction
    # ─────────────────────────────────────────────

    def build_action_intent_tool_call(self, text: str) -> Optional[dict]:
        lowered = (text or "").lower()
        app_name = self.extract_open_app_name(text)
        if app_name:
            return {
                "name": "desktop_control__open_app",
                "args": {"script": f'tell application "{app_name}" to activate'},
                "_intent": f"open {app_name}",
            }

        url = self.extract_first_url(text)
        if url:
            return {
                "name": "desktop_control__shell_command",
                "args": {"command": f"open {shlex.quote(url)}"},
                "_intent": f"open URL {url}",
            }

        if "desktop" in lowered and any(token in lowered for token in ("note", "file", "txt")):
            content_match = re.search(r"(?:add|with|containing|content[: ]+)(.+)$", text, flags=re.IGNORECASE)
            content = (content_match.group(1).strip() if content_match else "hello world").strip("\"'")
            python_code = (
                "from pathlib import Path; "
                "p=Path.home()/'Desktop'/'feral_note.txt'; "
                f"p.write_text({content!r}); "
                "print(f'Created {p}')"
            )
            return {
                "name": "computer_use__bash",
                "args": {"command": f"python3 -c {shlex.quote(python_code)}"},
                "_intent": "create desktop note",
            }

        if self.query_implies_action(text):
            return {
                "name": "agentic_computer_use__execute_task",
                "args": {"task": text, "max_steps": 8},
                "_intent": "execute GUI workflow",
            }

        return None

    @staticmethod
    def summarize_action_result(tool_call: dict, result_data: dict) -> str:
        tool_name = tool_call.get("name", "action")
        if not isinstance(result_data, dict):
            return f"I executed {tool_name}."

        if result_data.get("status") == "command_sent_to_hardware_daemon":
            return "Command sent to the connected device daemon."

        if result_data.get("success"):
            data = result_data.get("data")
            if isinstance(data, dict):
                if data.get("note"):
                    return f"Done. {data.get('note')}"
                if data.get("stdout"):
                    return f"Done. {str(data.get('stdout'))[:240]}"
            return f"Done. Executed {tool_name} successfully."

        error = result_data.get("error") or result_data.get("note") or "Unknown error"
        return f"I attempted {tool_name}, but it failed: {error}"

    # ─────────────────────────────────────────────
    # Fallback execution
    # ─────────────────────────────────────────────

    async def execute_action_intent_fallback(
        self,
        session_id: str,
        text: str,
        available_skills: list["SkillManifest"],
    ) -> bool:
        """
        Attempt to directly execute the user's intent when the LLM refuses.
        Returns True if the intent was handled (even if denied by safety).
        """
        from agents.tool_runner import SafetyLevel

        tool_call = self.build_action_intent_tool_call(text)
        if not tool_call:
            return False

        orch = self._orch
        tool_name = tool_call["name"]
        args = tool_call.get("args", {})
        safety_level = orch.tool_runner.classify_safety(tool_name, args)
        if self.action_text_is_destructive(text) and safety_level == SafetyLevel.AUTO:
            safety_level = SafetyLevel.CONFIRM

        if safety_level == SafetyLevel.DENY:
            denial = orch.tool_runner.enforce_safety(tool_name, args) or {
                "error": "This action is blocked by safety policy.",
            }
            await orch._send_text(session_id, denial.get("error", "Blocked by safety policy."))
            return True

        if safety_level == SafetyLevel.CONFIRM:
            await orch._maybe_auto_expand_capability(session_id, text)
            await orch._queue_action_confirmation(
                session_id=session_id,
                tool_call=tool_call,
                available_skills=available_skills,
                reason=text,
            )
            return True

        result_data = await orch.tool_runner.execute_tool_call_for_llm(session_id, tool_call, available_skills)
        await orch._try_genui_for_result(session_id, tool_call, result_data)
        summary = self.summarize_action_result(tool_call, result_data)
        await orch._send_text(session_id, summary)
        if orch.memory:
            orch.memory.working_push(session_id, {"role": "assistant", "text": summary[:300]})
        await orch._maybe_auto_expand_capability(session_id, text)
        return True
