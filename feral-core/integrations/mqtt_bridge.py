"""FERAL MQTT Bridge — connects to any MQTT broker for IoT device integration.

Subscribes to configurable topics, maps messages to HUP device events,
publishes commands back. Supports Home Assistant MQTT auto-discovery.
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("feral.integrations.mqtt")


class MQTTBridge:
    """Bidirectional MQTT bridge for IoT devices."""

    def __init__(self, broker_url: str = "", topics: list[str] = None,
                 on_device_event: Optional[Callable] = None):
        self._broker_url = broker_url or os.getenv("FERAL_MQTT_BROKER", "")
        self._topics = topics or self._default_topics()
        self._on_device_event = on_device_event
        self._client = None
        self._running = False
        self._devices: dict[str, dict] = {}  # topic -> device info
        self._message_count = 0

    @staticmethod
    def _default_topics() -> list[str]:
        custom = os.getenv("FERAL_MQTT_TOPICS", "")
        if custom:
            return [t.strip() for t in custom.split(",")]
        return [
            "homeassistant/+/+/config",  # HA auto-discovery
            "home/+/+",                   # Common home automation pattern
            "sensor/+",                    # Generic sensors
            "zigbee2mqtt/+",              # Zigbee2MQTT devices
            "tasmota/+/+",               # Tasmota devices
        ]

    @property
    def configured(self) -> bool:
        return bool(self._broker_url)

    async def start(self) -> bool:
        if not self.configured:
            logger.info("MQTT bridge: no broker configured (set FERAL_MQTT_BROKER)")
            return False

        try:
            import aiomqtt
        except ImportError:
            logger.warning("aiomqtt not installed — MQTT bridge disabled. pip install aiomqtt")
            return False

        self._running = True
        asyncio.create_task(self._subscribe_loop())
        logger.info("MQTT bridge started: %s (topics: %s)", self._broker_url, self._topics)
        return True

    async def stop(self):
        self._running = False

    async def publish(self, topic: str, payload: dict) -> bool:
        if not self._running:
            return False
        try:
            import aiomqtt
            async with aiomqtt.Client(self._broker_url) as client:
                await client.publish(topic, json.dumps(payload))
            return True
        except Exception as e:
            logger.error("MQTT publish failed: %s", e)
            return False

    async def _subscribe_loop(self):
        import aiomqtt
        while self._running:
            try:
                async with aiomqtt.Client(self._broker_url) as client:
                    for topic in self._topics:
                        await client.subscribe(topic)
                        logger.debug("MQTT subscribed: %s", topic)

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_message(str(message.topic), message.payload)
            except Exception as e:
                if self._running:
                    logger.warning("MQTT connection lost: %s — reconnecting in 10s", e)
                    await asyncio.sleep(10)

    async def _handle_message(self, topic: str, payload: bytes):
        self._message_count += 1
        try:
            data = json.loads(payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {"raw": payload.decode(errors="replace")}

        if topic.startswith("homeassistant/"):
            await self._handle_ha_discovery(topic, data)
            return

        device_id = self._topic_to_device_id(topic)

        if self._on_device_event:
            try:
                await self._on_device_event({
                    "source": "mqtt",
                    "topic": topic,
                    "device_id": device_id,
                    "data": data,
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.warning("MQTT event handler error: %s", e)

    async def _handle_ha_discovery(self, topic: str, config: dict):
        """Process Home Assistant MQTT auto-discovery messages."""
        parts = topic.split("/")
        if len(parts) < 4:
            return

        component_type = parts[1]  # sensor, light, switch, etc.
        device_id = parts[2]

        device_info = {
            "device_id": f"mqtt_{device_id}",
            "name": config.get("name", device_id),
            "type": component_type,
            "manufacturer": config.get("device", {}).get("manufacturer", "Unknown"),
            "model": config.get("device", {}).get("model", ""),
            "state_topic": config.get("state_topic", ""),
            "command_topic": config.get("command_topic", ""),
            "unique_id": config.get("unique_id", device_id),
        }

        self._devices[device_id] = device_info

        if device_info["state_topic"]:
            try:
                import aiomqtt
                async with aiomqtt.Client(self._broker_url) as client:
                    await client.subscribe(device_info["state_topic"])
            except Exception:
                pass

        logger.info("MQTT discovered device: %s (%s) — %s", device_info["name"], component_type, device_id)

    @staticmethod
    def _topic_to_device_id(topic: str) -> str:
        parts = topic.replace("/", "_")
        return f"mqtt_{parts}"

    def list_devices(self) -> list[dict]:
        return list(self._devices.values())

    def stats(self) -> dict:
        return {
            "configured": self.configured,
            "running": self._running,
            "broker": self._broker_url,
            "topics": self._topics,
            "devices_discovered": len(self._devices),
            "messages_received": self._message_count,
        }
