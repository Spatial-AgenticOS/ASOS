"""
THEORA Hardware Mesh — Auto-Registration & Node Invoke
========================================================
Bridges the gap between daemon WebSocket connections and the HUP device registry.

- Auto-registers daemons as HUP devices when they connect
- node.invoke pattern: send command to daemon, wait for response with timeout
- Phone as primary node (camera, GPS, health)
- Wristband/glasses as HUP devices
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Optional
from uuid import uuid4

from hardware.protocol import (
    DeviceRegistry,
    DeviceManifest,
    DeviceCapability,
    HUPAction,
    HUPResult,
)

logger = logging.getLogger("theora.hardware.mesh")

NODE_COMMANDS = {
    "camera.snap": {
        "description": "Capture a photo",
        "category": "sensor",
        "params": [{"name": "resolution", "type": "string", "default": "1080p"}],
    },
    "camera.clip": {
        "description": "Record a short video clip",
        "category": "sensor",
        "params": [{"name": "duration_s", "type": "integer", "default": 5}],
    },
    "location.get": {
        "description": "Get current GPS location",
        "category": "sensor",
        "params": [],
    },
    "sensor.read": {
        "description": "Read a named sensor value",
        "category": "sensor",
        "params": [{"name": "sensor_name", "type": "string", "required": True}],
    },
    "screen.record": {
        "description": "Start/stop screen recording",
        "category": "sensor",
        "params": [{"name": "action", "type": "string", "default": "start"}],
    },
    "system.run": {
        "description": "Execute a shell command on the node",
        "category": "compute",
        "params": [{"name": "command", "type": "string", "required": True}],
    },
    "notification.send": {
        "description": "Push a notification to the device",
        "category": "display",
        "params": [
            {"name": "title", "type": "string", "required": True},
            {"name": "body", "type": "string", "required": True},
        ],
    },
    "health.read": {
        "description": "Read health sensor data (heart rate, SpO2, etc.)",
        "category": "sensor",
        "params": [{"name": "metric", "type": "string", "default": "all"}],
    },
    "audio.play": {
        "description": "Play audio on the device",
        "category": "audio",
        "params": [{"name": "url", "type": "string", "required": True}],
    },
    "audio.tts": {
        "description": "Speak text on the device",
        "category": "audio",
        "params": [{"name": "text", "type": "string", "required": True}],
    },
}

PHONE_MANIFEST_TEMPLATE = DeviceManifest(
    device_id="",
    device_type="phone",
    name="Phone Bridge",
    manufacturer="THEORA",
    connection_type="websocket",
    capabilities=[
        DeviceCapability(
            id="camera_snap", name="Camera", description="Capture photos",
            category="sensor", permission_tier="active",
        ),
        DeviceCapability(
            id="gps_location", name="GPS", description="Get location",
            category="sensor", permission_tier="passive",
        ),
        DeviceCapability(
            id="health_sensors", name="Health Sensors",
            description="Heart rate, SpO2, temperature via HealthKit or wristband",
            category="sensor", permission_tier="passive",
        ),
        DeviceCapability(
            id="notification", name="Push Notification",
            description="Send notification to phone",
            category="display", permission_tier="active",
        ),
        DeviceCapability(
            id="haptic", name="Haptic Feedback",
            description="Vibrate the device",
            category="actuator", permission_tier="active",
        ),
    ],
    sensors=["camera", "gps", "accelerometer", "gyroscope", "heart_rate", "spo2"],
    actuators=["display", "speaker", "haptic"],
    battery_powered=True,
    location="pocket",
)


class HardwareMesh:
    """
    Manages the mesh of connected hardware nodes.
    Auto-registers daemons as HUP devices and routes commands.
    """

    def __init__(self, device_registry: DeviceRegistry, daemons: dict):
        self._registry = device_registry
        self._daemons = daemons
        self._pending_invokes: dict[str, asyncio.Future] = {}
        self._node_metadata: dict[str, dict] = {}

    async def on_node_connected(self, node_id: str, registration_payload: dict):
        """Auto-register a daemon as a HUP device when it connects."""
        node_type = registration_payload.get("node_type", "desktop")
        platform = registration_payload.get("platform", "unknown")
        capabilities = registration_payload.get("capabilities", [])

        if node_type in ("phone", "ios", "android"):
            manifest = PHONE_MANIFEST_TEMPLATE.model_copy(update={
                "device_id": node_id,
                "name": f"Phone ({platform})",
            })
        else:
            manifest = DeviceManifest(
                device_id=node_id,
                device_type=node_type,
                name=f"{node_type.title()} Node ({platform})",
                manufacturer="THEORA",
                connection_type="websocket",
                capabilities=[
                    DeviceCapability(
                        id=cap, name=cap.replace("_", " ").title(),
                        description=f"Device capability: {cap}",
                        category="compute", permission_tier="active",
                    )
                    for cap in capabilities
                ],
            )

        adapter = WebSocketNodeAdapter(node_id, self._daemons, self._pending_invokes)
        self._registry.register_device(manifest, adapter)
        self._node_metadata[node_id] = {
            "registered_at": time.time(),
            "node_type": node_type,
            "platform": platform,
        }
        logger.info(f"Node auto-registered as HUP device: {node_id} ({node_type}/{platform})")

    def on_node_disconnected(self, node_id: str):
        """Unregister a daemon when it disconnects."""
        self._registry.unregister_device(node_id)
        self._node_metadata.pop(node_id, None)
        logger.info(f"Node unregistered from HUP: {node_id}")

    async def invoke(
        self,
        node_id: str,
        command: str,
        params: dict = None,
        timeout: float = 10.0,
    ) -> dict:
        """
        Send a command to a daemon node and wait for the response.
        This is the core node.invoke pattern.
        """
        ws = self._daemons.get(node_id)
        if not ws:
            return {"success": False, "error": f"Node not connected: {node_id}"}

        request_id = str(uuid4())[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_invokes[request_id] = future

        msg = {
            "type": "command",
            "request_id": request_id,
            "command": command,
            "args": params or {},
        }

        try:
            await ws.send_json(msg)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_invokes.pop(request_id, None)
            return {"success": False, "error": f"Timeout waiting for {command} on {node_id}"}
        except Exception as e:
            self._pending_invokes.pop(request_id, None)
            return {"success": False, "error": str(e)}

    def resolve_invoke(self, request_id: str, result: dict):
        """Called when a daemon sends back an execute_result."""
        future = self._pending_invokes.pop(request_id, None)
        if future and not future.done():
            future.set_result(result)

    @property
    def connected_nodes(self) -> list[dict]:
        return [
            {"node_id": nid, **meta}
            for nid, meta in self._node_metadata.items()
            if nid in self._daemons
        ]


class WebSocketNodeAdapter:
    """
    HUP DeviceAdapter that routes actions to a WebSocket daemon.
    Bridges the HUP action model to the node.invoke pattern.
    """

    def __init__(self, node_id: str, daemons: dict, pending: dict):
        self._node_id = node_id
        self._daemons = daemons
        self._pending = pending

    async def execute(self, action: HUPAction) -> HUPResult:
        """Execute a HUP action by sending it to the daemon."""
        ws = self._daemons.get(self._node_id)
        if not ws:
            return HUPResult(
                action_id=action.action_id, device_id=action.device_id,
                status="failure", error=f"Node disconnected: {self._node_id}",
            )

        request_id = str(uuid4())[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        command = action.capability_id
        cmd_info = NODE_COMMANDS.get(command, {})

        msg = {
            "type": "command",
            "request_id": request_id,
            "command": command,
            "args": action.parameters,
        }

        try:
            await ws.send_json(msg)
            timeout = action.timeout_ms / 1000.0
            result = await asyncio.wait_for(future, timeout=timeout)

            return HUPResult(
                action_id=action.action_id,
                device_id=action.device_id,
                status="success" if result.get("success") else "failure",
                data=result.get("data", {}),
                error=result.get("error", ""),
            )
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            return HUPResult(
                action_id=action.action_id, device_id=action.device_id,
                status="timeout", error=f"Timeout ({action.timeout_ms}ms)",
            )
        except Exception as e:
            self._pending.pop(request_id, None)
            return HUPResult(
                action_id=action.action_id, device_id=action.device_id,
                status="failure", error=str(e),
            )
