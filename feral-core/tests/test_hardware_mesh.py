"""Tests for FERAL hardware mesh node registration and invoke."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hardware.mesh import NODE_COMMANDS, HardwareMesh
from hardware.protocol import DeviceRegistry


class TestHardwareMeshInit:
    """Mesh container state."""

    def test_init_empty_registry_side(self):
        reg = DeviceRegistry()
        daemons: dict = {}
        mesh = HardwareMesh(reg, daemons)
        assert mesh._pending_invokes == {}
        assert mesh._node_metadata == {}


class TestNodeLifecycle:
    """Connect / disconnect register devices."""

    @pytest.mark.asyncio
    async def test_on_node_connected_registers(self):
        reg = DeviceRegistry()
        daemons: dict = {}
        mesh = HardwareMesh(reg, daemons)
        await mesh.on_node_connected(
            "node-a",
            {"node_type": "desktop", "platform": "linux", "capabilities": ["shell"]},
        )
        assert reg.get_device("node-a") is not None
        assert "node-a" in mesh._node_metadata

    @pytest.mark.asyncio
    async def test_on_node_disconnected_unregisters(self):
        reg = DeviceRegistry()
        daemons: dict = {}
        mesh = HardwareMesh(reg, daemons)
        await mesh.on_node_connected(
            "node-b",
            {"node_type": "desktop", "platform": "macos", "capabilities": []},
        )
        mesh.on_node_disconnected("node-b")
        assert reg.get_device("node-b") is None
        assert "node-b" not in mesh._node_metadata


class TestInvoke:
    """Command send and response correlation."""

    @pytest.mark.asyncio
    async def test_invoke_resolves_with_result(self):
        reg = DeviceRegistry()
        daemons: dict = {}
        mesh = HardwareMesh(reg, daemons)

        async def send_and_resolve(msg: dict):
            rid = msg["request_id"]
            mesh.resolve_invoke(rid, {"success": True, "data": {"v": 42}})

        ws = MagicMock()
        ws.send_json = AsyncMock(side_effect=send_and_resolve)
        daemons["n1"] = ws

        result = await mesh.invoke("n1", "location.get", {}, timeout=5.0)
        assert result.get("success") is True
        assert result.get("data", {}).get("v") == 42
        ws.send_json.assert_awaited()

    @pytest.mark.asyncio
    async def test_invoke_timeout_returns_error(self):
        reg = DeviceRegistry()
        daemons: dict = {}
        mesh = HardwareMesh(reg, daemons)
        ws = MagicMock()
        ws.send_json = AsyncMock(return_value=None)
        daemons["n2"] = ws

        result = await mesh.invoke("n2", "sensor.read", {}, timeout=0.05)
        assert result.get("success") is False
        assert "error" in result
        assert "Timeout" in result["error"]


class TestNodeCommands:
    """NODE_COMMANDS catalog."""

    def test_expected_commands_exist(self):
        for key in (
            "camera.snap",
            "location.get",
            "sensor.read",
            "health.read",
            "notification.send",
        ):
            assert key in NODE_COMMANDS
            assert "description" in NODE_COMMANDS[key]
