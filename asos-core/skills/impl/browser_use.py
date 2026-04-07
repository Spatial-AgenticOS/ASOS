"""
THEORA Browser Control — CDP + Playwright
===========================================
Real browser automation via Chrome DevTools Protocol.

- Raw CDP for screenshots, navigation, and JS evaluation
- ARIA accessibility snapshots for agent-readable page structure
- Playwright bridge for reliable click/type/fill interactions
- Screenshot pipeline: resize + compress for VLM analysis
"""

from __future__ import annotations
import asyncio
import base64
import io
import json
import logging
import os
import re
from typing import Optional
from uuid import uuid4

logger = logging.getLogger("theora.browser")

CDP_PORT = int(os.getenv("THEORA_CDP_PORT", "9222"))
CDP_HOST = os.getenv("THEORA_CDP_HOST", "localhost")
MAX_SCREENSHOT_WIDTH = 1920
JPEG_QUALITY = 75


class CDPConnection:
    """Low-level Chrome DevTools Protocol connection via WebSocket."""

    def __init__(self, host: str = CDP_HOST, port: int = CDP_PORT):
        self._host = host
        self._port = port
        self._ws = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None
        self._connected = False
        self._page_ws_url: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connect to Chrome CDP endpoint."""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://{self._host}:{self._port}/json/version",
                    timeout=5.0,
                )
                info = resp.json()
                self._page_ws_url = info.get("webSocketDebuggerUrl")

            if not self._page_ws_url:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"http://{self._host}:{self._port}/json",
                        timeout=5.0,
                    )
                    targets = resp.json()
                    pages = [t for t in targets if t.get("type") == "page"]
                    if pages:
                        self._page_ws_url = pages[0].get("webSocketDebuggerUrl")

            if not self._page_ws_url:
                logger.error("No CDP WebSocket URL found")
                return False

            import websockets
            self._ws = await websockets.connect(
                self._page_ws_url,
                max_size=50 * 1024 * 1024,
                ping_interval=20,
            )
            self._connected = True
            self._recv_task = asyncio.create_task(self._receive_loop())
            logger.info(f"CDP connected: {self._page_ws_url}")
            return True

        except Exception as e:
            logger.error(f"CDP connection failed: {e}")
            return False

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

    async def send_command(self, method: str, params: dict = None, timeout: float = 30.0) -> dict:
        """Send a CDP command and wait for the response."""
        if not self._connected or not self._ws:
            raise ConnectionError("Not connected to CDP")

        self._msg_id += 1
        msg_id = self._msg_id
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        await self._ws.send(json.dumps(msg))
        result = await asyncio.wait_for(future, timeout=timeout)
        return result

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                    msg_id = msg.get("id")
                    if msg_id and msg_id in self._pending:
                        future = self._pending.pop(msg_id)
                        if "error" in msg:
                            future.set_exception(Exception(msg["error"].get("message", str(msg["error"]))))
                        else:
                            future.set_result(msg.get("result", {}))
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"CDP receive error: {e}")
            self._connected = False


class BrowserController:
    """
    High-level browser control combining CDP and Playwright.
    Registered as an orchestrator skill for the agent to use.
    """

    def __init__(self):
        self._cdp = CDPConnection()
        self._playwright = None
        self._browser = None
        self._page = None
        self._aria_refs: dict[str, dict] = {}

    @property
    def connected(self) -> bool:
        return self._cdp.connected

    async def initialize(self) -> bool:
        """Connect to Chrome CDP and optionally Playwright."""
        cdp_ok = await self._cdp.connect()
        if not cdp_ok:
            logger.warning("CDP not available — browser control disabled. "
                           "Start Chrome with: google-chrome --remote-debugging-port=9222")
            return False

        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            self._browser = await pw.chromium.connect_over_cdp(
                f"http://{CDP_HOST}:{CDP_PORT}",
            )
            contexts = self._browser.contexts
            if contexts:
                pages = contexts[0].pages
                self._page = pages[0] if pages else await contexts[0].new_page()
            else:
                ctx = await self._browser.new_context()
                self._page = await ctx.new_page()
            logger.info("Playwright connected via CDP")
        except Exception as e:
            logger.info(f"Playwright not available (CDP-only mode): {e}")

        return True

    async def navigate(self, url: str) -> dict:
        """Navigate to a URL."""
        try:
            if self._page:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            else:
                await self._cdp.send_command("Page.navigate", {"url": url})
                await asyncio.sleep(2)
            return {"success": True, "url": url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def screenshot(self, full_page: bool = False) -> dict:
        """Capture a screenshot, resize and compress for VLM."""
        try:
            if self._page:
                raw = await self._page.screenshot(full_page=full_page, type="jpeg", quality=JPEG_QUALITY)
            else:
                result = await self._cdp.send_command("Page.captureScreenshot", {
                    "format": "jpeg", "quality": JPEG_QUALITY,
                })
                raw = base64.b64decode(result["data"])

            img_b64 = self._compress_image(raw)
            return {"success": True, "image_b64": img_b64, "format": "jpeg"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def snapshot(self) -> dict:
        """Get ARIA accessibility tree as structured text."""
        try:
            result = await self._cdp.send_command("Accessibility.getFullAXTree")
            nodes = result.get("nodes", [])
            self._aria_refs.clear()
            text = self._build_aria_text(nodes)
            return {"success": True, "aria_tree": text, "ref_count": len(self._aria_refs)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def click(self, ref_or_selector: str) -> dict:
        """Click an element by ARIA ref or CSS selector."""
        try:
            if self._page:
                if ref_or_selector.startswith("ax"):
                    node_info = self._aria_refs.get(ref_or_selector)
                    if node_info and node_info.get("selector"):
                        await self._page.click(node_info["selector"], timeout=5000)
                    else:
                        await self._page.click(f"text={ref_or_selector}", timeout=5000)
                else:
                    await self._page.click(ref_or_selector, timeout=5000)
            else:
                await self._cdp_click(ref_or_selector)
            return {"success": True, "clicked": ref_or_selector}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def type_text(self, ref_or_selector: str, text: str) -> dict:
        """Type text into an element."""
        try:
            if self._page:
                if ref_or_selector.startswith("ax"):
                    node_info = self._aria_refs.get(ref_or_selector)
                    if node_info and node_info.get("selector"):
                        await self._page.fill(node_info["selector"], text, timeout=5000)
                    else:
                        await self._page.type(f"text={ref_or_selector}", text)
                else:
                    await self._page.fill(ref_or_selector, text, timeout=5000)
            else:
                await self._cdp.send_command("Input.dispatchKeyEvent", {
                    "type": "keyDown", "text": text,
                })
            return {"success": True, "typed": text[:50]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def fill(self, ref_or_selector: str, value: str) -> dict:
        """Fill a form field (clears first, then types)."""
        return await self.type_text(ref_or_selector, value)

    async def evaluate(self, js_code: str) -> dict:
        """Execute JavaScript in the page context."""
        try:
            if self._page:
                result = await self._page.evaluate(js_code)
            else:
                resp = await self._cdp.send_command("Runtime.evaluate", {
                    "expression": js_code, "returnByValue": True,
                })
                result = resp.get("result", {}).get("value")
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def scroll(self, direction: str = "down", amount: int = 500) -> dict:
        """Scroll the page."""
        try:
            dx, dy = 0, amount if direction == "down" else -amount
            if direction == "right":
                dx, dy = amount, 0
            elif direction == "left":
                dx, dy = -amount, 0
            if self._page:
                await self._page.evaluate(f"window.scrollBy({dx}, {dy})")
            else:
                await self._cdp.send_command("Input.dispatchMouseEvent", {
                    "type": "mouseWheel", "x": 400, "y": 400, "deltaX": dx, "deltaY": dy,
                })
            return {"success": True, "direction": direction, "amount": amount}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def select(self, ref_or_selector: str, value: str) -> dict:
        """Select an option from a dropdown."""
        try:
            if self._page:
                await self._page.select_option(ref_or_selector, value, timeout=5000)
            else:
                await self.evaluate(
                    f"document.querySelector('{ref_or_selector}').value = '{value}'"
                )
            return {"success": True, "selected": value}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def wait(self, ms: int = 1000) -> dict:
        """Wait for a specified duration."""
        await asyncio.sleep(ms / 1000.0)
        return {"success": True, "waited_ms": ms}

    async def get_page_info(self) -> dict:
        """Get current page URL and title."""
        try:
            if self._page:
                return {
                    "url": self._page.url,
                    "title": await self._page.title(),
                }
            result = await self._cdp.send_command("Runtime.evaluate", {
                "expression": "JSON.stringify({url: location.href, title: document.title})",
                "returnByValue": True,
            })
            return json.loads(result.get("result", {}).get("value", "{}"))
        except Exception:
            return {"url": "", "title": ""}

    async def close(self):
        await self._cdp.disconnect()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass

    def _build_aria_text(self, nodes: list[dict], max_depth: int = 10) -> str:
        """Convert AX tree nodes to readable text with assigned refs."""
        lines = []
        ref_counter = 0

        for node in nodes[:500]:
            role = node.get("role", {}).get("value", "")
            name = node.get("name", {}).get("value", "")
            if not role or role in ("none", "generic", "InlineTextBox"):
                continue

            ref_id = f"ax{ref_counter}"
            ref_counter += 1

            backend_id = node.get("backendDOMNodeId")
            self._aria_refs[ref_id] = {
                "node_id": node.get("nodeId", ""),
                "backend_id": backend_id,
                "role": role,
                "name": name,
                "selector": "",
            }

            indent = "  " * min(node.get("depth", 0), max_depth)
            desc = f"[{ref_id}] {role}"
            if name:
                desc += f': "{name}"'

            props = node.get("properties", [])
            for p in props:
                pname = p.get("name", "")
                pval = p.get("value", {}).get("value", "")
                if pname in ("disabled", "checked", "selected", "expanded") and pval:
                    desc += f" ({pname}={pval})"

            lines.append(f"{indent}{desc}")

        return "\n".join(lines) if lines else "(empty page)"

    def _compress_image(self, raw_bytes: bytes) -> str:
        """Resize and compress image for VLM analysis."""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw_bytes))
            if img.width > MAX_SCREENSHOT_WIDTH:
                ratio = MAX_SCREENSHOT_WIDTH / img.width
                new_h = int(img.height * ratio)
                img = img.resize((MAX_SCREENSHOT_WIDTH, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            return base64.b64encode(raw_bytes).decode()

    async def _cdp_click(self, selector: str):
        """Click via CDP (fallback when Playwright isn't available)."""
        result = await self._cdp.send_command("Runtime.evaluate", {
            "expression": f"""
                (function() {{
                    const el = document.querySelector('{selector}');
                    if (!el) return null;
                    const rect = el.getBoundingClientRect();
                    return {{ x: rect.x + rect.width/2, y: rect.y + rect.height/2 }};
                }})()
            """,
            "returnByValue": True,
        })
        coords = result.get("result", {}).get("value")
        if not coords:
            raise Exception(f"Element not found: {selector}")

        x, y = coords["x"], coords["y"]
        for event_type in ("mousePressed", "mouseReleased"):
            await self._cdp.send_command("Input.dispatchMouseEvent", {
                "type": event_type, "x": x, "y": y, "button": "left", "clickCount": 1,
            })


def get_browser_skill_manifest() -> dict:
    """Return the skill manifest for browser control."""
    return {
        "skill_id": "browser",
        "name": "Browser Control",
        "description": "Control web browsers — navigate, click, type, screenshot, read page content",
        "safety_level": "WARN",
        "endpoints": [
            {"id": "navigate", "description": "Navigate to a URL", "params": [
                {"name": "url", "type": "string", "required": True, "description": "URL to navigate to"},
            ]},
            {"id": "screenshot", "description": "Capture a screenshot of the current page", "params": [
                {"name": "full_page", "type": "boolean", "required": False, "description": "Capture full scrollable page"},
            ]},
            {"id": "snapshot", "description": "Get ARIA accessibility tree of the current page", "params": []},
            {"id": "click", "description": "Click an element by ref or CSS selector", "params": [
                {"name": "ref_or_selector", "type": "string", "required": True},
            ]},
            {"id": "type_text", "description": "Type text into an element", "params": [
                {"name": "ref_or_selector", "type": "string", "required": True},
                {"name": "text", "type": "string", "required": True},
            ]},
            {"id": "evaluate", "description": "Execute JavaScript in the page", "params": [
                {"name": "js_code", "type": "string", "required": True},
            ]},
            {"id": "scroll", "description": "Scroll the page", "params": [
                {"name": "direction", "type": "string", "required": False, "description": "up/down/left/right"},
                {"name": "amount", "type": "integer", "required": False},
            ]},
            {"id": "get_page_info", "description": "Get current page URL and title", "params": []},
        ],
    }
