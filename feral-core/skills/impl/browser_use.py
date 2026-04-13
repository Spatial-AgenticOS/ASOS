"""
FERAL Browser Control — CDP + Playwright
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
from typing import Optional, Callable
from uuid import uuid4

logger = logging.getLogger("feral.browser")

CDP_PORT = int(os.getenv("FERAL_CDP_PORT", "9222"))
CDP_HOST = os.getenv("FERAL_CDP_HOST", "localhost")
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
        self._event_listeners: list[Callable[[dict], None]] = []

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
            for _attempt in range(3):
                try:
                    self._ws = await websockets.connect(
                        self._page_ws_url,
                        max_size=50 * 1024 * 1024,
                        ping_interval=20,
                    )
                    break
                except Exception:
                    if _attempt == 2:
                        raise
                    await asyncio.sleep(2 ** _attempt)
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

    def add_event_listener(self, listener: Callable[[dict], None]):
        """Subscribe to raw CDP event messages (messages without request IDs)."""
        self._event_listeners.append(listener)

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
                    elif msg.get("method"):
                        for listener in self._event_listeners:
                            try:
                                maybe_coro = listener(msg)
                                if asyncio.iscoroutine(maybe_coro):
                                    asyncio.create_task(maybe_coro)
                            except Exception:
                                continue
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
        self._console_logs: list[dict] = []
        self._console_listener_attached = False

    @property
    def connected(self) -> bool:
        return self._cdp.connected

    async def initialize(self) -> bool:
        """Connect to Chrome CDP and optionally Playwright. Auto-launches Chrome if needed."""
        cdp_ok = await self._cdp.connect()
        if not cdp_ok:
            launched = await self._auto_launch_chrome()
            if launched:
                await asyncio.sleep(2.0)
                cdp_ok = await self._cdp.connect()
            if not cdp_ok:
                logger.warning("CDP not available — browser control disabled.")
                return False

        if not self._console_listener_attached:
            self._cdp.add_event_listener(self._on_cdp_event)
            self._console_listener_attached = True
        try:
            await self._cdp.send_command("Runtime.enable")
            await self._cdp.send_command("Log.enable")
            await self._cdp.send_command("Page.enable")
        except Exception as e:
            logger.debug(f"CDP event channels setup skipped: {e}")

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

    async def _auto_launch_chrome(self) -> bool:
        """Try to launch Chrome/Chromium with remote debugging enabled."""
        import platform
        import shutil
        system = platform.system()

        candidates = []
        if system == "Darwin":
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ]
        elif system == "Linux":
            for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
                p = shutil.which(name)
                if p:
                    candidates.append(p)
        else:
            for name in ("chrome.exe", "chromium.exe"):
                p = shutil.which(name)
                if p:
                    candidates.append(p)

        chrome_bin = None
        for c in candidates:
            if os.path.isfile(c):
                chrome_bin = c
                break

        if not chrome_bin:
            logger.warning("No Chrome/Chromium binary found for auto-launch")
            return False

        from config.loader import feral_home
        profile_dir = str(feral_home() / "chrome-profile")

        args = [
            chrome_bin,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        try:
            import subprocess
            self._chrome_proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"Auto-launched Chrome (pid={self._chrome_proc.pid}) on port {CDP_PORT}")
            return True
        except Exception as e:
            logger.error(f"Chrome auto-launch failed: {e}")
            return False

    async def list_tabs(self) -> list[dict]:
        """List all open browser tabs via CDP HTTP API."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{CDP_HOST}:{CDP_PORT}/json/list") as resp:
                    tabs = await resp.json()
                    return [
                        {"id": t.get("id"), "title": t.get("title", ""), "url": t.get("url", "")}
                        for t in tabs if t.get("type") == "page"
                    ]
        except Exception as e:
            logger.warning(f"Failed to list tabs: {e}")
            return []

    async def switch_tab(self, tab_id: str) -> bool:
        """Activate a tab by its CDP target id."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{CDP_HOST}:{CDP_PORT}/json/activate/{tab_id}") as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning(f"Failed to switch tab: {e}")
            return False

    async def new_tab(self, url: str = "about:blank") -> Optional[str]:
        """Open a new browser tab."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{CDP_HOST}:{CDP_PORT}/json/new?{url}") as resp:
                    data = await resp.json()
                    return data.get("id")
        except Exception as e:
            logger.warning(f"Failed to open new tab: {e}")
            return None

    async def close_tab(self, tab_id: str) -> bool:
        """Close a browser tab by its CDP target id."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{CDP_HOST}:{CDP_PORT}/json/close/{tab_id}") as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning(f"Failed to close tab: {e}")
            return False

    def _on_cdp_event(self, event: dict):
        """Capture console/log events so the agent can inspect browser errors."""
        method = event.get("method", "")
        params = event.get("params", {}) or {}

        if method == "Runtime.consoleAPICalled":
            args = []
            for arg in params.get("args", []):
                val = arg.get("value")
                if val is None:
                    val = arg.get("description") or arg.get("type")
                if val is not None:
                    args.append(str(val))
            self._append_console_log({
                "source": "runtime",
                "level": params.get("type", "log"),
                "text": " ".join(args).strip(),
                "timestamp": params.get("timestamp"),
            })
        elif method == "Log.entryAdded":
            entry = params.get("entry", {}) or {}
            self._append_console_log({
                "source": "log",
                "level": entry.get("level", "info"),
                "text": entry.get("text", ""),
                "timestamp": entry.get("timestamp"),
                "url": entry.get("url"),
            })

    def _append_console_log(self, entry: dict):
        if not entry.get("text"):
            return
        self._console_logs.append(entry)
        if len(self._console_logs) > 500:
            self._console_logs = self._console_logs[-500:]

    async def navigate(self, url: str) -> dict:
        """Navigate to a URL and wait for load."""
        try:
            if self._page:
                resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                status = resp.status if resp else 0
            else:
                await self._cdp.send_command("Page.enable")
                await self._cdp.send_command("Page.navigate", {"url": url})
                # Wait for Page.loadEventFired or timeout
                try:
                    await asyncio.wait_for(
                        self._cdp.send_command("Page.getNavigationHistory"),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    pass
                status = 200
            title = await self._get_title()
            return {"success": True, "url": url, "status": status, "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _get_title(self) -> str:
        try:
            if self._page:
                return await self._page.title()
            r = await self._cdp.send_command("Runtime.evaluate", {
                "expression": "document.title", "returnByValue": True,
            })
            return r.get("result", {}).get("value", "")
        except Exception:
            return ""

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
        """Get ARIA accessibility tree as structured text with resolved selectors."""
        try:
            await self._cdp.send_command("DOM.enable")
            await self._cdp.send_command("Accessibility.enable")
            result = await self._cdp.send_command("Accessibility.getFullAXTree")
            nodes = result.get("nodes", [])
            self._aria_refs.clear()
            text = self._build_aria_text(nodes)
            # Resolve backend DOM node IDs to CSS selectors
            await self._resolve_aria_selectors()
            return {"success": True, "aria_tree": text, "ref_count": len(self._aria_refs)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _resolve_aria_selectors(self):
        """Resolve ARIA refs to CSS selectors via DOM.describeNode."""
        for ref_id, info in list(self._aria_refs.items()):
            backend_id = info.get("backend_id")
            if not backend_id or info.get("selector"):
                continue
            try:
                desc = await self._cdp.send_command("DOM.describeNode", {
                    "backendNodeId": backend_id, "depth": 0,
                })
                node = desc.get("node", {})
                tag = node.get("localName", "")
                attrs = node.get("attributes", [])
                attr_dict = dict(zip(attrs[::2], attrs[1::2])) if attrs else {}
                if attr_dict.get("id"):
                    info["selector"] = f"#{attr_dict['id']}"
                elif attr_dict.get("data-testid"):
                    info["selector"] = f'[data-testid="{attr_dict["data-testid"]}"]'
                elif tag and attr_dict.get("class"):
                    first_class = attr_dict["class"].split()[0]
                    info["selector"] = f"{tag}.{first_class}"
                elif tag and info.get("name"):
                    safe_name = info["name"].replace('"', '\\"')[:50]
                    info["selector"] = f'{tag}:has-text("{safe_name}")'
            except Exception:
                pass

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

    async def fill_form(self, fields: dict) -> dict:
        """Fill multiple fields in one action: {selector_or_ref: value}."""
        if not isinstance(fields, dict) or not fields:
            return {"success": False, "error": "fields must be a non-empty object mapping selector/ref to value"}

        filled: list[str] = []
        failed: dict[str, str] = {}
        for target, value in fields.items():
            result = await self.fill(str(target), "" if value is None else str(value))
            if result.get("success"):
                filled.append(str(target))
            else:
                failed[str(target)] = str(result.get("error", "fill failed"))

        return {
            "success": len(failed) == 0,
            "filled": filled,
            "failed": failed,
            "total": len(fields),
        }

    async def hover(self, ref_or_selector: str) -> dict:
        """Hover over an element by ARIA ref or selector."""
        try:
            selector = self._resolve_selector(ref_or_selector)
            if self._page:
                await self._page.hover(selector, timeout=5000)
            else:
                await self._cdp_hover(selector)
            return {"success": True, "hovered": ref_or_selector}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
            selector = self._resolve_selector(ref_or_selector)
            if self._page:
                await self._page.select_option(selector, value, timeout=5000)
            else:
                # Escape user input to prevent injection
                safe_sel = json.dumps(selector)
                safe_val = json.dumps(value)
                await self.evaluate(
                    f"(function(){{ var el = document.querySelector({safe_sel}); if(el) el.value = {safe_val}; }})()"
                )
            return {"success": True, "selected": value}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _resolve_selector(self, ref_or_selector: str) -> str:
        """Resolve an ARIA ref (ax0, ax1...) to a CSS selector."""
        if ref_or_selector.startswith("ax"):
            info = self._aria_refs.get(ref_or_selector, {})
            return info.get("selector") or ref_or_selector
        return ref_or_selector

    async def wait(self, ms: int = 1000) -> dict:
        """Wait for a specified duration."""
        await asyncio.sleep(ms / 1000.0)
        return {"success": True, "waited_ms": ms}

    async def get_console_logs(self, limit: int = 50, clear: bool = False) -> dict:
        """Return captured browser console logs."""
        try:
            bounded = max(1, min(int(limit), 500))
        except Exception:
            bounded = 50
        logs = self._console_logs[-bounded:]
        if clear:
            self._console_logs.clear()
        return {"success": True, "count": len(logs), "logs": logs}

    async def get_page_pdf(self, print_background: bool = True, landscape: bool = False) -> dict:
        """Export current page to PDF via CDP."""
        try:
            await self._cdp.send_command("Page.enable")
            result = await self._cdp.send_command("Page.printToPDF", {
                "printBackground": bool(print_background),
                "landscape": bool(landscape),
            })
            pdf_b64 = result.get("data", "")
            if not pdf_b64:
                return {"success": False, "error": "No PDF data returned by browser"}
            size_bytes = len(base64.b64decode(pdf_b64))
            return {"success": True, "pdf_b64": pdf_b64, "size_bytes": size_bytes}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
        x, y = await self._cdp_get_element_center(selector)
        for event_type in ("mousePressed", "mouseReleased"):
            await self._cdp.send_command("Input.dispatchMouseEvent", {
                "type": event_type, "x": x, "y": y, "button": "left", "clickCount": 1,
            })

    async def _cdp_hover(self, selector: str):
        """Move mouse over element center via CDP."""
        x, y = await self._cdp_get_element_center(selector)
        await self._cdp.send_command("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": x,
            "y": y,
        })

    async def _cdp_get_element_center(self, selector: str) -> tuple[float, float]:
        safe_selector = json.dumps(selector)
        result = await self._cdp.send_command("Runtime.evaluate", {
            "expression": (
                "(function() {"
                f"const el = document.querySelector({safe_selector});"
                "if (!el) return null;"
                "const rect = el.getBoundingClientRect();"
                "return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };"
                "})()"
            ),
            "returnByValue": True,
        })
        coords = result.get("result", {}).get("value")
        if not coords:
            raise Exception(f"Element not found: {selector}")
        return float(coords["x"]), float(coords["y"])


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
            {"id": "fill_form", "description": "Fill multiple form fields in one step", "params": [
                {"name": "fields", "type": "object", "required": True, "description": "Mapping: selector/ref -> value"},
            ]},
            {"id": "hover", "description": "Hover over an element to reveal menus/tooltips", "params": [
                {"name": "ref_or_selector", "type": "string", "required": True},
            ]},
            {"id": "evaluate", "description": "Execute JavaScript in the page", "params": [
                {"name": "js_code", "type": "string", "required": True},
            ]},
            {"id": "scroll", "description": "Scroll the page", "params": [
                {"name": "direction", "type": "string", "required": False, "description": "up/down/left/right"},
                {"name": "amount", "type": "integer", "required": False},
            ]},
            {"id": "get_console_logs", "description": "Read captured browser console logs", "params": [
                {"name": "limit", "type": "integer", "required": False, "description": "Max log entries to return"},
                {"name": "clear", "type": "boolean", "required": False, "description": "Clear logs after reading"},
            ]},
            {"id": "get_page_pdf", "description": "Export current page to PDF and return base64 bytes", "params": [
                {"name": "print_background", "type": "boolean", "required": False},
                {"name": "landscape", "type": "boolean", "required": False},
            ]},
            {"id": "get_page_info", "description": "Get current page URL and title", "params": []},
            {"id": "list_tabs", "description": "List all open browser tabs", "params": []},
            {"id": "switch_tab", "description": "Activate a browser tab by its id", "params": [
                {"name": "tab_id", "type": "string", "required": True, "description": "Tab id from list_tabs"},
            ]},
            {"id": "new_tab", "description": "Open a new browser tab", "params": [
                {"name": "url", "type": "string", "required": False, "description": "URL to open (default: blank)"},
            ]},
            {"id": "close_tab", "description": "Close a browser tab", "params": [
                {"name": "tab_id", "type": "string", "required": True, "description": "Tab id to close"},
            ]},
        ],
    }
