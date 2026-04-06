"""
THEORA MCP Client — Consume Any MCP Server
=============================================
THEORA can connect to external MCP servers and use their tools.
This instantly gives THEORA access to thousands of existing tools
without writing any adapters.

Examples:
  - Connect to a GitHub MCP server → THEORA can manage repos
  - Connect to a Postgres MCP server → THEORA can query databases
  - Connect to a Notion MCP server → THEORA can manage pages
  - Connect to another THEORA instance → multi-Brain collaboration

Configuration via ~/.theora/mcp_servers.json:
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
import subprocess
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger("theora.mcp.client")


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

    async def connect(self) -> bool:
        if self.transport == "stdio":
            return await self._connect_stdio()
        elif self.transport == "http":
            self._connected = True
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
                "clientInfo": {"name": "theora", "version": "1.0.0"},
            })

            if init_result and "error" not in init_result:
                await self._send_notification("initialized", {})
                self._connected = True
                await self._discover_tools()
                await self._discover_resources()
                logger.info(f"MCP server connected: {self.name} ({len(self._tools)} tools, {len(self._resources)} resources)")
                return True

        except FileNotFoundError:
            logger.error(f"MCP server command not found: {command}")
        except Exception as e:
            logger.error(f"MCP server connection failed ({self.name}): {e}")

        return False

    async def disconnect(self):
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
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
                return json.loads(response_line.decode().strip())
        except asyncio.TimeoutError:
            logger.warning(f"MCP request timed out: {method}")
        except Exception as e:
            logger.warning(f"MCP request error: {e}")
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
    Auto-discovers servers from ~/.theora/mcp_servers.json.
    """

    def __init__(self, config_path: Optional[str] = None):
        home = os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))
        self._config_path = Path(config_path) if config_path else Path(home) / "mcp_servers.json"
        self._servers: dict[str, MCPServerConnection] = {}

    async def load_and_connect(self):
        """Load MCP server configs and connect to all."""
        if not self._config_path.exists():
            logger.info("No MCP servers configured (create ~/.theora/mcp_servers.json)")
            return

        with open(self._config_path) as f:
            config = json.load(f)

        for server_config in config.get("servers", []):
            name = server_config.get("name", "unnamed")
            if not server_config.get("enabled", True):
                continue

            conn = MCPServerConnection(name, server_config)
            success = await conn.connect()
            if success:
                self._servers[name] = conn

        logger.info(f"MCP Client: {len(self._servers)} servers connected")

    async def disconnect_all(self):
        for conn in self._servers.values():
            await conn.disconnect()
        self._servers.clear()

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
                return await self._servers[name].call_tool(tool_name, arguments)

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
        return {
            "servers_connected": len(self._servers),
            "total_tools": sum(len(s.tools) for s in self._servers.values()),
            "total_resources": sum(len(s.resources) for s in self._servers.values()),
            "server_names": list(self._servers.keys()),
        }
