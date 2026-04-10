#!/usr/bin/env python3
"""
Reference THEORA phone bridge daemon.

This process simulates a phone node that can:
- Register to THEORA Brain over WebSocket
- Receive node.invoke commands and return execute_result payloads
- Stream sensor data and glasses bridge status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import random
import socket
import time
from uuid import uuid4

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("theora.phone_bridge")


def normalize_ws_base(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif not url.startswith(("ws://", "wss://")):
        url = "ws://" + url
    return url.rstrip("/")


class PhoneBridgeDaemon:
    def __init__(
        self,
        brain_url: str,
        api_key: str,
        node_id: str | None = None,
        glasses_model: str = "THEORA-Health-v1",
        sensor_interval_s: float = 5.0,
    ):
        self.base_url = normalize_ws_base(brain_url)
        self.api_key = api_key
        self.ws_url = f"{self.base_url}/v1/node?api_key={self.api_key}"
        self.node_id = node_id or f"{socket.gethostname()}-phone-{uuid4().hex[:6]}"
        self.glasses_model = glasses_model
        self.sensor_interval_s = max(1.0, sensor_interval_s)
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.running = True

    async def run(self) -> None:
        while self.running:
            try:
                logger.info("Connecting to %s", self.ws_url)
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
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
                        exc = task.exception()
                        if exc:
                            raise exc
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
        return {"success": True, "data": {"note": "Stub camera snap (replace with native iOS/Android camera call).", "resolution": args.get("resolution", "1080p")}}

    async def _camera_clip(self, args: dict) -> dict:
        duration_s = int(args.get("duration_s", 5))
        return {"success": True, "data": {"note": "Stub camera clip.", "duration_s": duration_s}}

    async def _location_get(self, args: dict) -> dict:
        lat = 47.6062 + random.uniform(-0.001, 0.001)
        lon = -122.3321 + random.uniform(-0.001, 0.001)
        return {"success": True, "data": {"latitude": lat, "longitude": lon, "source": "simulated"}}

    async def _sensor_read(self, args: dict) -> dict:
        sensor_name = args.get("sensor_name", "all")
        all_data = {
            "battery_pct": random.randint(30, 100),
            "ambient_temp_c": round(22 + random.uniform(-2, 2), 1),
            "accelerometer": {"x": random.uniform(-0.2, 0.2), "y": random.uniform(-0.2, 0.2), "z": 1 + random.uniform(-0.05, 0.05)},
        }
        if sensor_name == "all":
            return {"success": True, "data": all_data}
        return {"success": True, "data": {sensor_name: all_data.get(sensor_name, "unavailable")}}

    async def _health_read(self, args: dict) -> dict:
        return {"success": True, "data": {"heart_rate": random.randint(62, 90), "spo2": random.randint(95, 99), "source": "simulated"}}

    async def _audio_play(self, args: dict) -> dict:
        return {"success": True, "data": {"note": "Stub audio playback.", "url": args.get("url", "")}}

    async def _audio_tts(self, args: dict) -> dict:
        text = args.get("text", "")
        logger.info("TTS request: %s", text[:100])
        return {"success": True, "data": {"spoken_preview": text[:100]}}

    async def _notify(self, args: dict) -> dict:
        title = args.get("title", "THEORA")
        body = args.get("body", "")
        logger.info("Notification -> %s: %s", title, body)
        return {"success": True, "data": {"sent": True, "title": title}}

    async def _system_run(self, args: dict) -> dict:
        if os.getenv("THEORA_PHONE_BRIDGE_ALLOW_SYSTEM_RUN", "0") != "1":
            return {"success": False, "error": "system.run disabled by default. Set THEORA_PHONE_BRIDGE_ALLOW_SYSTEM_RUN=1 to enable."}
        command = args.get("command", "")
        if not command:
            return {"success": False, "error": "Missing command"}
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
        return {"success": True, "data": {"note": "Stub screen record command.", "action": args.get("action", "start")}}

    async def _sensor_loop(self) -> None:
        assert self.ws is not None
        while True:
            now = time.time()
            readings = {
                "phone": {
                    "battery_pct": random.randint(30, 100),
                    "network": random.choice(["wifi", "5g"]),
                },
                "health": {
                    "heart_rate": random.randint(62, 90),
                    "spo2": random.randint(95, 99),
                },
            }
            await self.ws.send(
                json.dumps(
                    {
                        "hop": "daemon",
                        "type": "sensor_batch",
                        "payload": {"readings": readings, "timestamp": now},
                    }
                )
            )
            await self.ws.send(
                json.dumps(
                    {
                        "hop": "daemon",
                        "type": "glasses_status",
                        "payload": {
                            "glasses_connected": True,
                            "battery_level": random.randint(40, 100),
                            "glasses_model": self.glasses_model,
                        },
                    }
                )
            )
            await asyncio.sleep(self.sensor_interval_s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="THEORA phone bridge reference daemon")
    parser.add_argument("--brain", default=os.getenv("THEORA_BRAIN_WS", "ws://localhost:9090"), help="Brain base URL (ws://host:port)")
    parser.add_argument("--api-key", default=os.getenv("NODE_API_KEY", "dev-secret-key"), help="NODE_API_KEY used by /v1/node")
    parser.add_argument("--node-id", default=os.getenv("THEORA_NODE_ID", ""), help="Optional static node id")
    parser.add_argument("--glasses-model", default=os.getenv("THEORA_GLASSES_MODEL", "THEORA-Health-v1"))
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
