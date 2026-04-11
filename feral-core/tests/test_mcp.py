"""Tests for MCP Server and Client."""
import pytest
import json
from mcp.server import FeralMCPServer
from hardware.protocol import DeviceRegistry, FERAL_GLASSES_MANIFEST


class TestMCPServer:
    def setup_method(self):
        self.registry = DeviceRegistry()
        self.registry.register_device(FERAL_GLASSES_MANIFEST)
        self.server = FeralMCPServer(device_registry=self.registry)

    def test_initialize(self):
        result = self.server.handle_initialize({})
        assert result["protocolVersion"] == "2024-11-05"
        assert "tools" in result["capabilities"]
        assert "resources" in result["capabilities"]

    def test_tools_list_has_core_tools(self):
        result = self.server.handle_tools_list()
        tool_names = [t["name"] for t in result["tools"]]
        assert "feral_list_devices" in tool_names
        assert "feral_device_status" in tool_names
        assert "feral_read_sensor" in tool_names
        assert "feral_execute_action" in tool_names
        assert "feral_memory_query" in tool_names
        assert "feral_perception_snapshot" in tool_names

    def test_tools_list_has_dynamic_device_tools(self):
        result = self.server.handle_tools_list()
        tool_names = [t["name"] for t in result["tools"]]
        has_glasses_tool = any("feral-glasses" in n for n in tool_names)
        assert has_glasses_tool

    def test_resources_list(self):
        result = self.server.handle_resources_list()
        uris = [r["uri"] for r in result["resources"]]
        assert "feral://devices" in uris
        assert "feral://perception" in uris
        assert "feral://device/feral-glasses" in uris

    def test_resources_read_devices(self):
        result = self.server.handle_resources_read("feral://devices")
        contents = result["contents"][0]["text"]
        data = json.loads(contents)
        assert len(data) == 1
        assert data[0]["device_id"] == "feral-glasses"

    def test_prompts_list(self):
        result = self.server.handle_prompts_list()
        assert len(result["prompts"]) >= 2

    @pytest.mark.asyncio
    async def test_jsonrpc_initialize(self):
        result = await self.server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {},
        })
        assert result["id"] == 1
        assert "result" in result

    @pytest.mark.asyncio
    async def test_jsonrpc_ping(self):
        result = await self.server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 2,
            "method": "ping", "params": {},
        })
        assert result["id"] == 2
        assert "result" in result

    @pytest.mark.asyncio
    async def test_jsonrpc_unknown_method(self):
        result = await self.server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 3,
            "method": "nonexistent", "params": {},
        })
        assert "error" in result
        assert result["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_tools_call_list_devices(self):
        result = await self.server.handle_tools_call("feral_list_devices", {})
        assert "content" in result
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_tools_call_device_status(self):
        result = await self.server.handle_tools_call("feral_device_status", {"device_id": "feral-glasses"})
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert data["device_id"] == "feral-glasses"

    @pytest.mark.asyncio
    async def test_tools_call_unknown(self):
        result = await self.server.handle_tools_call("unknown_tool", {})
        assert result["isError"]


class TestMCPServerNoDevices:
    def test_empty_tools_list(self):
        server = FeralMCPServer()
        result = server.handle_tools_list()
        tool_names = [t["name"] for t in result["tools"]]
        assert "feral_list_devices" in tool_names
