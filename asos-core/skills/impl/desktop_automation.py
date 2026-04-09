"""
THEORA Desktop Automation Skill
================================
Global mouse/keyboard control via pyautogui for vision-action loops.
"""

from __future__ import annotations

import asyncio
import platform
from typing import Any, Dict

from skills.base import BaseSkill
from skills.impl import register_skill


@register_skill
class DesktopAutomationSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="desktop_automation")
        self._pag = None

    def _get_pyautogui(self):
        if self._pag is not None:
            return self._pag
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05
            self._pag = pyautogui
        except ImportError:
            self._pag = None
        return self._pag

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        _ = vault
        handler = {
            "click_screen": self._click,
            "double_click": self._double_click,
            "right_click": self._right_click,
            "move_mouse": self._move_mouse,
            "type_text": self._type_text,
            "key_combo": self._key_combo,
            "scroll": self._scroll,
            "get_cursor_position": self._get_cursor_position,
        }.get(endpoint_id)

        if not handler:
            return {"success": False, "status_code": 404, "data": None, "error": f"Unknown endpoint: {endpoint_id}"}

        pag = self._get_pyautogui()
        if pag is None:
            return {
                "success": False,
                "status_code": 500,
                "data": None,
                "error": "pyautogui is not installed. Run: pip install pyautogui",
            }

        try:
            return await handler(pag, args)
        except Exception as e:
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}

    async def _click(self, pag, args: dict) -> dict:
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        await asyncio.to_thread(pag.click, x, y)
        return {"success": True, "status_code": 200, "data": {"action": "click", "x": x, "y": y}, "error": None}

    async def _double_click(self, pag, args: dict) -> dict:
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        await asyncio.to_thread(pag.doubleClick, x, y)
        return {"success": True, "status_code": 200, "data": {"action": "double_click", "x": x, "y": y}, "error": None}

    async def _right_click(self, pag, args: dict) -> dict:
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        await asyncio.to_thread(pag.rightClick, x, y)
        return {"success": True, "status_code": 200, "data": {"action": "right_click", "x": x, "y": y}, "error": None}

    async def _move_mouse(self, pag, args: dict) -> dict:
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        duration = float(args.get("duration", 0.3))
        await asyncio.to_thread(pag.moveTo, x, y, duration=duration)
        return {"success": True, "status_code": 200, "data": {"action": "move_mouse", "x": x, "y": y}, "error": None}

    async def _type_text(self, pag, args: dict) -> dict:
        text = str(args.get("text", ""))
        interval = float(args.get("interval", 0.02))
        if not text:
            return {"success": False, "status_code": 400, "data": None, "error": "text is required"}
        await asyncio.to_thread(pag.typewrite, text, interval=interval)
        return {"success": True, "status_code": 200, "data": {"action": "type_text", "length": len(text)}, "error": None}

    async def _key_combo(self, pag, args: dict) -> dict:
        keys_raw = args.get("keys", "")
        if isinstance(keys_raw, str):
            keys = [k.strip() for k in keys_raw.split("+") if k.strip()]
        else:
            keys = list(keys_raw)

        if not keys:
            return {"success": False, "status_code": 400, "data": None, "error": "keys is required (e.g. 'cmd+c')"}

        key_map = {"cmd": "command", "ctrl": "ctrl", "alt": "alt", "shift": "shift", "win": "win", "super": "win"}
        mapped = [key_map.get(k.lower(), k.lower()) for k in keys]

        await asyncio.to_thread(pag.hotkey, *mapped)
        return {"success": True, "status_code": 200, "data": {"action": "key_combo", "keys": mapped}, "error": None}

    async def _scroll(self, pag, args: dict) -> dict:
        amount = int(args.get("amount", 3))
        direction = str(args.get("direction", "down")).lower()
        x = args.get("x")
        y = args.get("y")

        clicks = -amount if direction == "down" else amount
        kwargs: dict[str, Any] = {}
        if x is not None and y is not None:
            kwargs["x"] = int(x)
            kwargs["y"] = int(y)
        await asyncio.to_thread(pag.scroll, clicks, **kwargs)
        return {"success": True, "status_code": 200, "data": {"action": "scroll", "direction": direction, "amount": amount}, "error": None}

    async def _get_cursor_position(self, pag, args: dict) -> dict:
        pos = pag.position()
        screen = pag.size()
        return {
            "success": True,
            "status_code": 200,
            "data": {"x": pos.x, "y": pos.y, "screen_width": screen.width, "screen_height": screen.height},
            "error": None,
        }
