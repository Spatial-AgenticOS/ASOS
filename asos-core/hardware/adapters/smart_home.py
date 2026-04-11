"""
HUP Smart Home Adapter — Control lights, switches, thermostats via HUP.

Bridges the HUP protocol to common smart home APIs (Philips Hue, MQTT, HTTP).
The agent says "turn off the lights" and HUP routes it here.

Usage:
    adapter = SmartHomeAdapter(bridge_ip="192.168.1.42", api_key="...")
    registry.register_device(adapter.manifest)
"""

from __future__ import annotations
import logging
from typing import Any, Optional

from hardware.protocol import (
    DeviceManifest,
    DeviceCapability,
    HUPAction,
    HUPResult,
)

logger = logging.getLogger("theora.hup.smart_home")


class SmartHomeAdapter:
    """Reference HUP adapter for smart home devices (lights, plugs, thermostats).

    Demonstrates the pattern for:
    1. Multi-capability devices (light color, brightness, on/off, scenes)
    2. HTTP bridge to external APIs (Hue, Home Assistant, MQTT)
    3. State tracking for reversible actions
    """

    def __init__(
        self,
        bridge_ip: str = "",
        api_key: str = "",
        device_id: str = "smart-home-01",
    ):
        self.bridge_ip = bridge_ip
        self.api_key = api_key
        self.device_id = device_id
        self._state: dict[str, Any] = {
            "lights_on": True,
            "brightness": 80,
            "color": "#FFFFFF",
            "temperature_setpoint_c": 22.0,
        }

    @property
    def manifest(self) -> DeviceManifest:
        return DeviceManifest(
            device_id=self.device_id,
            name="Smart Home Hub",
            device_type="smart_home",
            manufacturer="THEORA",
            model="SH-Hub",
            firmware_version="1.0.0",
            connection_type="wifi",
            capabilities=[
                DeviceCapability(
                    id="lights_toggle",
                    name="Toggle Lights",
                    description="Turn lights on or off",
                    category="actuator",
                    permission_tier="active",
                    parameters=[{"name": "state", "type": "string", "description": "on or off"}],
                    reversible=True,
                ),
                DeviceCapability(
                    id="lights_brightness",
                    name="Set Brightness",
                    description="Adjust light brightness (0-100)",
                    category="actuator",
                    permission_tier="active",
                    parameters=[{"name": "brightness", "type": "integer", "description": "0-100"}],
                    reversible=True,
                ),
                DeviceCapability(
                    id="lights_color",
                    name="Set Light Color",
                    description="Change light color (hex)",
                    category="actuator",
                    permission_tier="active",
                    parameters=[{"name": "color", "type": "string", "description": "Hex color e.g. #FF6600"}],
                    reversible=True,
                ),
                DeviceCapability(
                    id="thermostat_set",
                    name="Set Thermostat",
                    description="Set target temperature in Celsius",
                    category="actuator",
                    permission_tier="active",
                    parameters=[{"name": "temperature_c", "type": "number", "description": "Target temperature"}],
                    requires_confirmation=True,
                    reversible=True,
                ),
                DeviceCapability(
                    id="thermostat_read",
                    name="Read Temperature",
                    description="Read current room temperature",
                    category="sensor",
                    permission_tier="passive",
                    returns={"type": "object", "properties": {"current_c": {"type": "number"}, "setpoint_c": {"type": "number"}}},
                ),
                DeviceCapability(
                    id="scene_activate",
                    name="Activate Scene",
                    description="Activate a lighting scene (e.g. relax, focus, movie, bright)",
                    category="actuator",
                    permission_tier="active",
                    parameters=[{"name": "scene", "type": "string", "description": "Scene name"}],
                ),
            ],
            location="home",
            tags=["smart-home", "lights", "thermostat"],
        )

    async def execute(self, action: HUPAction) -> HUPResult:
        cap_id = action.capability_id
        params = action.parameters or {}

        if cap_id == "lights_toggle":
            on = params.get("state", "on").lower() == "on"
            self._state["lights_on"] = on
            await self._send_hue_command({"on": on})
            return HUPResult(action_id=action.action_id, device_id=self.device_id, success=True, data={"lights_on": on})

        elif cap_id == "lights_brightness":
            bri = int(params.get("brightness", 80))
            self._state["brightness"] = max(0, min(100, bri))
            await self._send_hue_command({"bri": int(bri * 2.54)})
            return HUPResult(action_id=action.action_id, device_id=self.device_id, success=True, data={"brightness": self._state["brightness"]})

        elif cap_id == "lights_color":
            color = params.get("color", "#FFFFFF")
            self._state["color"] = color
            await self._send_hue_command({"color": color})
            return HUPResult(action_id=action.action_id, device_id=self.device_id, success=True, data={"color": color})

        elif cap_id == "thermostat_set":
            temp = float(params.get("temperature_c", 22.0))
            self._state["temperature_setpoint_c"] = temp
            return HUPResult(action_id=action.action_id, device_id=self.device_id, success=True, data={"setpoint_c": temp})

        elif cap_id == "thermostat_read":
            import random
            current = round(self._state["temperature_setpoint_c"] + random.uniform(-1, 1), 1)
            return HUPResult(
                action_id=action.action_id, device_id=self.device_id, success=True,
                data={"current_c": current, "setpoint_c": self._state["temperature_setpoint_c"]},
            )

        elif cap_id == "scene_activate":
            scene = params.get("scene", "relax")
            scenes = {
                "relax": {"brightness": 30, "color": "#FF8C00"},
                "focus": {"brightness": 90, "color": "#FFFFFF"},
                "movie": {"brightness": 10, "color": "#1E0A3C"},
                "bright": {"brightness": 100, "color": "#FFFFFF"},
            }
            settings = scenes.get(scene, scenes["relax"])
            self._state.update(settings)
            return HUPResult(action_id=action.action_id, device_id=self.device_id, success=True, data={"scene": scene, **settings})

        return HUPResult(action_id=action.action_id, device_id=self.device_id, success=False, error=f"Unknown capability: {cap_id}")

    async def _send_hue_command(self, cmd: dict):
        """Send a command to the Hue bridge. Falls back to simulation if not configured."""
        if not self.bridge_ip:
            logger.debug("Smart home simulation: %s", cmd)
            return
        try:
            import httpx
            url = f"http://{self.bridge_ip}/api/{self.api_key}/lights/1/state"
            async with httpx.AsyncClient() as client:
                await client.put(url, json=cmd)
        except Exception as e:
            logger.warning("Hue bridge command failed: %s", e)
