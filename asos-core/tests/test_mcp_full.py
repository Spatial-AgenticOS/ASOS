"""
Focused JSON-RPC and HTTP surface tests for `mcp.server.TheoraMCPServer`.

Validates initialization, MCP method routing over `handle_jsonrpc`, and the
FastAPI router factory used for HTTP transport.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp.server import TheoraMCPServer


class TestTheoraMCPServerCore:
    """Construction and protocol entrypoints."""

    def test_init_creates_instance(self) -> None:
        """Server stores optional dependencies and server metadata."""
        srv = TheoraMCPServer(device_registry=None, memory=None, perception=None)
        assert srv._devices is None
        assert srv._server_info["name"] == "theora"

    @pytest.mark.asyncio
    async def test_jsonrpc_tools_list_returns_tool_definitions(self) -> None:
        """`tools/list` JSON-RPC resolves to tool schemas."""
        srv = TheoraMCPServer()
        resp = await srv.handle_jsonrpc(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert "result" in resp
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "theora_list_devices" in names
        assert all("name" in t and "description" in t for t in tools)

    @pytest.mark.asyncio
    async def test_jsonrpc_tools_call_valid_tool_mocked_impl(self) -> None:
        """`tools/call` returns the underlying tool result (implementation mocked)."""
        srv = TheoraMCPServer()
        fake = {"content": [{"type": "text", "text": "mock-ok"}]}
        with patch.object(srv, "_call_list_devices", return_value=fake):
            resp = await srv.handle_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "theora_list_devices", "arguments": {}},
                }
            )
        assert resp.get("error") is None
        assert resp["result"] == fake

    @pytest.mark.asyncio
    async def test_jsonrpc_invalid_method_returns_error(self) -> None:
        """Unknown JSON-RPC methods yield a standard method-not-found error."""
        srv = TheoraMCPServer()
        resp = await srv.handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "skills/unknown",
                "params": {},
            }
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_get_http_routes_exposes_mcp_endpoints(self) -> None:
        """HTTP helper returns a router registering MCP and health routes."""
        srv = TheoraMCPServer()
        router = srv.get_http_routes()
        route_paths = [getattr(r, "path", None) for r in router.routes]
        assert any(p == "/mcp/" for p in route_paths if p)
        assert any(p == "/mcp/health" for p in route_paths if p)
