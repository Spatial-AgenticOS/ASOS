"""Tests for MQTT Bridge — TLS, persistent client, auth, graceful degradation."""
import asyncio
import os
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.mqtt_bridge import MQTTBridge, _build_ssl_context


# ─── Configuration & startup ────────────────────────────────────


class TestMQTTBridgeConfig:
    def test_no_broker_returns_early(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="")
        assert bridge.configured is False

    @pytest.mark.asyncio
    async def test_start_without_broker_logs_and_returns_false(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="")
        result = await bridge.start()
        assert result is False

    @pytest.mark.asyncio
    async def test_publish_before_start_returns_false(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="test-broker")
        result = await bridge.publish("test/topic", {"hello": "world"})
        assert result is False

    @pytest.mark.asyncio
    async def test_publish_while_running_no_client_returns_false(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="test-broker")
        bridge._running = True
        bridge._client = None
        result = await bridge.publish("test/topic", {"data": 1})
        assert result is False

    def test_custom_topics_from_env(self, monkeypatch):
        monkeypatch.setenv("FERAL_MQTT_TOPICS", "a/b,c/d")
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge()
        assert bridge._topics == ["a/b", "c/d"]


# ─── TLS ─────────────────────────────────────────────────────────


class TestMQTTTLS:
    def test_tls_default_system_ca(self, monkeypatch):
        monkeypatch.setenv("FERAL_MQTT_TLS", "true")
        monkeypatch.delenv("FERAL_MQTT_CA_CERT", raising=False)
        monkeypatch.delenv("FERAL_MQTT_CLIENT_CERT", raising=False)
        monkeypatch.delenv("FERAL_MQTT_CLIENT_KEY", raising=False)
        ctx = _build_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)

    def test_tls_flag_false_by_default(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_TLS", raising=False)
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        assert bridge._tls_enabled is False

    def test_tls_flag_enabled(self, monkeypatch):
        monkeypatch.setenv("FERAL_MQTT_TLS", "true")
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        assert bridge._tls_enabled is True

    def test_client_kwargs_includes_tls_when_enabled(self, monkeypatch):
        monkeypatch.setenv("FERAL_MQTT_TLS", "1")
        monkeypatch.delenv("FERAL_MQTT_CA_CERT", raising=False)
        monkeypatch.delenv("FERAL_MQTT_CLIENT_CERT", raising=False)
        monkeypatch.delenv("FERAL_MQTT_CLIENT_KEY", raising=False)
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        kw = bridge._client_kwargs()
        assert "tls_context" in kw
        assert isinstance(kw["tls_context"], ssl.SSLContext)

    def test_client_kwargs_omits_tls_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_TLS", raising=False)
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        kw = bridge._client_kwargs()
        assert "tls_context" not in kw


# ─── Auth ────────────────────────────────────────────────────────


class TestMQTTAuth:
    def test_username_password_from_env(self, monkeypatch):
        monkeypatch.setenv("FERAL_MQTT_USERNAME", "testuser")
        monkeypatch.setenv("FERAL_MQTT_PASSWORD", "secret")
        monkeypatch.delenv("FERAL_MQTT_TLS", raising=False)
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        kw = bridge._client_kwargs()
        assert kw["username"] == "testuser"
        assert kw["password"] == "secret"

    def test_no_auth_when_not_set(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_USERNAME", raising=False)
        monkeypatch.delenv("FERAL_MQTT_PASSWORD", raising=False)
        monkeypatch.delenv("FERAL_MQTT_TLS", raising=False)
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        kw = bridge._client_kwargs()
        assert "username" not in kw
        assert "password" not in kw


# ─── Persistent client ───────────────────────────────────────────


class TestMQTTPersistentClient:
    @pytest.mark.asyncio
    async def test_publish_uses_persistent_client(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        monkeypatch.delenv("FERAL_MQTT_TLS", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        bridge._running = True

        mock_client = AsyncMock()
        bridge._client = mock_client

        result = await bridge.publish("test/topic", {"val": 42})
        assert result is True
        mock_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_publishes_serialized(self, monkeypatch):
        """The publish lock ensures serial access to the shared client."""
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        monkeypatch.delenv("FERAL_MQTT_TLS", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        bridge._running = True

        call_order = []

        async def slow_publish(topic, payload):
            call_order.append(f"start-{topic}")
            await asyncio.sleep(0.05)
            call_order.append(f"end-{topic}")

        mock_client = AsyncMock()
        mock_client.publish = slow_publish
        bridge._client = mock_client

        await asyncio.gather(
            bridge.publish("t/1", {}),
            bridge.publish("t/2", {}),
        )
        assert call_order[0] == "start-t/1" or call_order[0] == "start-t/2"
        assert call_order[1].startswith("end-")


# ─── Message handling ────────────────────────────────────────────


class TestMQTTMessageHandling:
    @pytest.mark.asyncio
    async def test_handle_ha_discovery(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        await bridge._handle_ha_discovery(
            "homeassistant/sensor/temp1/config",
            {"name": "Temperature", "state_topic": "sensor/temp1/state"},
        )
        assert "temp1" in bridge._devices
        assert bridge._devices["temp1"]["name"] == "Temperature"

    @pytest.mark.asyncio
    async def test_handle_message_increments_count(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        bridge = MQTTBridge(broker_url="broker")
        assert bridge._message_count == 0
        await bridge._handle_message("sensor/test", b'{"value": 1}')
        assert bridge._message_count == 1

    def test_stats(self, monkeypatch):
        monkeypatch.delenv("FERAL_MQTT_BROKER", raising=False)
        monkeypatch.delenv("FERAL_MQTT_TLS", raising=False)
        bridge = MQTTBridge(broker_url="test-broker")
        s = bridge.stats()
        assert s["configured"] is True
        assert s["broker"] == "test-broker"
        assert "tls_enabled" in s


# ─── Integration test (off by default) ───────────────────────────


@pytest.mark.skipif(
    not os.getenv("FERAL_MQTT_IT"),
    reason="Set FERAL_MQTT_IT=1 and provide a live broker to run integration tests",
)
class TestMQTTIntegration:
    @pytest.mark.asyncio
    async def test_publish_subscribe_roundtrip(self):
        """Requires a real MQTT broker (e.g. mosquitto on localhost:1883)."""
        import aiomqtt

        broker = os.getenv("FERAL_MQTT_BROKER", "localhost")
        topic = "feral/test/roundtrip"
        received = asyncio.Event()
        received_payload = {}

        async def subscriber():
            async with aiomqtt.Client(hostname=broker) as client:
                await client.subscribe(topic)
                async for msg in client.messages:
                    received_payload.update({"data": msg.payload.decode()})
                    received.set()
                    break

        sub_task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.5)

        async with aiomqtt.Client(hostname=broker) as pub:
            await pub.publish(topic, '{"test": true}')

        try:
            await asyncio.wait_for(received.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("Did not receive MQTT message within 5 seconds")
        finally:
            sub_task.cancel()

        assert "test" in received_payload.get("data", "")
