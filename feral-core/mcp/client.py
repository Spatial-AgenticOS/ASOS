"""
FERAL MCP Client — Consume Any MCP Server
=============================================
FERAL can connect to external MCP servers and use their tools.
This instantly gives FERAL access to thousands of existing tools
without writing any adapters.

Examples:
  - Connect to a GitHub MCP server → FERAL can manage repos
  - Connect to a Postgres MCP server → FERAL can query databases
  - Connect to a Notion MCP server → FERAL can manage pages
  - Connect to another FERAL instance → multi-Brain collaboration

Configuration via ~/.feral/mcp_servers.json:
{
  "servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "..."}
    }
  ]
}
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from config.loader import feral_home

logger = logging.getLogger("feral.mcp.client")


class MCPServerConnection:
    """A connection to a single external MCP server."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.transport = config.get("transport", "stdio")
        self._process: Optional[asyncio.subprocess.Process] = None
        self._tools: list[dict] = []
        self._resources: list[dict] = []
        self._request_id = 0
        self._connected = False
        self._request_failures = 0
        self._request_failure_fuse = max(
            1, int(os.environ.get("FERAL_MCP_REQUEST_FAILURE_FUSE", "3"))
        )

    async def connect(self) -> bool:
        # Reconnect path: tear down old process first to avoid zombie stdio
        # children holding stale pipes.
        if self._process is not None and self.transport == "stdio":
            await self.disconnect()
        if self.transport == "stdio":
            return await self._connect_stdio()
        elif self.transport == "http":
            self._connected = True
            self._request_failures = 0
            return True
        logger.warning(f"Unsupported transport: {self.transport}")
        return False

    async def _connect_stdio(self) -> bool:
        command = self.config.get("command", "")
        args = self.config.get("args", [])
        env = {**os.environ, **self.config.get("env", {})}

        try:
            self._process = await asyncio.create_subprocess_exec(
                command, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "feral", "version": "1.0.0"},
            })

            if init_result and "error" not in init_result:
                await self._send_notification("initialized", {})
                self._connected = True
                self._request_failures = 0
                await self._discover_tools()
                await self._discover_resources()
                logger.info(f"MCP server connected: {self.name} ({len(self._tools)} tools, {len(self._resources)} resources)")
                return True

        except FileNotFoundError:
            logger.error(f"MCP server command not found: {command}")
        except Exception as e:
            logger.error(f"MCP server connection failed ({self.name}): {e}")

        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._connected = False
        return False

    async def disconnect(self):
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
        self._process = None
        self._connected = False

    async def _discover_tools(self):
        result = await self._send_request("tools/list", {})
        if result and "result" in result:
            self._tools = result["result"].get("tools", [])

    async def _discover_resources(self):
        result = await self._send_request("resources/list", {})
        if result and "result" in result:
            self._resources = result["result"].get("resources", [])

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        if not self._connected:
            return {"error": f"MCP server {self.name} not connected"}
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result and "result" in result:
            return result["result"]
        return {"error": result.get("error", {}).get("message", "Unknown error") if result else "No response"}

    async def read_resource(self, uri: str) -> dict:
        if not self._connected:
            return {"error": f"MCP server {self.name} not connected"}
        result = await self._send_request("resources/read", {"uri": uri})
        if result and "result" in result:
            return result["result"]
        return {"error": "Failed to read resource"}

    async def _send_request(self, method: str, params: dict) -> Optional[dict]:
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None
        if self._process.returncode is not None:
            self._connected = False
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            line = json.dumps(request) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

            response_line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=30,
            )
            if response_line:
                decoded = json.loads(response_line.decode().strip())
                self._request_failures = 0
                return decoded
            self._request_failures += 1
        except asyncio.TimeoutError:
            logger.warning(f"MCP request timed out: {method}")
            self._request_failures += 1
        except Exception as e:
            logger.warning(f"MCP request error: {e}")
            self._request_failures += 1
        if self._request_failures >= self._request_failure_fuse:
            logger.error(
                "MCP connection fuse opened for %s after %d request failures",
                self.name,
                self._request_failures,
            )
            self._connected = False
        return None

    async def _send_notification(self, method: str, params: dict):
        if not self._process or not self._process.stdin:
            return
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            line = json.dumps(notification) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
        except Exception:
            pass

    @property
    def tools(self) -> list[dict]:
        return self._tools

    @property
    def resources(self) -> list[dict]:
        return self._resources

    @property
    def is_connected(self) -> bool:
        return self._connected


class MCPClientManager:
    """
    Manages connections to multiple external MCP servers.
    Auto-discovers servers from ~/.feral/mcp_servers.json.
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = Path(config_path) if config_path else feral_home() / "mcp_servers.json"
        self._servers: dict[str, MCPServerConnection] = {}
        self._server_configs: dict[str, dict] = {}
        self._degraded_servers: dict[str, dict] = {}
        self._reconnect_not_before: dict[str, float] = {}
        self._connect_max_attempts = max(
            1, int(os.environ.get("FERAL_MCP_RECONNECT_MAX_ATTEMPTS", "4"))
        )
        self._connect_backoff_cap_sec = max(
            1, int(os.environ.get("FERAL_MCP_RECONNECT_BACKOFF_CAP_SEC", "60"))
        )

    def _mark_degraded(self, name: str, reason: str, attempts: int) -> None:
        self._degraded_servers[name] = {
            "state": "DEGRADED",
            "reason": reason,
            "attempts": attempts,
        }

    def _clear_degraded(self, name: str) -> None:
        self._degraded_servers.pop(name, None)
        self._reconnect_not_before.pop(name, None)

    async def _connect_with_retries(self, conn: MCPServerConnection) -> bool:
        delay = 1.0
        attempts = 0
        for attempts in range(1, self._connect_max_attempts + 1):
            ok = await conn.connect()
            if ok:
                self._clear_degraded(conn.name)
                return True
            if attempts < self._connect_max_attempts:
                backoff = min(delay, float(self._connect_backoff_cap_sec))
                logger.warning(
                    "MCP reconnect retry: server=%s attempt=%d/%d backoff=%.1fs",
                    conn.name,
                    attempts,
                    self._connect_max_attempts,
                    backoff,
                )
                await asyncio.sleep(backoff)
                delay = min(backoff * 2.0, float(self._connect_backoff_cap_sec))

        self._mark_degraded(
            conn.name,
            f"connection failed after {attempts} attempts",
            attempts,
        )
        self._reconnect_not_before[conn.name] = time.time() + float(self._connect_backoff_cap_sec)
        logger.error(
            "MCP server marked DEGRADED: %s (attempts=%d)",
            conn.name,
            attempts,
        )
        return False

    async def _try_reconnect(self, name: str) -> bool:
        conn = self._servers.get(name)
        if conn is None:
            return False
        now = time.time()
        not_before = float(self._reconnect_not_before.get(name, 0.0) or 0.0)
        if now < not_before:
            return False
        ok = await self._connect_with_retries(conn)
        if ok:
            self._clear_degraded(name)
            return True
        self._reconnect_not_before[name] = now + float(self._connect_backoff_cap_sec)
        return False

    async def load_and_connect(self):
        """Load MCP server configs and connect to all."""
        self._degraded_servers.pop("__config__", None)
        if not self._config_path.exists():
            logger.info("No MCP servers configured (create ~/.feral/mcp_servers.json)")
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            self._mark_degraded("__config__", f"invalid config: {e}", attempts=1)
            logger.error("MCP config load failed: %s", e)
            return

        for server_config in config.get("servers", []):
            name = server_config.get("name", "unnamed")
            if not server_config.get("enabled", True):
                continue

            self._server_configs[name] = dict(server_config)
            conn = MCPServerConnection(name, server_config)
            success = await self._connect_with_retries(conn)
            if success:
                self._servers[name] = conn

        logger.info(f"MCP Client: {len(self._servers)} servers connected")

    async def disconnect_all(self):
        for conn in self._servers.values():
            await conn.disconnect()
        self._servers.clear()
        self._server_configs.clear()
        self._degraded_servers.clear()
        self._reconnect_not_before.clear()

    def get_server(self, name: str) -> Optional[MCPServerConnection]:
        return self._servers.get(name)

    def all_tools(self) -> list[dict]:
        """Get all tools from all connected MCP servers, prefixed with server name."""
        tools = []
        for name, server in self._servers.items():
            for tool in server.tools:
                prefixed_tool = {**tool, "name": f"mcp_{name}_{tool['name']}"}
                tools.append(prefixed_tool)
        return tools

    def all_resources(self) -> list[dict]:
        resources = []
        for name, server in self._servers.items():
            for resource in server.resources:
                resources.append({**resource, "server": name})
        return resources

    async def call_tool(self, prefixed_name: str, arguments: dict) -> dict:
        """Call a tool by its prefixed name (mcp_servername_toolname)."""
        if not prefixed_name.startswith("mcp_"):
            return {"error": "Not an MCP tool"}

        rest = prefixed_name[4:]
        for name in self._servers:
            if rest.startswith(f"{name}_"):
                tool_name = rest[len(name) + 1:]
                conn = self._servers[name]
                if not conn.is_connected:
                    await self._try_reconnect(name)
                if not conn.is_connected:
                    degraded = self._degraded_servers.get(name, {})
                    reason = degraded.get("reason") or "not connected"
                    return {"error": f"MCP server {name} unavailable ({reason})"}

                result = await conn.call_tool(tool_name, arguments)
                # One auto-reconnect chance when the call itself drops the
                # transport/fuse.
                if isinstance(result, dict) and result.get("error") and not conn.is_connected:
                    if await self._try_reconnect(name):
                        result = await conn.call_tool(tool_name, arguments)
                return result

        return {"error": f"MCP server not found for tool: {prefixed_name}"}

    def to_llm_tool_definitions(self) -> list[dict]:
        """Convert MCP tools to the format the LLM orchestrator expects."""
        definitions = []
        for tool in self.all_tools():
            definitions.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {}),
                },
            })
        return definitions

    @property
    def stats(self) -> dict:
        server_states = {
            name: ("connected" if conn.is_connected else "degraded")
            for name, conn in self._servers.items()
        }
        for name in self._degraded_servers:
            if name == "__config__":
                continue
            server_states.setdefault(name, "degraded")
        return {
            "servers_connected": len(self._servers),
            "total_tools": sum(len(s.tools) for s in self._servers.values()),
            "total_resources": sum(len(s.resources) for s in self._servers.values()),
            "server_names": list(self._servers.keys()),
            "server_states": server_states,
            "degraded_servers": dict(self._degraded_servers),
            "degraded_count": len(self._degraded_servers),
        }
