"""
FERAL Desktop Automation Skill — compatibility shim
=====================================================

Historically there were three parallel surfaces for "synthetic mouse +
keyboard" actions: ``agentic_computer_use`` (with its own pyautogui),
``gui_computer_use`` (DPI-scaled primitives), and ``desktop_automation``
(raw, *un-scaled* pyautogui). On Retina displays the unscaled path
clicks at half the intended position, so any code mixing skills landed
in the wrong place.

This module is now a **compatibility shim** that:

1. Keeps the ``desktop_automation`` ``skill_id`` and endpoint ids
   intact so `test_desktop_skills.py`, persona files, and any
   downstream callers that hardcoded ``desktop_automation__click_screen``
   continue to resolve.
2. Normalizes incoming arguments through the provider-neutral
   :mod:`agents.computer_use_driver` and dispatches to
   ``GUIComputerUseSkill`` so DPI scaling, rate limiting, and
   pyautogui/AppleScript fallbacks live in **one** module.
3. Logs a one-shot deprecation warning so anyone still calling these
   endpoints sees that the canonical surface is now ``gui_computer_use``.

The endpoint manifest stays the same (see
``feral-core/skills/manifests/desktop_automation.json``); only the
implementation collapses onto the canonical primitive layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from agents.computer_use_driver import GUI_ENDPOINT_FOR, gui_args_for, normalize_action  # boundary-ok: provider-neutral driver lives in agents/ by design (PR 4)
from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger(__name__)


_ENDPOINT_TO_FERAL_ACTION: Dict[str, str] = {
    "click_screen": "click",
    "double_click": "double_click",
    "right_click": "right_click",
    "move_mouse": "move",
    "type_text": "type",
    "key_combo": "key",
    "scroll": "scroll",
    "get_cursor_position": "screenshot",  # cursor_position is delegated below
}


@register_skill
class DesktopAutomationSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="desktop_automation")
        self._deprecation_warned = False

    def _warn_once(self) -> None:
        if self._deprecation_warned:
            return
        logger.warning(
            "desktop_automation is now a compatibility shim over "
            "gui_computer_use; new callers should use "
            "gui_computer_use__* endpoints directly so DPI scaling "
            "and rate limiting apply uniformly."
        )
        self._deprecation_warned = True

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        self._warn_once()

        if endpoint_id not in _ENDPOINT_TO_FERAL_ACTION:
            return {
                "success": False,
                "status_code": 404,
                "data": None,
                "error": f"Unknown endpoint: {endpoint_id}",
            }

        from skills.impl import get_implementation

        gui = get_implementation("gui_computer_use")
        if gui is None:
            return {
                "success": False,
                "status_code": 503,
                "data": None,
                "error": (
                    "desktop_automation now requires gui_computer_use "
                    "to be registered (it provides DPI-correct primitives). "
                    "Restart FERAL or check the skill registry."
                ),
            }

        if endpoint_id == "get_cursor_position":
            return await gui.execute("cursor_position", {}, vault)

        canonical_args = dict(args or {})
        canonical_args["action"] = _ENDPOINT_TO_FERAL_ACTION[endpoint_id]

        if endpoint_id == "key_combo":
            keys_raw = canonical_args.pop("keys", "")
            if isinstance(keys_raw, list):
                keys_raw = "+".join(str(k) for k in keys_raw)
            canonical_args["keys"] = str(keys_raw)

        normalized = normalize_action(canonical_args)
        if normalized is None:
            return {
                "success": False,
                "status_code": 400,
                "data": None,
                "error": f"desktop_automation could not normalize args for {endpoint_id}",
            }

        gui_endpoint = GUI_ENDPOINT_FOR.get(normalized.action)
        if gui_endpoint is None:
            return {
                "success": False,
                "status_code": 400,
                "data": None,
                "error": f"desktop_automation: unsupported action after normalization: {normalized.action}",
            }

        try:
            return await gui.execute(gui_endpoint, gui_args_for(normalized), vault)
        except Exception as exc:
            return {
                "success": False,
                "status_code": 500,
                "data": None,
                "error": f"desktop_automation -> gui_computer_use failed: {exc}",
            }


__all__ = ["DesktopAutomationSkill"]


# Avoid an unused-import warning on environments where ``asyncio`` is
# only needed transitively. We keep it imported so future async
# additions don't require touching the import block again.
_ = asyncio
