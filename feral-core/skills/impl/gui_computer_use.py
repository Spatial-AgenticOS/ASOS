"""
FERAL GUI Computer Use — Anthropic-Style Desktop Control
==========================================================
Industry-standard computer-use skill providing individual GUI primitives:
screenshot, mouse clicks, typing, key combos, scrolling, and window management.

All coordinates from VLMs are in screenshot-space and automatically divided
by the DPI scale factor before being passed to pyautogui, so Retina/HiDPI
displays work correctly out of the box.

Hardened: action rate limiter (configurable), proper logger namespace.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skill.gui")

_SCREENSHOT_MAX_WIDTH = 1920


# ── DPI / Retina helpers ─────────────────────────────────────────

def detect_dpi_scale() -> float:
    """Detect the display DPI scale factor.

    macOS: queries NSScreen via a subprocess call to AppKit.
    Linux: reads GDK_SCALE env var.
    Falls back to 1.0 everywhere else.
    """
    system = platform.system()
    if system == "Darwin":
        try:
            result = subprocess.run(
                [
                    "python3", "-c",
                    "import AppKit; print(AppKit.NSScreen.mainScreen().backingScaleFactor())",
                ],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return 2.0  # safe default for modern Macs
    elif system == "Linux":
        scale = os.environ.get("GDK_SCALE")
        if scale:
            try:
                return float(scale)
            except ValueError:
                pass
        return 1.0
    return 1.0


def scale_coordinates(x: int, y: int, scale: float) -> Tuple[int, int]:
    """Convert VLM screenshot-space coords to physical screen coords."""
    if scale <= 0:
        scale = 1.0
    return int(x / scale), int(y / scale)


# ── Rate limiter ─────────────────────────────────────────────────

class ActionRateLimiter:
    """Sliding-window rate limiter for GUI actions."""

    def __init__(self, max_per_second: float = 10.0):
        self._max_per_second = max_per_second
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Return True if the action is allowed, False if rate-limited."""
        async with self._lock:
            now = time.monotonic()
            cutoff = now - 1.0
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) >= self._max_per_second:
                return False
            self._timestamps.append(now)
            return True


# ── Screenshot capture (cross-platform) ─────────────────────────

async def capture_screenshot_bytes() -> Optional[bytes]:
    """Capture the screen and return raw JPEG bytes (resized for VLM)."""
    system = platform.system()
    raw_data: Optional[bytes] = None

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = tmp.name

    try:
        if system == "Darwin":
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", "-t", "png", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if Path(path).exists() and Path(path).stat().st_size > 0:
                raw_data = Path(path).read_bytes()

        elif system == "Linux":
            for tool in ["gnome-screenshot", "scrot", "import"]:
                if not shutil.which(tool):
                    continue
                if tool == "gnome-screenshot":
                    proc = await asyncio.create_subprocess_exec(
                        tool, "-f", path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                elif tool == "scrot":
                    proc = await asyncio.create_subprocess_exec(
                        tool, path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                elif tool == "import":
                    proc = await asyncio.create_subprocess_exec(
                        tool, "-window", "root", path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                else:
                    continue
                await proc.wait()
                if Path(path).exists() and Path(path).stat().st_size > 0:
                    raw_data = Path(path).read_bytes()
                    break
        else:
            logger.warning("gui_computer_use: unsupported platform %s", system)
            return None

    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if not raw_data:
        return None

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw_data))
        if img.width > _SCREENSHOT_MAX_WIDTH:
            ratio = _SCREENSHOT_MAX_WIDTH / img.width
            img = img.resize(
                (_SCREENSHOT_MAX_WIDTH, int(img.height * ratio)),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return buf.getvalue()
    except ImportError:
        return raw_data


# ── Skill implementation ─────────────────────────────────────────

@register_skill
class GUIComputerUseSkill(BaseSkill):
    """Individual GUI-control primitives for VLM-driven computer use."""

    def __init__(self) -> None:
        super().__init__(skill_id="gui_computer_use")
        self._scale: Optional[float] = None
        max_actions = float(os.getenv("FERAL_GUI_MAX_ACTIONS_PER_S", "10"))
        self._rate_limiter = ActionRateLimiter(max_per_second=max_actions)

    @property
    def scale(self) -> float:
        if self._scale is None:
            self._scale = detect_dpi_scale()
            logger.info("DPI scale factor detected: %.1f", self._scale)
        return self._scale

    async def execute(
        self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str],
    ) -> Dict[str, Any]:
        if endpoint_id != "screenshot":
            allowed = await self._rate_limiter.acquire()
            if not allowed:
                return {
                    "success": False, "status_code": 429,
                    "data": None,
                    "reason": "rate_limit_exceeded",
                    "error": f"Rate limit exceeded (max {self._rate_limiter._max_per_second}/s)",
                }

        dispatch = {
            "screenshot": self._screenshot,
            "mouse_click": self._mouse_click,
            "mouse_double_click": self._mouse_double_click,
            "mouse_right_click": self._mouse_right_click,
            "mouse_move": self._mouse_move,
            "type_text": self._type_text,
            "key_press": self._key_press,
            "scroll": self._scroll,
            "cursor_position": self._cursor_position,
            "window_list": self._window_list,
            "window_focus": self._window_focus,
        }
        handler = dispatch.get(endpoint_id)
        if not handler:
            return {
                "success": False, "status_code": 404,
                "data": None, "error": f"Unknown endpoint: {endpoint_id}",
            }
        try:
            return await handler(args)
        except Exception as exc:
            logger.exception("gui_computer_use.%s failed", endpoint_id)
            return {
                "success": False, "status_code": 500,
                "data": None, "error": str(exc),
            }

    # ── screenshot ────────────────────────────────────────────────

    async def _screenshot(self, args: dict) -> dict:
        data = await asyncio.to_thread(self._sync_screenshot)
        if data is None:
            return {
                "success": False, "status_code": 500,
                "data": None, "error": "Screenshot capture failed",
            }
        return {
            "success": True, "status_code": 200,
            "data": {
                "image_base64": data,
                "format": "jpeg",
                "dpi_scale": self.scale,
            },
            "error": None,
        }

    def _sync_screenshot(self) -> Optional[str]:
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(capture_screenshot_bytes())
        finally:
            loop.close()
        if raw is None:
            return None
        return base64.b64encode(raw).decode()

    # ── mouse_click ───────────────────────────────────────────────

    async def _mouse_click(self, args: dict) -> dict:
        x, y = self._scaled_xy(args)
        await asyncio.to_thread(self._pyautogui_click, x, y, 1, "left")
        return self._ok(f"Clicked ({x}, {y})")

    async def _mouse_double_click(self, args: dict) -> dict:
        x, y = self._scaled_xy(args)
        await asyncio.to_thread(self._pyautogui_click, x, y, 2, "left")
        return self._ok(f"Double-clicked ({x}, {y})")

    async def _mouse_right_click(self, args: dict) -> dict:
        x, y = self._scaled_xy(args)
        await asyncio.to_thread(self._pyautogui_click, x, y, 1, "right")
        return self._ok(f"Right-clicked ({x}, {y})")

    # ── mouse_move ────────────────────────────────────────────────

    async def _mouse_move(self, args: dict) -> dict:
        x, y = self._scaled_xy(args)
        await asyncio.to_thread(self._pyautogui_move, x, y)
        return self._ok(f"Moved to ({x}, {y})")

    # ── type_text ─────────────────────────────────────────────────

    async def _type_text(self, args: dict) -> dict:
        text = args.get("text", "")
        if not text:
            return self._err(400, "text is required")
        await asyncio.to_thread(self._do_type, text)
        preview = text[:80] + ("..." if len(text) > 80 else "")
        return self._ok(f"Typed: {preview}")

    # ── key_press ─────────────────────────────────────────────────

    async def _key_press(self, args: dict) -> dict:
        combo = args.get("keys", "") or args.get("key", "")
        if not combo:
            return self._err(400, "keys is required (e.g. 'cmd+c')")
        await asyncio.to_thread(self._do_hotkey, combo)
        return self._ok(f"Key combo: {combo}")

    # ── scroll ────────────────────────────────────────────────────

    async def _scroll(self, args: dict) -> dict:
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        direction = args.get("direction", "down")
        amount = int(args.get("amount", 3))
        sx, sy = scale_coordinates(x, y, self.scale) if (x or y) else (None, None)
        await asyncio.to_thread(self._do_scroll, sx, sy, direction, amount)
        return self._ok(f"Scrolled {direction} by {amount}")

    # ── cursor_position ───────────────────────────────────────────

    async def _cursor_position(self, args: dict) -> dict:
        pos = await asyncio.to_thread(self._get_cursor_pos)
        return {
            "success": True, "status_code": 200,
            "data": {"x": pos[0], "y": pos[1], "dpi_scale": self.scale},
            "error": None,
        }

    # ── window_list ───────────────────────────────────────────────

    async def _window_list(self, args: dict) -> dict:
        windows = await asyncio.to_thread(self._get_windows)
        return {
            "success": True, "status_code": 200,
            "data": {"windows": windows},
            "error": None,
        }

    # ── window_focus ──────────────────────────────────────────────

    async def _window_focus(self, args: dict) -> dict:
        title = args.get("title", "")
        if not title:
            return self._err(400, "title is required")
        ok = await asyncio.to_thread(self._focus_window, title)
        if ok:
            return self._ok(f"Focused window: {title}")
        return self._err(404, f"Window not found: {title}")

    # ── internal helpers ──────────────────────────────────────────

    def _scaled_xy(self, args: dict) -> Tuple[int, int]:
        raw_x = int(args.get("x", 0))
        raw_y = int(args.get("y", 0))
        return scale_coordinates(raw_x, raw_y, self.scale)

    @staticmethod
    def _ok(msg: str) -> dict:
        return {"success": True, "status_code": 200, "data": {"message": msg}, "error": None}

    @staticmethod
    def _err(code: int, msg: str) -> dict:
        return {"success": False, "status_code": code, "data": None, "error": msg}

    # ── pyautogui wrappers (run in thread) ────────────────────────

    @staticmethod
    def _pyautogui_click(x: int, y: int, clicks: int, button: str) -> None:
        import pyautogui
        pyautogui.click(x, y, clicks=clicks, button=button)

    @staticmethod
    def _pyautogui_move(x: int, y: int) -> None:
        import pyautogui
        pyautogui.moveTo(x, y)

    @staticmethod
    def _do_type(text: str) -> None:
        """Type text. Uses pyperclip + Cmd/Ctrl+V for non-ASCII."""
        import pyautogui
        if text.isascii():
            pyautogui.write(text, interval=0.02)
        else:
            try:
                import pyperclip
                pyperclip.copy(text)
                modifier = "command" if platform.system() == "Darwin" else "ctrl"
                pyautogui.hotkey(modifier, "v")
            except ImportError:
                pyautogui.write(text, interval=0.02)

    @staticmethod
    def _do_hotkey(combo: str) -> None:
        import pyautogui
        parts = [k.strip() for k in combo.split("+")]
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
        pyautogui.hotkey(*mapped)

    @staticmethod
    def _do_scroll(
        x: Optional[int], y: Optional[int], direction: str, amount: int,
    ) -> None:
        import pyautogui
        clicks = amount if direction == "up" else -amount
        if x is not None and y is not None:
            pyautogui.scroll(clicks, x=x, y=y)
        else:
            pyautogui.scroll(clicks)

    @staticmethod
    def _get_cursor_pos() -> Tuple[int, int]:
        import pyautogui
        pos = pyautogui.position()
        return (pos.x, pos.y)

    @staticmethod
    def _get_windows() -> List[dict]:
        """List visible windows with titles and bounds (macOS only for now)."""
        if platform.system() != "Darwin":
            return []
        try:
            script = (
                'tell application "System Events" to get '
                '{name, position, size} of every window of every process '
                'whose visible is true'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            windows: List[dict] = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    windows.append({"raw": line})
            return windows
        except Exception:
            return []

    @staticmethod
    def _focus_window(title: str) -> bool:
        if platform.system() == "Darwin":
            script = (
                f'tell application "System Events"\n'
                f'  set targetProc to first process whose visible is true '
                f'and (name of every window contains "{title}")\n'
                f'  set frontmost of targetProc to true\n'
                f'end tell'
            )
            try:
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True, timeout=5,
                )
                return result.returncode == 0
            except Exception:
                pass

            try:
                result = subprocess.run(
                    ["osascript", "-e",
                     f'tell application "{title}" to activate'],
                    capture_output=True, text=True, timeout=5,
                )
                return result.returncode == 0
            except Exception:
                return False
        elif platform.system() == "Linux":
            if shutil.which("wmctrl"):
                try:
                    result = subprocess.run(
                        ["wmctrl", "-a", title],
                        capture_output=True, text=True, timeout=5,
                    )
                    return result.returncode == 0
                except Exception:
                    pass
            if shutil.which("xdotool"):
                try:
                    result = subprocess.run(
                        ["xdotool", "search", "--name", title, "windowactivate"],
                        capture_output=True, text=True, timeout=5,
                    )
                    return result.returncode == 0
                except Exception:
                    pass
        return False
