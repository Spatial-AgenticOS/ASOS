#!/usr/bin/env python3
"""
ASOS Node SDK — W300 Smart Glasses Bridge Daemon
=================================================
Connects to W300 smart glasses via Bluetooth (bleak) on macOS.
Captures live telemetry (PPG, IMU, SpO2) and vision frames,
streaming them into the ASOS Agentic Loop for biometric-aware
and vision-aware context routing.

Usage:
    python3 w300_daemon.py
    python3 w300_daemon.py --dev-camera --vision-interval 10
"""

import asyncio
import base64
import io
import json
import logging
import argparse
import math
import os
import socket
import struct
import uuid
import time
import subprocess
from collections import deque
from typing import Optional

import websockets
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("w300_daemon")

# ─────────────────────────────────────────────
# W300 BLE Service UUIDs
# ─────────────────────────────────────────────
W300_DEVICE_NAME = "W300"

# Standard GATT services
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_UUID = "00002a29-0000-1000-8000-00805f9b34fb"

# W300 vendor-specific services (placeholder UUIDs — replace with real SDK values)
W300_CAMERA_SERVICE_UUID = "0000ff10-0000-1000-8000-00805f9b34fb"
W300_CAMERA_CONTROL_UUID = "0000ff11-0000-1000-8000-00805f9b34fb"
W300_CAMERA_FRAME_UUID = "0000ff12-0000-1000-8000-00805f9b34fb"
W300_IMU_SERVICE_UUID = "0000ff20-0000-1000-8000-00805f9b34fb"
W300_IMU_DATA_UUID = "0000ff21-0000-1000-8000-00805f9b34fb"
W300_SPO2_UUID = "0000ff30-0000-1000-8000-00805f9b34fb"
W300_AMBIENT_LIGHT_UUID = "0000ff31-0000-1000-8000-00805f9b34fb"

MAX_FRAME_B64_BYTES = 512 * 1024  # 512KB cap on base64 payload


# ─────────────────────────────────────────────
# Vision Capture — Multi-backend frame grabber
# ─────────────────────────────────────────────

class VisionCapture:
    """
    Captures frames from the W300 camera through multiple backends,
    tried in priority order: BLE camera service, TCP/WiFi-Direct, local webcam fallback.
    """

    def __init__(self, ble_client: Optional[BleakClient] = None, dev_camera: bool = False):
        self._ble_client = ble_client
        self._dev_camera = dev_camera
        self._tcp_host: Optional[str] = None
        self._tcp_port: int = 8890
        self._has_ble_camera = False
        self._cv2 = None
        self._local_cap = None

        if dev_camera:
            self._init_dev_camera()

    def _init_dev_camera(self):
        """Lazy-load opencv for development camera fallback."""
        try:
            import cv2
            self._cv2 = cv2
            self._local_cap = cv2.VideoCapture(0)
            if self._local_cap.isOpened():
                logger.info("Dev camera initialized (local webcam)")
            else:
                logger.warning("Dev camera requested but no webcam available")
                self._local_cap = None
        except ImportError:
            logger.warning("opencv-python-headless not installed — dev camera unavailable")

    async def probe_ble_camera(self, client: BleakClient) -> bool:
        """Check if the connected W300 exposes the vendor camera GATT service."""
        self._ble_client = client
        try:
            services = client.services
            for service in services:
                if W300_CAMERA_SERVICE_UUID.lower() in str(service.uuid).lower():
                    self._has_ble_camera = True
                    logger.info(f"W300 BLE camera service discovered: {service.uuid}")
                    return True
            logger.info("W300 does not expose BLE camera service — will use fallback backends")
            return False
        except Exception as e:
            logger.warning(f"Failed to probe BLE camera service: {e}")
            return False

    def set_tcp_endpoint(self, host: str, port: int = 8890):
        """Configure a TCP/WiFi-Direct endpoint for high-bandwidth frame streaming."""
        self._tcp_host = host
        self._tcp_port = port
        logger.info(f"TCP camera endpoint set: {host}:{port}")

    async def grab_frame(self, resolution: str = "640x480", quality: int = 80) -> Optional[dict]:
        """
        Capture a single frame. Tries backends in order:
        1. BLE camera service (real hardware)
        2. TCP/WiFi-Direct socket
        3. Local webcam (dev mode)

        Returns dict with frame_id, encoding, resolution, data_b64, metadata or None on failure.
        """
        width, height = self._parse_resolution(resolution)

        frame_bytes = await self._capture_ble(width, height, quality)
        if frame_bytes is None:
            frame_bytes = await self._capture_tcp(width, height, quality)
        if frame_bytes is None:
            frame_bytes = self._capture_local(width, height, quality)
        if frame_bytes is None:
            return None

        data_b64 = base64.b64encode(frame_bytes).decode("ascii")

        if len(data_b64) > MAX_FRAME_B64_BYTES:
            logger.warning(f"Frame exceeds {MAX_FRAME_B64_BYTES}B limit ({len(data_b64)}B), downscaling")
            frame_bytes = self._downscale(frame_bytes, max_bytes=int(MAX_FRAME_B64_BYTES * 0.75))
            if frame_bytes is None:
                return None
            data_b64 = base64.b64encode(frame_bytes).decode("ascii")

        return {
            "frame_id": uuid.uuid4().hex[:12],
            "encoding": "jpeg",
            "resolution": [width, height],
            "data_b64": data_b64,
            "timestamp": time.time(),
            "metadata": {
                "size_bytes": len(frame_bytes),
                "quality": quality,
            },
        }

    async def _capture_ble(self, width: int, height: int, quality: int) -> Optional[bytes]:
        """Capture via W300 BLE camera GATT characteristic (chunked read)."""
        if not self._has_ble_camera or not self._ble_client or not self._ble_client.is_connected:
            return None

        try:
            control_payload = struct.pack("<HHB", width, height, quality)
            await self._ble_client.write_gatt_char(W300_CAMERA_CONTROL_UUID, control_payload)
            await asyncio.sleep(0.5)

            chunks = []
            while True:
                chunk = await self._ble_client.read_gatt_char(W300_CAMERA_FRAME_UUID)
                if not chunk or len(chunk) == 0:
                    break
                chunks.append(bytes(chunk))
                if len(chunk) < 512:
                    break

            if chunks:
                frame_data = b"".join(chunks)
                logger.info(f"BLE camera captured {len(frame_data)} bytes")
                return frame_data

        except Exception as e:
            logger.warning(f"BLE camera capture failed: {e}")
        return None

    async def _capture_tcp(self, width: int, height: int, quality: int) -> Optional[bytes]:
        """Capture via TCP/WiFi-Direct socket from W300."""
        if not self._tcp_host:
            return None

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._tcp_host, self._tcp_port),
                timeout=5.0,
            )
            request = json.dumps({"cmd": "capture", "width": width, "height": height, "quality": quality})
            writer.write(request.encode() + b"\n")
            await writer.drain()

            size_header = await asyncio.wait_for(reader.readexactly(4), timeout=5.0)
            frame_size = struct.unpack("<I", size_header)[0]
            frame_data = await asyncio.wait_for(reader.readexactly(frame_size), timeout=10.0)

            writer.close()
            await writer.wait_closed()
            logger.info(f"TCP camera captured {len(frame_data)} bytes from {self._tcp_host}")
            return frame_data

        except Exception as e:
            logger.warning(f"TCP camera capture failed: {e}")
        return None

    def _capture_local(self, width: int, height: int, quality: int) -> Optional[bytes]:
        """Capture from local webcam (dev fallback)."""
        if not self._cv2 or not self._local_cap or not self._local_cap.isOpened():
            return None

        self._local_cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, width)
        self._local_cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, height)

        ret, frame = self._local_cap.read()
        if not ret or frame is None:
            return None

        encode_params = [self._cv2.IMWRITE_JPEG_QUALITY, quality]
        success, buf = self._cv2.imencode(".jpg", frame, encode_params)
        if not success:
            return None

        logger.info(f"Dev camera captured {len(buf)} bytes ({width}x{height})")
        return buf.tobytes()

    def _downscale(self, jpeg_bytes: bytes, max_bytes: int) -> Optional[bytes]:
        """Re-encode a JPEG at lower quality to fit within size limits."""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(jpeg_bytes))

            for q in (60, 40, 25, 15):
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=q)
                if buf.tell() <= max_bytes:
                    return buf.getvalue()

            ratio = 0.5
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=30)
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Downscale failed: {e}")
            return None

    @staticmethod
    def _parse_resolution(resolution: str) -> tuple[int, int]:
        try:
            parts = resolution.lower().split("x")
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 640, 480

    def close(self):
        if self._local_cap and self._local_cap.isOpened():
            self._local_cap.release()


# ─────────────────────────────────────────────
# Telemetry Analyzer — infer user state from sensor data
# ─────────────────────────────────────────────

class TelemetryAnalyzer:
    """Lightweight state-machine that infers user physical state from sensor readings."""

    def __init__(self):
        self._hr_history: deque[int] = deque(maxlen=30)
        self._accel_history: deque[float] = deque(maxlen=20)

    def update(self, vitals: dict, imu: dict) -> str:
        hr = vitals.get("ppg_heart_rate", 0)
        if hr > 0:
            self._hr_history.append(hr)

        accel = imu.get("accel_xyz", [0, 0, 0])
        magnitude = math.sqrt(sum(a * a for a in accel))
        self._accel_history.append(magnitude)

        return self._classify()

    def _classify(self) -> str:
        if not self._hr_history:
            return "unknown"

        avg_hr = sum(self._hr_history) / len(self._hr_history)
        avg_accel = sum(self._accel_history) / len(self._accel_history) if self._accel_history else 9.81
        accel_variance = self._variance(self._accel_history) if len(self._accel_history) > 2 else 0.0
        hr_variance = self._variance(self._hr_history) if len(self._hr_history) > 5 else 0.0

        if avg_hr > 130 and avg_accel > 12:
            return "running"
        if avg_hr > 100 and accel_variance > 2.0:
            return "walking"
        if avg_hr > 100 and hr_variance > 100:
            return "stressed"
        if avg_hr < 80 and accel_variance < 0.5:
            return "resting"
        return "active"

    @staticmethod
    def _variance(data: deque) -> float:
        if len(data) < 2:
            return 0.0
        mean = sum(data) / len(data)
        return sum((x - mean) ** 2 for x in data) / len(data)


# ─────────────────────────────────────────────
# W300 Node — Main Daemon
# ─────────────────────────────────────────────

class W300Node:
    def __init__(self, brain_url: str, api_key: str, dev_camera: bool = False, vision_interval: float = 0):
        self.brain_ws_url = f"{brain_url}/v1/node?api_key={api_key}"
        self.node_id = f"daemon_{socket.gethostname()}-w300-{uuid.uuid4().hex[:4]}"
        self.node_type = "glasses"
        self.brain_ws = None
        self.running = True
        self.mac_address = None
        self._ble_client: Optional[BleakClient] = None

        # Vision
        self.vision = VisionCapture(dev_camera=dev_camera)
        self.vision_interval = vision_interval
        self.last_frame_id: Optional[str] = None

        # Telemetry state
        self.analyzer = TelemetryAnalyzer()
        self.hr_buffer: deque[int] = deque(maxlen=5)
        self.current_hr = 0
        self.battery_pct = 100
        self.firmware_version = ""
        self.rssi_dbm = 0

        # IMU state
        self.accel_xyz = [0.0, 0.0, 9.81]
        self.gyro_xyz = [0.0, 0.0, 0.0]

        # SpO2 / environment
        self.spo2_pct = 0
        self.ambient_light_lux = 0
        self.skin_temperature_c = 0.0

    # ─── BLE Connection ───

    async def _unpair_and_repair_mac(self, address: str):
        """macOS specific fallback logic to un-bond hung bluetooth connections via blueutil."""
        logger.warning(f"Attempting deep macOS Bluetooth reset for {address}...")
        try:
            subprocess.run(["blueutil", "--unpair", address], check=False, capture_output=True)
            await asyncio.sleep(2)
            subprocess.run(["blueutil", "--pair", address], check=False, capture_output=True)
            logger.info("Deep pairing reset sequence completed.")
        except Exception as e:
            logger.error(f"Failed to reset bluetooth via blueutil (is it installed?): {e}")

    async def discover_and_connect_w300(self):
        """Scans for W300 and connects via Bleak, subscribing to all available services."""
        while self.running:
            try:
                logger.info("Scanning for W300 Smart Glasses...")
                devices = await BleakScanner.discover(timeout=5.0)
                w300_device = None

                for d in devices:
                    if d.name and W300_DEVICE_NAME in d.name:
                        w300_device = d
                        self.mac_address = d.address
                        break

                if not w300_device:
                    logger.info("W300 not found. Retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue

                logger.info(f"Establishing BLE connection to {W300_DEVICE_NAME} [{self.mac_address}]...")
                async with BleakClient(w300_device) as client:
                    self._ble_client = client
                    logger.info("BLE Connected successfully to W300!")

                    await self._subscribe_all_services(client)
                    await self.vision.probe_ble_camera(client)

                    while client.is_connected and self.running:
                        await asyncio.sleep(1.0)

            except BleakError as e:
                logger.error(f"Bluetooth connection failed: {e}")
                if self.mac_address:
                    await self._unpair_and_repair_mac(self.mac_address)
            except Exception as e:
                logger.error(f"Unexpected BLE fault: {e}")
                await asyncio.sleep(3)
            finally:
                self._ble_client = None

    async def _subscribe_all_services(self, client: BleakClient):
        """Enumerate GATT services and subscribe to every characteristic we understand."""
        available_uuids = {str(c.uuid).lower() for s in client.services for c in s.characteristics}
        logger.info(f"GATT characteristics discovered: {len(available_uuids)}")

        subscriptions = {
            HR_MEASUREMENT_UUID: self._on_heart_rate,
            W300_IMU_DATA_UUID: self._on_imu_data,
            W300_SPO2_UUID: self._on_spo2_data,
            W300_AMBIENT_LIGHT_UUID: self._on_ambient_light,
        }

        for char_uuid, handler in subscriptions.items():
            if char_uuid.lower() in available_uuids:
                try:
                    await client.start_notify(char_uuid, handler)
                    logger.info(f"Subscribed to {char_uuid}")
                except Exception as e:
                    logger.warning(f"Could not subscribe to {char_uuid}: {e}")

        # One-shot reads
        if BATTERY_LEVEL_UUID.lower() in available_uuids:
            try:
                data = await client.read_gatt_char(BATTERY_LEVEL_UUID)
                self.battery_pct = data[0] if data else 100
                logger.info(f"Battery level: {self.battery_pct}%")
            except Exception:
                pass

        if DEVICE_INFO_UUID.lower() in available_uuids:
            try:
                data = await client.read_gatt_char(DEVICE_INFO_UUID)
                self.firmware_version = data.decode("utf-8", errors="replace").strip()
                logger.info(f"Firmware: {self.firmware_version}")
            except Exception:
                pass

    # ─── BLE Notification Handlers ───

    def _on_heart_rate(self, sender, data):
        """Decode incoming PPG/HeartRate byte stream from W300 (GATT 0x2A37)."""
        flags = data[0]
        hr_16bit = flags & 0x01

        if hr_16bit:
            heart_rate = int.from_bytes(data[1:3], byteorder="little")
        else:
            heart_rate = data[1]

        self.hr_buffer.append(heart_rate)
        self.current_hr = int(sum(self.hr_buffer) / len(self.hr_buffer))

    def _on_imu_data(self, sender, data):
        """Decode vendor-specific IMU packet: 6x int16 (accel XYZ + gyro XYZ) in mg / mdps."""
        try:
            if len(data) >= 12:
                raw = struct.unpack("<6h", data[:12])
                self.accel_xyz = [raw[0] / 1000.0 * 9.81, raw[1] / 1000.0 * 9.81, raw[2] / 1000.0 * 9.81]
                self.gyro_xyz = [raw[3] / 1000.0, raw[4] / 1000.0, raw[5] / 1000.0]
        except Exception as e:
            logger.debug(f"IMU parse error: {e}")

    def _on_spo2_data(self, sender, data):
        """Decode SpO2 reading."""
        try:
            if len(data) >= 1:
                self.spo2_pct = data[0]
        except Exception:
            pass

    def _on_ambient_light(self, sender, data):
        """Decode ambient light sensor (lux as uint16 LE)."""
        try:
            if len(data) >= 2:
                self.ambient_light_lux = struct.unpack("<H", data[:2])[0]
        except Exception:
            pass

    # ─── Brain Connection ───

    async def connect_brain(self):
        """Connect to the ASOS Brain and run event loops."""
        while self.running:
            try:
                async with websockets.connect(self.brain_ws_url) as ws:
                    self.brain_ws = ws
                    logger.info("Connected to ASOS Brain. Registering Glasses...")

                    register_msg = {
                        "hop": "daemon",
                        "type": "node_register",
                        "payload": {
                            "node_id": self.node_id,
                            "node_type": self.node_type,
                            "capabilities": [
                                "telemetry",
                                "capture_frame",
                                "actuator_display",
                                "imu",
                                "spo2",
                                "ambient_light",
                            ],
                        },
                    }
                    await ws.send(json.dumps(register_msg))

                    tasks = [
                        asyncio.create_task(self._listen_loop()),
                        asyncio.create_task(self._telemetry_loop()),
                    ]

                    if self.vision_interval > 0:
                        tasks.append(asyncio.create_task(self._vision_loop()))

                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                    for task in pending:
                        task.cancel()

            except Exception as e:
                logger.warning(f"Lost connection to Brain ({e}). Retrying in 5s...")
                await asyncio.sleep(5)

    # ─── Event Loops ───

    async def _listen_loop(self):
        """Listen for ASOS commands."""
        try:
            async for message in self.brain_ws:
                data = json.loads(message)
                msg_type = data.get("type")
                if msg_type == "execute":
                    await self._handle_command(data.get("payload", {}), data.get("msg_id"))
                elif msg_type == "vision_request":
                    await self._handle_vision_request(data.get("payload", {}), data.get("msg_id"))
        except websockets.ConnectionClosed:
            pass

    async def _handle_command(self, payload: dict, msg_id: str):
        """Execute physical display, camera, or actuator hooks dispatched by Brain."""
        executor = payload.get("executor", "")
        args = payload.get("args", {})
        logger.info(f"GLASSES CMD: {executor} | Args: {args}")

        if executor == "capture_frame":
            resolution = args.get("resolution", "640x480")
            quality = args.get("quality", 80)
            frame = await self.vision.grab_frame(resolution=resolution, quality=quality)

            if frame:
                self.last_frame_id = frame["frame_id"]
                vision_msg = {
                    "hop": "daemon",
                    "type": "vision_frame",
                    "payload": {
                        "node_id": self.node_id,
                        **frame,
                    },
                }
                await self.brain_ws.send(json.dumps(vision_msg))
                result_msg = f"Frame captured: {frame['frame_id']} ({frame['metadata']['size_bytes']} bytes)"
            else:
                result_msg = "Frame capture failed — no camera backend available"

            resp = {
                "hop": "daemon",
                "type": "execute_result",
                "payload": {
                    "request_id": msg_id,
                    "status": "success" if frame else "failure",
                    "stdout": result_msg,
                },
            }
            await self.brain_ws.send(json.dumps(resp))
            return

        # Default passthrough for other executors (display, etc.)
        resp = {
            "hop": "daemon",
            "type": "execute_result",
            "payload": {
                "request_id": msg_id,
                "status": "success",
                "stdout": f"Executed {executor}",
            },
        }
        await self.brain_ws.send(json.dumps(resp))

    async def _handle_vision_request(self, payload: dict, msg_id: str):
        """Handle a direct vision_request from Brain (not wrapped in execute)."""
        resolution = payload.get("resolution", "640x480")
        quality = payload.get("quality", 80)
        reason = payload.get("reason", "")
        logger.info(f"Vision request (reason={reason}): {resolution} q={quality}")

        frame = await self.vision.grab_frame(resolution=resolution, quality=quality)
        if frame:
            self.last_frame_id = frame["frame_id"]
            vision_msg = {
                "hop": "daemon",
                "type": "vision_frame",
                "msg_id": msg_id,
                "payload": {
                    "node_id": self.node_id,
                    **frame,
                },
            }
            await self.brain_ws.send(json.dumps(vision_msg))
        else:
            logger.warning("Vision request failed — no camera backend available")

    async def _vision_loop(self):
        """Periodic frame capture loop (enabled via --vision-interval)."""
        logger.info(f"Vision loop started (interval={self.vision_interval}s)")
        try:
            while self.running:
                await asyncio.sleep(self.vision_interval)

                frame = await self.vision.grab_frame(resolution="640x480", quality=70)
                if frame and self.brain_ws:
                    self.last_frame_id = frame["frame_id"]
                    vision_msg = {
                        "hop": "daemon",
                        "type": "vision_frame",
                        "payload": {
                            "node_id": self.node_id,
                            **frame,
                        },
                    }
                    await self.brain_ws.send(json.dumps(vision_msg))
                    logger.debug(f"Periodic frame sent: {frame['frame_id']}")

        except websockets.ConnectionClosed:
            pass

    async def _telemetry_loop(self):
        """Structured ASOS telemetry loop with expanded sensor channels."""
        try:
            while self.running:
                vitals = {
                    "ppg_heart_rate": self.current_hr,
                    "spo2_pct": self.spo2_pct,
                    "skin_temperature_c": self.skin_temperature_c,
                }
                imu = {
                    "accel_xyz": self.accel_xyz,
                    "gyro_xyz": self.gyro_xyz,
                    "head_pose_euler": self._estimate_head_pose(),
                }

                inferred_state = self.analyzer.update(vitals, imu)

                telemetry = {
                    "hop": "daemon",
                    "type": "telemetry",
                    "payload": {
                        "node_id": self.node_id,
                        "sensors": {
                            "vitals": vitals,
                            "imu": imu,
                            "environment": {
                                "ambient_light_lux": self.ambient_light_lux,
                            },
                            "device": {
                                "battery_pct": self.battery_pct,
                                "connectivity": "ble_bonded" if self._ble_client and self._ble_client.is_connected else "disconnected",
                                "rssi_dbm": self.rssi_dbm,
                                "firmware_version": self.firmware_version,
                            },
                            "vision": {
                                "last_frame_id": self.last_frame_id or "",
                            },
                            "inferred_state": inferred_state,
                        },
                        "timestamp": time.time(),
                    },
                }
                if self.brain_ws:
                    await self.brain_ws.send(json.dumps(telemetry))

                await asyncio.sleep(2.0)
        except websockets.ConnectionClosed:
            pass

    def _estimate_head_pose(self) -> list[float]:
        """Rough head pose from accelerometer (pitch/roll in degrees, yaw=0)."""
        ax, ay, az = self.accel_xyz
        magnitude = math.sqrt(ax * ax + ay * ay + az * az)
        if magnitude < 0.01:
            return [0.0, 0.0, 0.0]
        pitch = math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az)))
        roll = math.degrees(math.atan2(ay, math.sqrt(ax * ax + az * az)))
        return [pitch, roll, 0.0]

    # ─── Lifecycle ───

    async def run(self):
        """Start both the BLE discovery and Brain websocket streams."""
        await asyncio.gather(
            self.discover_and_connect_w300(),
            self.connect_brain(),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="W300 Hardware bridge")
    parser.add_argument("--brain", default="ws://localhost:9090")
    parser.add_argument("--api-key", default="dev-secret-key")
    parser.add_argument("--dev-camera", action="store_true", help="Use local webcam as camera fallback for development")
    parser.add_argument("--vision-interval", type=float, default=0, help="Seconds between periodic frame captures (0=disabled)")
    parser.add_argument("--tcp-camera", default="", help="TCP camera endpoint host (e.g. 192.168.1.50)")
    parser.add_argument("--tcp-camera-port", type=int, default=8890, help="TCP camera endpoint port")
    args = parser.parse_args()

    node = W300Node(
        brain_url=args.brain,
        api_key=args.api_key,
        dev_camera=args.dev_camera,
        vision_interval=args.vision_interval,
    )

    if args.tcp_camera:
        node.vision.set_tcp_endpoint(args.tcp_camera, args.tcp_camera_port)

    try:
        asyncio.run(node.run())
    except KeyboardInterrupt:
        logger.info("Daemon shutting down")
        node.running = False
        node.vision.close()
