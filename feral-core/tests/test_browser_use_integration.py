"""
Browser automation integration tests — stubbed CDP server via aiohttp.
Skipped unless FERAL_BROWSER_TEST=1 to keep CI fast.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    os.environ.get("FERAL_BROWSER_TEST") != "1",
    reason="set FERAL_BROWSER_TEST=1 to run browser integration tests",
)
async def test_cdp_connect_get_page_info_and_disconnect():
    """Stub a minimal CDP HTTP+WS server, verify CDPConnection lifecycle."""
    import aiohttp
    from aiohttp import web

    async def json_version(request):
        return web.json_response({
            "webSocketDebuggerUrl": f"ws://127.0.0.1:{server_port}/devtools/browser",
        })

    async def json_list(request):
        return web.json_response([
            {"id": "page1", "type": "page", "title": "Test", "url": "about:blank",
             "webSocketDebuggerUrl": f"ws://127.0.0.1:{server_port}/devtools/page/1"},
        ])

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                resp = {"id": data["id"], "result": {}}
                method = data.get("method", "")
                if method == "Runtime.evaluate":
                    resp["result"] = {"result": {"value": '{"url":"about:blank","title":"Test"}'}}
                await ws.send_json(resp)
        return ws

    app = web.Application()
    app.router.add_get("/json/version", json_version)
    app.router.add_get("/json", json_list)
    app.router.add_get("/devtools/browser", ws_handler)
    app.router.add_get("/devtools/page/1", ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server_port = site._server.sockets[0].getsockname()[1]

    try:
        from skills.impl.browser_use import CDPConnection
        cdp = CDPConnection(host="127.0.0.1", port=server_port)
        connected = await cdp.connect()
        assert connected is True
        assert cdp.connected

        result = await cdp.send_command("Runtime.evaluate", {
            "expression": "JSON.stringify({url: location.href, title: document.title})",
            "returnByValue": True,
        })
        assert "result" in result

        await cdp.disconnect()
        assert not cdp.connected
    finally:
        await runner.cleanup()


async def test_browser_controller_handles_cdp_failure_gracefully():
    """When CDP is unreachable, initialize() returns False."""
    from skills.impl.browser_use import BrowserController

    bc = BrowserController()
    with patch.object(bc._cdp, "connect", return_value=False):
        with patch.object(bc, "_auto_launch_chrome", return_value=False):
            result = await bc.initialize()
            assert result is False


async def test_browser_get_page_info_fallback():
    """get_page_info returns empty dict when not connected."""
    from skills.impl.browser_use import BrowserController

    bc = BrowserController()
    info = await bc.get_page_info()
    assert info == {"url": "", "title": ""}
