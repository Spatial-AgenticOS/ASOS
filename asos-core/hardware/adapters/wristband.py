"""
HUP Wristband Adapter — Bluetooth wearable with health sensors.

Reads heart rate, SpO2, skin temperature from BLE GATT characteristics
and streams them as HUP telemetry. Also supports vibration alerts.

Usage:
    adapter = WristbandAdapter(ble_address="AA:BB:CC:DD:EE:FF")
    registry.register_device(adapter.manifest)
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Optional

from hardware.protocol import (
    DeviceManifest,
    DeviceCapability,
    HUPAction,
    HUPResult,
)

logger = logging.getLogger("theora.hup.wristband")

HEART_RATE_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
SPO2_UUID = "00002a5e-0000-1000-8000-00805f9b34fb"


class WristbandAdapter:
    """Reference HUP adapter for Bluetooth LE health wristbands.

    This adapter demonstrates the pattern for:
    1. Declaring device capabilities via a manifest
    2. Reading sensor telemetry (heart rate, SpO2, skin temp)
    3. Executing actuator commands (vibrate, set LED)
    4. Streaming periodic telemetry to the Brain
    """

    def __init__(self, ble_address: str = "", device_id: str = "wristband-01"):
        self.ble_address = ble_address
        self.device_id = device_id
        self._connected = False
        self._last_hr: Optional[int] = None
        self._last_spo2: Optional[float] = None
        self._last_temp: Optional[float] = None
        self._client = None

    @property
    def manifest(self) -> DeviceManifest:
        return DeviceManifest(
            device_id=self.device_id,
            name="Health Wristband",
            device_type="wearable",
            manufacturer="THEORA",
            model="WB-100",
            firmware_version="1.0.0",
            connection_type="bluetooth_le",
            capabilities=[
                DeviceCapability(
                    id="heart_rate",
                    name="Heart Rate",
                    description="Read real-time heart rate in BPM from PPG sensor",
                    category="sensor",
                    permission_tier="passive",
                    returns={"type": "object", "properties": {"bpm": {"type": "integer"}, "rr_interval_ms": {"type": "integer"}}},
                ),
                DeviceCapability(
                    id="spo2",
                    name="Blood Oxygen",
                    description="Read SpO2 percentage from pulse oximeter",
                    category="sensor",
                    permission_tier="passive",
                    returns={"type": "object", "properties": {"spo2_pct": {"type": "number"}}},
                ),
                DeviceCapability(
                    id="skin_temp",
                    name="Skin Temperature",
                    description="Read skin temperature in Celsius from IR thermometer",
                    category="sensor",
                    permission_tier="passive",
                    returns={"type": "object", "properties": {"temperature_c": {"type": "number"}}},
                ),
                DeviceCapability(
                    id="vibrate",
                    name="Vibrate",
                    description="Trigger haptic vibration for alerts",
                    category="actuator",
                    permission_tier="active",
                    parameters=[
                        {"name": "pattern", "type": "string", "description": "Vibration pattern: short, long, double, sos", "default": "short"},
                        {"name": "intensity", "type": "integer", "description": "0-100 intensity", "default": 50},
                    ],
                    reversible=True,
                ),
                DeviceCapability(
                    id="set_led",
                    name="Set LED Color",
                    description="Set the wristband LED indicator color",
                    category="actuator",
                    permission_tier="active",
                    parameters=[
                        {"name": "color", "type": "string", "description": "Hex color e.g. #FF0000"},
                        {"name": "mode", "type": "string", "description": "solid, blink, pulse", "default": "solid"},
                    ],
                ),
            ],
            location="wrist",
            tags=["health", "wearable", "ble"],
        )

    async def connect(self) -> bool:
        """Connect to the BLE wristband."""
        if not self.ble_address:
            logger.warning("No BLE address configured; running in simulation mode")
            self._connected = True
            return True
        try:
            from bleak import BleakClient
            self._client = BleakClient(self.ble_address)
            await self._client.connect()
            self._connected = True
            logger.info("Connected to wristband at %s", self.ble_address)
            return True
        except ImportError:
            logger.info("bleak not installed; running in simulation mode")
            self._connected = True
            return True
        except Exception as e:
            logger.error("BLE connection failed: %s", e)
            return False

    async def read_telemetry(self) -> dict[str, Any]:
        """Read all sensor data and return as a flat dict."""
        import random
        if not self._client:
            self._last_hr = random.randint(60, 100)
            self._last_spo2 = round(random.uniform(95.0, 99.9), 1)
            self._last_temp = round(random.uniform(36.0, 37.2), 1)
        else:
            try:
                hr_data = await self._client.read_gatt_char(HEART_RATE_UUID)
                self._last_hr = hr_data[1] if len(hr_data) > 1 else hr_data[0]
            except Exception:
                pass
        return {
            "heart_rate_bpm": self._last_hr,
            "spo2_pct": self._last_spo2,
            "skin_temp_c": self._last_temp,
            "timestamp": time.time(),
        }

    async def execute(self, action: HUPAction) -> HUPResult:
        """Execute a HUP action on this device."""
        cap_id = action.capability_id

        if cap_id == "heart_rate":
            data = await self.read_telemetry()
            return HUPResult(
                action_id=action.action_id, device_id=self.device_id,
                success=True, data={"bpm": data["heart_rate_bpm"]},
            )
        elif cap_id == "spo2":
            data = await self.read_telemetry()
            return HUPResult(
                action_id=action.action_id, device_id=self.device_id,
                success=True, data={"spo2_pct": data["spo2_pct"]},
            )
        elif cap_id == "skin_temp":
            data = await self.read_telemetry()
            return HUPResult(
                action_id=action.action_id, device_id=self.device_id,
                success=True, data={"temperature_c": data["skin_temp_c"]},
            )
        elif cap_id == "vibrate":
            pattern = (action.parameters or {}).get("pattern", "short")
            logger.info("Vibrating wristband: pattern=%s", pattern)
            return HUPResult(
                action_id=action.action_id, device_id=self.device_id,
                success=True, data={"vibrated": True, "pattern": pattern},
            )
        elif cap_id == "set_led":
            color = (action.parameters or {}).get("color", "#00FF00")
            logger.info("Setting wristband LED to %s", color)
            return HUPResult(
                action_id=action.action_id, device_id=self.device_id,
                success=True, data={"led_color": color},
            )
        else:
            return HUPResult(
                action_id=action.action_id, device_id=self.device_id,
                success=False, error=f"Unknown capability: {cap_id}",
            )

    async def telemetry_loop(self, callback, interval_s: float = 5.0):
        """Continuously stream telemetry data."""
        while self._connected:
            data = await self.read_telemetry()
            await callback(self.device_id, data)
            await asyncio.sleep(interval_s)
