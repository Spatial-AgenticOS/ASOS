#!/usr/bin/env python3
"""
FERAL Phone Bridge (Python reference)

Reference daemon for turning a Linux/macOS/Windows host into a FERAL
companion node. Uses real system sensors only - any unavailable sensor
returns {"success": false, "reason": "..."}.

For full phone capabilities (HealthKit, Health Connect, motion, camera),
use the native FERAL Node apps for iOS and Android in feral-nodes/ios-app/
and feral-nodes/android-app/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import socket
import time
from uuid import uuid4

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("feral.phone_bridge")


def normalize_ws_base(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif not url.startswith(("ws://", "wss://")):
        url = "ws://" + url
    return url.rstrip("/")


def _try_real_location() -> dict:
    """Attempt to get real location from the host OS. Returns result dict."""
    system = platform.system()

    if system == "Darwin":
        try:
            import CoreLocation  # pyobjc
            mgr = CoreLocation.CLLocationManager.alloc().init()
            loc = mgr.location()
            if loc:
                return {
                    "success": True,
                    "data": {
                        "latitude": loc.coordinate().latitude,
                        "longitude": loc.coordinate().longitude,
                        "source": "core_location",
                    },
                }
        except ImportError:
            pass

    if system == "Linux":
        try:
            import subprocess
            result = subprocess.run(
                ["gdbus", "call", "--system",
                 "--dest", "org.freedesktop.GeoClue2",
                 "--object-path", "/org/freedesktop/GeoClue2/Manager",
                 "--method", "org.freedesktop.GeoClue2.Manager.GetClient"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "data": {"source": "geoclue", "note": "geoclue available"},
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if system == "Windows":
        try:
            from winrt.windows.devices.geolocation import Geolocator
            locator = Geolocator()
            pos = locator.get_geoposition_async().get()
            coord = pos.coordinate.point.position
            return {
                "success": True,
                "data": {
                    "latitude": coord.latitude,
                    "longitude": coord.longitude,
                    "source": "windows_geolocation",
                },
            }
        except (ImportError, Exception):
            pass

    return {
        "success": False,
        "reason": "location_service_not_available_on_this_host",
        "hint": "Install pyobjc (macOS), geoclue (Linux), or use the native mobile apps",
    }


_QUERY_AUTH_DEPRECATION_WARNING = (
    "Brain rejected Bearer auth — retrying with ?api_key= query "
    "(DEPRECATED, will stop working in 2026.7.0)"
)


class PhoneBridgeDaemon:
    def __init__(
        self,
        brain_url: str,
        api_key: str,
        node_id: str | None = None,
        glasses_model: str = "FERAL-Health-v1",
        sensor_interval_s: float = 5.0,
    ):
        self.base_url = normalize_ws_base(brain_url)
        self.api_key = api_key
        self.ws_url = f"{self.base_url}/v1/node"
        self.node_id = node_id or f"{socket.gethostname()}-phone-{uuid4().hex[:6]}"
        self.glasses_model = glasses_model
        self.sensor_interval_s = max(1.0, sensor_interval_s)
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.running = True

    @staticmethod
    def _is_auth_rejection(exc: Exception) -> bool:
        """Return True if *exc* indicates the brain refused our credentials."""
        if isinstance(exc, websockets.InvalidStatus):
            return exc.response.status_code == 401
        if isinstance(exc, websockets.ConnectionClosedError):
            return exc.rcvd is not None and exc.rcvd.code == 4001
        return False

    async def _run_session(self, *, use_query_auth: bool = False) -> None:
        """Run a single WebSocket session against the brain."""
        if use_query_auth:
            url = f"{self.ws_url}?api_key={self.api_key}"
            headers = None
        else:
            url = self.ws_url
            headers = {"Authorization": f"Bearer {self.api_key}"}
        async with websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            self.ws = ws
            await self._register()
            listener = asyncio.create_task(self._listen_loop())
            sensors = asyncio.create_task(self._sensor_loop())
            done, pending = await asyncio.wait(
                [listener, sensors],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                if task.exception():
                    raise task.exception()

    async def run(self) -> None:
        while self.running:
            try:
                logger.info("Connecting to %s", self.ws_url)
                try:
                    await self._run_session()
                except (
                    websockets.InvalidStatus,
                    websockets.ConnectionClosedError,
                ) as exc:
                    if not self._is_auth_rejection(exc):
                        raise
                    logger.warning(_QUERY_AUTH_DEPRECATION_WARNING)
                    await self._run_session(use_query_auth=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Bridge disconnected: %s", exc)
                await asyncio.sleep(3)

    async def _register(self) -> None:
        assert self.ws is not None
        register = {
            "hop": "daemon",
            "type": "node_register",
            "payload": {
                "node_id": self.node_id,
                "node_type": "phone",
                "os": platform.platform(),
                "platform": "ios" if platform.system() == "Darwin" else platform.system().lower(),
                "capabilities": [
                    "camera.snap",
                    "camera.clip",
                    "location.get",
                    "sensor.read",
                    "health.read",
                    "audio.play",
                    "audio.tts",
                    "notification.send",
                    "system.run",
                ],
            },
        }
        await self.ws.send(json.dumps(register))
        logger.info("Registered phone bridge node_id=%s", self.node_id)

    async def _listen_loop(self) -> None:
        assert self.ws is not None
        async for raw in self.ws:
            message = json.loads(raw)
            msg_type = message.get("type", "")
            if msg_type == "command":
                await self._handle_command(message)
            elif msg_type == "text_response":
                logger.info("Brain ack: %s", message.get("payload", {}).get("text", ""))
            else:
                logger.debug("Unhandled inbound message: %s", msg_type)

    async def _handle_command(self, message: dict) -> None:
        assert self.ws is not None
        command = message.get("command", "")
        request_id = message.get("request_id", "")
        args = message.get("args", {}) or {}
        result = await self._dispatch(command, args)
        response = {
            "hop": "daemon",
            "type": "execute_result",
            "payload": {"request_id": request_id, **result},
        }
        await self.ws.send(json.dumps(response))

    async def _dispatch(self, command: str, args: dict) -> dict:
        handlers = {
            "camera.snap": self._camera_snap,
            "camera.clip": self._camera_clip,
            "location.get": self._location_get,
            "sensor.read": self._sensor_read,
            "health.read": self._health_read,
            "audio.play": self._audio_play,
            "audio.tts": self._audio_tts,
            "notification.send": self._notify,
            "system.run": self._system_run,
            "screen.record": self._screen_record,
        }
        handler = handlers.get(command)
        if not handler:
            return {"success": False, "error": f"Unknown command: {command}"}
        try:
            return await handler(args)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _camera_snap(self, args: dict) -> dict:
        return {
            "success": False,
            "reason": "camera_not_available_on_host_bridge",
            "hint": "Use the native FERAL Node app for iOS or Android for camera capture.",
        }

    async def _camera_clip(self, args: dict) -> dict:
        return {
            "success": False,
            "reason": "video_not_available_on_host_bridge",
            "hint": "Use the native FERAL Node app for iOS or Android for video recording.",
        }

    async def _location_get(self, args: dict) -> dict:
        return _try_real_location()

    async def _sensor_read(self, args: dict) -> dict:
        sensor_name = args.get("sensor_name", "all")
        try:
            import psutil
        except ImportError:
            return {
                "success": False,
                "reason": "psutil_not_installed",
                "hint": "Install psutil for real system metrics: pip install psutil",
            }

        data = {}
        if sensor_name in ("all", "battery"):
            bat = psutil.sensors_battery()
            if bat:
                data["battery_pct"] = bat.percent
                data["power_plugged"] = bat.power_plugged
        if sensor_name in ("all", "cpu"):
            data["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        if sensor_name in ("all", "network"):
            net_stats = psutil.net_if_stats()
            active = [k for k, v in net_stats.items() if v.isup and k != "lo"]
            data["active_interfaces"] = active
            net_io = psutil.net_io_counters()
            data["bytes_sent"] = net_io.bytes_sent
            data["bytes_recv"] = net_io.bytes_recv
        if sensor_name in ("all", "temperature"):
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    first = next(iter(temps.values()))[0]
                    data["ambient_temp_c"] = first.current
            except Exception:
                pass

        if not data:
            return {
                "success": False,
                "reason": f"sensor_{sensor_name}_not_available",
                "hint": "This host does not expose the requested sensor. Use the native mobile apps for accelerometer, gyroscope, etc.",
            }

        data["source"] = "psutil"
        return {"success": True, "data": data}

    async def _health_read(self, args: dict) -> dict:
        return {
            "success": False,
            "reason": "no_health_sensor_on_host_bridge",
            "hint": "Health data requires the native FERAL Node app with HealthKit (iOS) or Health Connect (Android), or a paired BLE wristband.",
        }

    async def _audio_play(self, args: dict) -> dict:
        return {
            "success": False,
            "reason": "audio_playback_not_available_on_host_bridge",
            "hint": "Use the native mobile app for audio playback.",
        }

    async def _audio_tts(self, args: dict) -> dict:
        text = args.get("text", "")
        if not text:
            return {"success": False, "reason": "no_text_provided"}
        system = platform.system()
        if system == "Darwin":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "say", text,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                return {"success": True, "data": {"spoken_preview": text[:100], "engine": "macos_say"}}
            except FileNotFoundError:
                pass
        return {
            "success": False,
            "reason": "tts_not_available_on_this_host",
            "hint": "Install a TTS engine or use the native mobile app.",
        }

    async def _notify(self, args: dict) -> dict:
        title = args.get("title", "FERAL")
        body = args.get("body", "")
        system = platform.system()
        if system == "Darwin":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e",
                    f'display notification "{body}" with title "{title}"',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                return {"success": True, "data": {"sent": True, "title": title}}
            except FileNotFoundError:
                pass
        logger.info("[NOTIFICATION] %s: %s", title, body)
        return {"success": True, "data": {"sent": True, "title": title, "method": "log"}}

    async def _system_run(self, args: dict) -> dict:
        if os.getenv("FERAL_PHONE_BRIDGE_ALLOW_SYSTEM_RUN", "0") != "1":
            return {"success": False, "reason": "system_run_disabled", "hint": "Set FERAL_PHONE_BRIDGE_ALLOW_SYSTEM_RUN=1 to enable."}
        command = args.get("command", "")
        if not command:
            return {"success": False, "reason": "missing_command"}
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "success": proc.returncode == 0,
            "data": {"stdout": stdout.decode()[:4000], "stderr": stderr.decode()[:2000], "exit_code": proc.returncode},
        }

    async def _screen_record(self, args: dict) -> dict:
        return {
            "success": False,
            "reason": "screen_recording_not_available_on_host_bridge",
            "hint": "Use the native mobile app for screen recording.",
        }

    async def _sensor_loop(self) -> None:
        """Push real telemetry from psutil. Skip ticks when no real data is available."""
        assert self.ws is not None

        try:
            import psutil
        except ImportError:
            logger.warning("psutil not installed — telemetry loop disabled. Install: pip install psutil")
            return

        while True:
            readings = {}

            bat = psutil.sensors_battery()
            if bat:
                readings["battery_pct"] = bat.percent
                readings["power_plugged"] = bat.power_plugged

            net_stats = psutil.net_if_stats()
            active = [k for k, v in net_stats.items() if v.isup and k != "lo"]
            if active:
                readings["network_interfaces_up"] = len(active)

            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    first = next(iter(temps.values()))[0]
                    readings["cpu_temp_c"] = first.current
            except Exception:
                pass

            readings["cpu_percent"] = psutil.cpu_percent(interval=None)

            if readings:
                readings["source"] = "psutil"
                await self.ws.send(
                    json.dumps({
                        "hop": "daemon",
                        "type": "sensor_batch",
                        "payload": {"readings": readings, "timestamp": time.time()},
                    })
                )

            await asyncio.sleep(self.sensor_interval_s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FERAL phone bridge reference daemon")
    parser.add_argument("--brain", default=os.getenv("FERAL_BRAIN_WS", "ws://localhost:9090"), help="Brain base URL (ws://host:port)")
    parser.add_argument("--api-key", default=os.getenv("NODE_API_KEY", ""), help="NODE_API_KEY used by /v1/node")
    parser.add_argument("--node-id", default=os.getenv("FERAL_NODE_ID", ""), help="Optional static node id")
    parser.add_argument("--glasses-model", default=os.getenv("FERAL_GLASSES_MODEL", "FERAL-Health-v1"))
    parser.add_argument("--sensor-interval", type=float, default=5.0, help="Telemetry interval in seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    daemon = PhoneBridgeDaemon(
        brain_url=args.brain,
        api_key=args.api_key,
        node_id=args.node_id or None,
        glasses_model=args.glasses_model,
        sensor_interval_s=args.sensor_interval,
    )
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        logger.info("Phone bridge stopped by user")


if __name__ == "__main__":
    main()
