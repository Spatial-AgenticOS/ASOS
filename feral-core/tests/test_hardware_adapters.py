"""Tests for FERAL hardware adapters — wristband, smart home, robot arm."""

import pytest
from hardware.protocol import HUPAction, HUPActionType


# ── Wristband ─────────────────────────────────────────────────────


class TestWristbandAdapter:
    def test_init_and_manifest(self):
        from hardware.adapters.wristband import WristbandAdapter

        wb = WristbandAdapter()
        assert wb.device_id == "wristband-01"
        m = wb.manifest
        assert m.device_type == "wearable"
        assert len(m.capabilities) >= 5

    @pytest.mark.asyncio
    async def test_read_heart_rate(self):
        from hardware.adapters.wristband import WristbandAdapter

        wb = WristbandAdapter()
        await wb.connect()
        action = HUPAction(
            device_id="wristband-01",
            capability_id="heart_rate",
            action_type=HUPActionType.READ,
        )
        result = await wb.execute(action)
        assert result.status == "success"
        assert "bpm" in result.data

    @pytest.mark.asyncio
    async def test_unknown_capability(self):
        from hardware.adapters.wristband import WristbandAdapter

        wb = WristbandAdapter()
        action = HUPAction(
            device_id="wristband-01",
            capability_id="nonexistent",
            action_type=HUPActionType.READ,
        )
        result = await wb.execute(action)
        assert result.status == "failure"
        assert "Unknown" in result.error


# ── Smart Home ────────────────────────────────────────────────────


class TestSmartHomeAdapter:
    def test_init_and_manifest(self):
        from hardware.adapters.smart_home import SmartHomeAdapter

        sh = SmartHomeAdapter()
        assert sh.device_id == "smart-home-01"
        m = sh.manifest
        assert m.device_type == "smart_home"
        assert len(m.capabilities) >= 5

    @pytest.mark.asyncio
    async def test_lights_toggle_off(self):
        from hardware.adapters.smart_home import SmartHomeAdapter

        sh = SmartHomeAdapter()
        action = HUPAction(
            device_id="smart-home-01",
            capability_id="lights_toggle",
            action_type=HUPActionType.EXECUTE,
            parameters={"state": "off"},
        )
        result = await sh.execute(action)
        assert result.status == "success"
        assert result.data["lights_on"] is False

    @pytest.mark.asyncio
    async def test_unknown_capability(self):
        from hardware.adapters.smart_home import SmartHomeAdapter

        sh = SmartHomeAdapter()
        action = HUPAction(
            device_id="smart-home-01",
            capability_id="nonexistent",
            action_type=HUPActionType.EXECUTE,
        )
        result = await sh.execute(action)
        assert result.status == "failure"
        assert "Unknown" in result.error


# ── Robot Arm ─────────────────────────────────────────────────────


class TestRobotArmAdapter:
    def test_init_and_manifest(self):
        from hardware.adapters.robot_arm import RobotArmAdapter

        ra = RobotArmAdapter()
        assert ra.device_id == "robot-arm-01"
        assert ra.dof == 6
        m = ra.manifest
        assert m.device_type == "robot"

    @pytest.mark.asyncio
    async def test_read_position(self):
        from hardware.adapters.robot_arm import RobotArmAdapter

        ra = RobotArmAdapter()
        action = HUPAction(
            device_id="robot-arm-01",
            capability_id="read_position",
            action_type=HUPActionType.READ,
        )
        result = await ra.execute(action)
        assert result.status == "success"
        assert "joints" in result.data
        assert len(result.data["joints"]) == 6

    @pytest.mark.asyncio
    async def test_unknown_capability(self):
        from hardware.adapters.robot_arm import RobotArmAdapter

        ra = RobotArmAdapter()
        action = HUPAction(
            device_id="robot-arm-01",
            capability_id="nonexistent",
            action_type=HUPActionType.EXECUTE,
        )
        result = await ra.execute(action)
        assert result.status == "failure"
        assert "Unknown" in result.error
