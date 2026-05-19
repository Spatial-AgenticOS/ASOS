"""End-to-end tests for the MCP Streamable HTTP transport
(audit-r12 D6, spec rev 2025-06-18).

Pre-r12 ``MCPServerConnection._connect_http`` was a stub that set
``self._connected = True`` and never spoke protocol; every subsequent
``call_tool`` returned ``{"error": "No response"}`` because the stdio
``_send_request`` code path silently failed when ``self._process`` was
``None``. This suite pins the new behaviour by spinning up an
in-process FastAPI server that simulates a real MCP server: client
and server speak JSON-RPC over POST with proper ``Mcp-Session-Id``,
``MCP-Protocol-Version`` handling, plus JSON and SSE response shapes.

No mocks at the transport layer — ``httpx.AsyncClient`` talks to a
genuine ASGI app via :class:`httpx.AsyncHTTPTransport` over a TCP
socket, exactly as production traffic would.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import pytest

_FERAL_CORE = Path(__file__).resolve().parent.parent
if str(_FERAL_CORE) not in sys.path:
    sys.path.insert(0, str(_FERAL_CORE))

# Skip the entire module if uvicorn isn't available (it's part of the
# top-level FastAPI dep set, so it almost always is).
uvicorn = pytest.importorskip("uvicorn")
fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, Response, StreamingResponse  # noqa: E402

from mcp.client import (  # noqa: E402
    MCPServerConfig,
    MCPServerConnection,
    _MCP_PROTOCOL_VERSION,
)


# ─────────────────────────────────────────────
# In-process MCP-over-HTTP server fixture
# ─────────────────────────────────────────────


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _MCPSimServer:
    """Minimal Streamable HTTP MCP server for testing.

    Implements just enough of the spec rev 2025-06-18 to exercise the
    client's full happy + sad paths:

    * ``initialize`` returns a JSON-RPC response and stamps the reply
      with an ``Mcp-Session-Id``.
    * ``tools/list`` returns one tool via JSON response.
    * ``resources/list`` returns one resource via JSON response.
    * ``tools/call`` returns a JSON response OR, when the caller flips
      ``use_sse`` to True, streams the reply via SSE (multiple data:
      events before the matching response).
    * ``notifications/*`` and JSON-RPC responses get HTTP 202.
    * Stale session id -> HTTP 404.
    * ``DELETE`` -> 200 (graceful tear-down).
    """

    def __init__(self) -> None:
        self.use_sse = False
        self.next_session_id = "sim-session-id-1"
        self.active_sessions: set[str] = set()
        self.received_protocol_versions: list[Optional[str]] = []
        self.notifications_received: list[str] = []

    def make_app(self) -> FastAPI:
        app = FastAPI()

        @app.post("/mcp")
        async def handle_post(request: Request):
            self.received_protocol_versions.append(
                request.headers.get("MCP-Protocol-Version"),
            )
            session_in = request.headers.get("Mcp-Session-Id")
            body = await request.body()
            try:
                msg = json.loads(body.decode("utf-8"))
            except Exception:
                return JSONResponse(
                    {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
                    status_code=400,
                )

            # Notification or response: must be 202 Accepted, no body.
            if "id" not in msg:
                self.notifications_received.append(msg.get("method", "?"))
                return Response(status_code=202)

            method = msg.get("method")
            req_id = msg.get("id")

            # Reject requests carrying a stale session id with HTTP 404
            # so the client's "rotate session" path is exercised. We
            # do this BEFORE the initialize special-case so the test
            # can drive the rotation path explicitly.
            if (
                session_in
                and session_in not in self.active_sessions
                and method != "initialize"
            ):
                return Response(status_code=404)

            if method == "initialize":
                sid = self.next_session_id
                self.active_sessions.add(sid)
                payload = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": _MCP_PROTOCOL_VERSION,
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": "sim", "version": "0.1"},
                    },
                }
                return JSONResponse(payload, headers={"Mcp-Session-Id": sid})

            if method == "tools/list":
                payload = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echoes its input back",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"msg": {"type": "string"}},
                                },
                            },
                        ],
                    },
                }
                return JSONResponse(payload)

            if method == "resources/list":
                payload = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "resources": [
                            {"uri": "sim://hello", "name": "Hello", "mimeType": "text/plain"},
                        ],
                    },
                }
                return JSONResponse(payload)

            if method == "tools/call":
                args = msg.get("params", {}).get("arguments", {})
                payload = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": args.get("msg", "")}]},
                }
                if self.use_sse:
                    async def _stream() -> AsyncIterator[bytes]:
                        # First push a server-initiated notification —
                        # the client must skip it and keep reading.
                        notif = {
                            "jsonrpc": "2.0",
                            "method": "notifications/progress",
                            "params": {"phase": "running"},
                        }
                        yield f"data: {json.dumps(notif)}\n\n".encode("utf-8")
                        await asyncio.sleep(0)
                        # Then the actual response.
                        yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                    return StreamingResponse(_stream(), media_type="text/event-stream")
                return JSONResponse(payload)

            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown method {method}"},
                },
            )

        @app.delete("/mcp")
        async def handle_delete(request: Request):
            sid = request.headers.get("Mcp-Session-Id")
            if sid:
                self.active_sessions.discard(sid)
            return Response(status_code=200)

        return app


@asynccontextmanager
async def _run_sim_server(sim: _MCPSimServer):
    port = _pick_free_port()
    app = sim.make_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait for uvicorn to flip its ``started`` flag.
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_connect_initialize_and_discover():
    sim = _MCPSimServer()
    async with _run_sim_server(sim) as url:
        cfg = MCPServerConfig(name="sim", transport="http", url=url)
        conn = MCPServerConnection("sim", cfg)
        ok = await conn.connect()
        assert ok is True
        assert conn.is_connected is True
        assert conn._session_id == "sim-session-id-1"
        # Tools and resources discovered during connect.
        assert any(t["name"] == "echo" for t in conn.tools)
        assert any(r["uri"] == "sim://hello" for r in conn.resources)
        await conn.disconnect()
        # After disconnect, the simulator dropped the session id.
        assert "sim-session-id-1" not in sim.active_sessions


@pytest.mark.asyncio
async def test_http_tool_call_json_response_roundtrip():
    sim = _MCPSimServer()
    async with _run_sim_server(sim) as url:
        cfg = MCPServerConfig(name="sim", transport="http", url=url)
        conn = MCPServerConnection("sim", cfg)
        assert await conn.connect() is True
        result = await conn.call_tool("echo", {"msg": "hello world"})
        assert "content" in result
        assert result["content"][0]["text"] == "hello world"
        await conn.disconnect()


@pytest.mark.asyncio
async def test_http_tool_call_sse_response_roundtrip():
    sim = _MCPSimServer()
    sim.use_sse = True
    async with _run_sim_server(sim) as url:
        cfg = MCPServerConfig(name="sim", transport="http", url=url)
        conn = MCPServerConnection("sim", cfg)
        assert await conn.connect() is True
        result = await conn.call_tool("echo", {"msg": "streamed"})
        # The server intentionally sent a progress notification BEFORE
        # the response; the client must skip it and return the actual
        # response. If this fails the SSE reader is leaking events.
        assert result.get("content")
        assert result["content"][0]["text"] == "streamed"
        await conn.disconnect()


@pytest.mark.asyncio
async def test_http_protocol_version_header_after_init_only():
    sim = _MCPSimServer()
    async with _run_sim_server(sim) as url:
        cfg = MCPServerConfig(name="sim", transport="http", url=url)
        conn = MCPServerConnection("sim", cfg)
        assert await conn.connect() is True
        await conn.call_tool("echo", {"msg": "v"})
        # The very first request (initialize) MUST NOT advertise a
        # protocol version per spec § Protocol Version Header — the
        # version isn't negotiated yet. Every subsequent request,
        # including ``notifications/initialized``, MUST carry the
        # negotiated version.
        versions = sim.received_protocol_versions
        assert versions[0] is None, versions
        assert all(v == _MCP_PROTOCOL_VERSION for v in versions[1:]), versions
        await conn.disconnect()


@pytest.mark.asyncio
async def test_http_session_404_returns_jsonrpc_error_envelope():
    sim = _MCPSimServer()
    async with _run_sim_server(sim) as url:
        cfg = MCPServerConfig(name="sim", transport="http", url=url)
        conn = MCPServerConnection("sim", cfg)
        assert await conn.connect() is True
        # Server-side: forget the session.
        sim.active_sessions.clear()
        # Next request: server returns 404; client must surface a
        # JSON-RPC error rather than a None.
        result = await conn.call_tool("echo", {"msg": "ignored"})
        assert "error" in result
        # And the session id must have been dropped so a manual
        # reconnect can rotate without conflict.
        assert conn._session_id is None
        await conn.disconnect()


@pytest.mark.asyncio
async def test_http_initialized_notification_sent_as_202():
    sim = _MCPSimServer()
    async with _run_sim_server(sim) as url:
        cfg = MCPServerConfig(name="sim", transport="http", url=url)
        conn = MCPServerConnection("sim", cfg)
        assert await conn.connect() is True
        assert "notifications/initialized" in sim.notifications_received
        await conn.disconnect()


@pytest.mark.asyncio
async def test_http_connect_without_url_fails_loud():
    cfg = MCPServerConfig(name="oops", transport="http", url="")
    conn = MCPServerConnection("oops", cfg)
    ok = await conn.connect()
    assert ok is False
    assert conn.is_connected is False


@pytest.mark.asyncio
async def test_http_unreachable_server_returns_false_not_silent_true():
    # Random unbound port — connection MUST fail fast and return
    # False, not the pre-r12 silent ``self._connected = True``.
    port = _pick_free_port()
    cfg = MCPServerConfig(
        name="dead", transport="http", url=f"http://127.0.0.1:{port}/mcp",
    )
    conn = MCPServerConnection("dead", cfg)
    ok = await conn.connect()
    assert ok is False
    assert conn.is_connected is False
