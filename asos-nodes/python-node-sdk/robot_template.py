#!/usr/bin/env python3
"""
ASOS Node SDK — Robot Actuator Template
========================================
This template allows you to connect any physical robot (ROS, serial, I2C, etc.) 
to the Spatial-AgenticOS Brain.

To run:
    python3 robot_template.py --brain ws://localhost:9090
"""

import asyncio
import json
import logging
import argparse
import socket
import uuid
import time
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("robot_node")

class RobotNode:
    def __init__(self, brain_url: str, api_key: str):
        self.brain_ws_url = f"{brain_url}/v1/node?api_key={api_key}"
        self.node_id = f"daemon_{socket.gethostname()}-robot-{uuid.uuid4().hex[:4]}"
        self.node_type = "actuator"
        self.ws = None
        self.running = True

    async def connect(self):
        """Connect to the ASOS Brain."""
        while self.running:
            try:
                logger.info(f"Connecting to ASOS Brain at {self.brain_ws_url}...")
                async with websockets.connect(self.brain_ws_url) as ws:
                    self.ws = ws
                    logger.info("Connected! Registering Robot Node...")
                    
                    # 1. Register
                    register_msg = {
                        "hop": "daemon",
                        "type": "node_register",
                        "payload": {
                            "node_id": self.node_id,
                            "node_type": self.node_type,
                            "capabilities": ["telemetry", "robot_move", "robot_grip"]
                        }
                    }
                    await ws.send(json.dumps(register_msg))
                    
                    # 2. Setup Loop
                    listener = asyncio.create_task(self._listen_loop())
                    telemetry = asyncio.create_task(self._telemetry_loop())
                    
                    done, pending = await asyncio.wait(
                        [listener, telemetry],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    for task in pending:
                        task.cancel()
                        
            except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
                logger.warning(f"Connection lost. Retrying... ({e})")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(5)

    async def _listen_loop(self):
        """Listen for physical commands from the ASOS LLM hook."""
        try:
            async for message in self.ws:
                data = json.loads(message)
                if data.get("type") == "execute":
                    await self._handle_command(data.get("payload", {}), data.get("msg_id"))
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed.")

    async def _handle_command(self, payload: dict, msg_id: str):
        """Execute a physical command bound to the Hook pipeline."""
        executor = payload.get("executor", "")
        args = payload.get("args", {})
        
        logger.info(f"EXECUTING ROBOT CMD: {executor} | Args: {args}")
        
        # --- Robot Actuator Logic Here ---
        success = True
        result_msg = ""
        
        if executor == "robot_move":
            direction = args.get("direction", "forward")
            speed = args.get("speed", 30)
            logger.info(f"Robot moving {direction} at {speed}% speed")
            result_msg = f"Moved robot {direction} successfully"
            
        elif executor == "robot_grip":
            action = args.get("action", "close")
            logger.info(f"Robot gripper {action}")
            result_msg = f"Gripper {action} successful"
            
        else:
            success = False
            result_msg = f"Unknown command: {executor}"
            logger.error(result_msg)

        # Acknowledge execution back to ASOS
        resp = {
            "hop": "daemon",
            "type": "execute_result",
            "payload": {
                "request_id": msg_id,
                "status": "success" if success else "error",
                "stdout": result_msg if success else "",
                "error": result_msg if not success else ""
            }
        }
        await self.ws.send(json.dumps(resp))
        logger.info(f"Result sent to Brain for request: {msg_id}")

    async def _telemetry_loop(self):
        """Standard ROS-like telemetry topic loop."""
        try:
            while self.running:
                # Simulating physical state feedback
                telemetry = {
                    "hop": "daemon",
                    "type": "telemetry",
                    "payload": {
                        "node_id": self.node_id,
                        "sensors": {
                            "battery_pct": 98.5,
                            "joint_temperatures": [42.1, 41.5, 39.8],
                            "status": "idle"
                        },
                        "timestamp": time.time()
                    }
                }
                if self.ws:
                    await self.ws.send(json.dumps(telemetry))
                await asyncio.sleep(5.0)
        except websockets.ConnectionClosed:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASOS Robot Node SDK")
    parser.add_argument("--brain", default="ws://localhost:9090", help="WebSocket URL of ASOS Brain")
    parser.add_argument("--api-key", default="dev-secret-key", help="Authentication key for Brain connection")
    args = parser.parse_args()

    node = RobotNode(args.brain, args.api_key)
    try:
        asyncio.run(node.connect())
    except KeyboardInterrupt:
        logger.info("Node shutting down")
        node.running = False
