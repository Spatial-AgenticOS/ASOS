"""MCP JSON-RPC and management endpoints."""

from fastapi import APIRouter

from api.state import state, _log_activity
from mcp.client import MCPServerConnection

router = APIRouter()


@router.post("/mcp")
async def mcp_jsonrpc(body: dict):
    """MCP JSON-RPC endpoint for external MCP clients."""
    if not state.mcp_server:
        return {"jsonrpc": "2.0", "error": {"code": -32603, "message": "MCP server not initialized"}, "id": body.get("id")}
    return await state.mcp_server.handle_jsonrpc(body)


@router.get("/api/mcp/status")
async def mcp_status():
    """MCP server and client status."""
    server_tools = len(state.mcp_server.handle_tools_list()["tools"]) if state.mcp_server else 0
    client_stats = state.mcp_client.stats if state.mcp_client else {}
    projection = state.mcp_server.projection_status() if state.mcp_server else {}
    return {
        "server": {"tools_exposed": server_tools, "skill_projection": projection},
        "client": client_stats,
    }


# ── PR 11 gap-fill: operator toggle for skill projection ───────────


@router.get("/api/mcp/projection")
async def mcp_projection_status():
    """Inspect the current FERAL-skill MCP projection state.

    Returns ``{enabled, ready, projected_count, registry_wired,
    executor_wired}``. Used by the Settings UI to truthfully report
    whether external MCP clients can call FERAL skills."""
    if not state.mcp_server:
        return {"error": "MCP server not initialised"}
    return state.mcp_server.projection_status()


@router.post("/api/mcp/projection")
async def mcp_projection_toggle(body: dict | None = None):
    """Enable or disable FERAL-skill projection at runtime.

    Body: ``{"enabled": true|false}``. Re-wires the server's
    skill_registry + skill_executor from BrainState in case they
    weren't ready at boot time. Returns the live projection status."""
    if not state.mcp_server:
        return {"error": "MCP server not initialised"}
    body = body or {}
    enabled = bool(body.get("enabled", True))
    return state.mcp_server.configure_skill_projection(
        skill_registry=state.skill_registry,
        skill_executor=state.skill_executor,
        enabled=enabled,
    )


@router.get("/api/mcp/tools")
async def mcp_external_tools():
    """List all tools from connected external MCP servers."""
    if not state.mcp_client:
        return {"tools": []}
    return {"tools": state.mcp_client.all_tools()}


@router.get("/api/mcp/registry")
async def mcp_registry():
    """List all known MCP servers with status."""
    from mcp.registry import MCPServerRegistry
    registry = MCPServerRegistry(mcp_client=state.mcp_client)
    return {"servers": registry.list_known()}


@router.post("/api/mcp/connect")
async def mcp_connect(body: dict):
    """Connect to a new MCP server at runtime."""
    if not state.mcp_client:
        return {"error": "MCP client not initialized"}
    name = body.get("name", "unnamed")
    conn = MCPServerConnection(name, body)
    success = await conn.connect()
    if success:
        state.mcp_client._servers[name] = conn
        _log_activity("mcp_connected", f"MCP server '{name}' connected ({len(conn.tools)} tools)")
        return {"success": True, "tools": len(conn.tools)}
    return {"success": False, "error": f"Failed to connect to MCP server '{name}'"}
