#!/usr/bin/env python3
"""
THEORA Hardware Connectivity Daemon (ROS Node Prototype)
======================================================
This python daemon runs on remote hardware (Smart Glasses, Robots, IoT Sensors).
It acts like a ROS node but uses THEORA's lightweight WebSocket protocol.

Features:
1. Pushes high-frequency telemetry (Heart rate, Battery, Sensors) to the Brain.
2. Receives and executes raw physical actuator commands (LEDs, Motors, Displays).

Usage:
  python3 daemon.py --brain ws://localhost:9090
"""

import asyncio
import json
import logging
import argparse
import os
import socket
import time
import uuid

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("hardware_daemon")

class HardwareDaemon:
    def __init__(self, brain_url: str, node_type: str = "glasses", api_key: str = "dev-secret-key"):
        self.api_key = api_key
        self.brain_ws_url = f"{brain_url}/v1/node?api_key={self.api_key}"
        self.node_id = f"{socket.gethostname()}-{node_type}-{uuid.uuid4().hex[:4]}"
        self.node_type = node_type
        self.ws = None
        self.running = True

    async def connect(self):
        """Connect to the THEORA Brain."""
        while self.running:
            try:
                logger.info(f"Connecting to THEORA Brain at {self.brain_ws_url.split('?')[0]}...")
                async with websockets.connect(self.brain_ws_url) as ws:
                    self.ws = ws
                    logger.info("Connected successfully! Registering hardware node...")
                    
                    # 1. Register
                    register_msg = {
                        "hop": "daemon",
                        "type": "node_register",
                        "payload": {
                            "node_id": self.node_id,
                            "node_type": self.node_type,
                            "capabilities": ["telemetry", "actuator_led", "actuator_display", "camera"]
                        }
                    }
                    await ws.send(json.dumps(register_msg))
                    
                    # 2. Start asynchronous tasks: Listening & Telemetry
                    listener = asyncio.create_task(self._listen_loop())
                    telemetry = asyncio.create_task(self._telemetry_loop())
                    
                    # Wait until one fails
                    done, pending = await asyncio.wait(
                        [listener, telemetry],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    for task in pending:
                        task.cancel()
                        
            except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
                logger.warning(f"Connection lost or refused: {e}. Retrying in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(5)

    async def _listen_loop(self):
        """Listen for actuator commands from the Brain."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "command":
                        await self._handle_command(data)
                    else:
                        logger.info(f"Received unknown message type: {msg_type}")
                        
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode message: {message}")
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed by server.")

    async def _handle_command(self, data: dict):
        """Execute a physical command sent by the Brain's LLM."""
        req_id = data.get("request_id", "unknown")
        cmd = data.get("command", "")
        args = data.get("args", {})
        
        logger.info(f"EXECUTING HARDWARE CMD: {cmd} | Args: {args}")
        
        # --- Real Hardware Actuator Mocking ---
        result_data = None
        success = True
        error_msg = None
        
        if cmd == "set_led":
            color = args.get("color", "white")
            logger.info(f"[ACTUATOR] Setting glasses LED array to {color.upper()}")
            result_data = f"LEDs set to {color}"
            
        elif cmd == "render_display":
            text = args.get("text", "")
            logger.info(f"[ACTUATOR] Rendering text on AR display: '{text}'")
            result_data = f"Rendered '{text}' on HUD"
            
        elif cmd == "capture_frame":
            logger.info(f"[ACTUATOR] Capturing image frame from front camera...")
            # Mocking a base64 frame return
            result_data = "base64_encoded_frame_buffer_mock"
            
        else:
            logger.error(f"Unknown hardware command: {cmd}")
            success = False
            error_msg = f"Unknown command: {cmd}"
            
        # Send result back
        resp = {
            "hop": "daemon",
            "type": "execute_result",
            "payload": {
                "request_id": req_id,
                "success": success,
                "data": {"output": result_data, "error": error_msg}
            }
        }
        await self.ws.send(json.dumps(resp))
        logger.info(f"Result sent to brain for req: {req_id}")

    async def _telemetry_loop(self):
        """Continuously push sensor telemetry to the Brain (ROS Publisher equivalent)."""
        heart_rate = 70
        try:
            while True:
                # Simulate bio-metric data drift
                import random
                heart_rate += random.randint(-2, 2)
                heart_rate = max(60, min(120, heart_rate))
                
                telemetry = {
                    "hop": "daemon",
                    "type": "telemetry",
                    "payload": {
                        "node_id": self.node_id,
                        "sensors": {
                            "ppg_heart_rate": heart_rate,
                            "battery_pct": 87,
                            "imu_status": "stable",
                            "environment_temp": 22.5
                        },
                        "timestamp": time.time()
                    }
                }
                
                await self.ws.send(json.dumps(telemetry))
                logger.debug(f"Pushed telemetry: HR={heart_rate}")
                
                # Push every 2 seconds
                await asyncio.sleep(2.0)
                
        except websockets.ConnectionClosed:
            logger.info("Telemetry loop stopped (connection closed).")

def main():
    parser = argparse.ArgumentParser(description="THEORA Hardware Daemon")
    parser.add_argument("--brain", default="ws://localhost:9090", help="WebSocket URL of THEORA Brain")
    parser.add_argument("--type", default="glasses", help="Type of hardware node")
    parser.add_argument("--api-key", default=os.environ.get("NODE_API_KEY", "dev-secret-key"),
                        help="API key for Brain authentication (or set NODE_API_KEY env var)")
    args = parser.parse_args()

    daemon = HardwareDaemon(brain_url=args.brain, node_type=args.type, api_key=args.api_key)
    
    try:
        asyncio.run(daemon.connect())
    except KeyboardInterrupt:
        logger.info("Daemon shutting down linearly via Ctrl-C")
        daemon.running = False

if __name__ == "__main__":
    main()
