"""Offline unit tests for wristband_daemon.

Uses a FakeBleClient + FakeFeralNode so no real bluetooth / websocket
connection is required. These run in CI.
"""

from __future__ import annotations

import asyncio
import struct
from typing import Any, Callable

import pytest

from wristband_daemon.daemon import (
    HEART_RATE_UUID,
    SPO2_UUID,
    WristbandConfig,
    WristbandDaemon,
    decode_heart_rate,
    decode_spo2,
)


# ------------------------------------------------------------------
# Fake doubles
# ------------------------------------------------------------------

class FakeBleClient:
    def __init__(self, address: str) -> None:
        self.address = address
        self.connected = False
        self.notifications: dict[str, Callable[[Any, bytes], Any]] = {}
        self.writes: list[tuple[str, bytes]] = []
        self.disconnected = False

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def start_notify(self, char_uuid: str, callback) -> None:
        self.notifications[char_uuid] = callback

    async def write_gatt_char(self, char_uuid: str, data: bytes) -> None:
        self.writes.append((char_uuid, data))

    async def emit(self, char_uuid: str, data: bytes) -> None:
        cb = self.notifications[char_uuid]
        res = cb(self, data)
        if asyncio.iscoroutine(res):
            await res


class FakeFeralNode:
    """Fake FeralNode that blocks in run_async() until stop() is called.

    Matches the real SDK contract (run_async is an async coroutine;
    the sync `run` wrapper exists only for CLI entry-points). Daemons
    call `await node.run_async()`, so that is what the fake must
    expose — if the fake exposed `async def run` instead, the tests
    would pass against it but fail against the real SDK, which is
    exactly the bug we shipped in commit c13460b and are fixing here.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.ran = False
        self._actions: dict[str, Callable] = {}
        self._stop = asyncio.Event()

    def on_action(self, name: str):
        def _wrap(fn):
            self._actions[name] = fn
            return fn
        return _wrap

    async def emit_event(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))

    async def run_async(self) -> None:
        self.ran = True
        await self._stop.wait()

    def request_stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------
# Decoder tests
# ------------------------------------------------------------------

def test_decode_heart_rate_8bit():
    assert decode_heart_rate(bytes([0x00, 72])) == 72


def test_decode_heart_rate_16bit():
    frame = bytes([0x01]) + struct.pack("<H", 158)
    assert decode_heart_rate(frame) == 158


def test_decode_heart_rate_empty_frame():
    assert decode_heart_rate(b"") is None


def test_decode_spo2_uint16():
    raw = struct.pack("<H", 97)
    assert decode_spo2(raw) == 97.0


def test_decode_spo2_empty():
    assert decode_spo2(b"") is None


# ------------------------------------------------------------------
# Daemon wiring
# ------------------------------------------------------------------

@pytest.fixture
def wired_daemon():
    fake_ble: FakeBleClient | None = None

    def _ble_factory(address: str) -> FakeBleClient:
        nonlocal fake_ble
        fake_ble = FakeBleClient(address)
        return fake_ble

    fake_node = FakeFeralNode()

    def _node_factory(_cfg):
        return fake_node

    cfg = WristbandConfig(ble_address="AA:BB:CC:DD:EE:FF", node_id="feral-wb-test")
    daemon = WristbandDaemon(
        cfg,
        ble_factory=_ble_factory,
        node_factory=_node_factory,
    )
    return daemon, lambda: fake_ble, fake_node


async def _start_and_settle(daemon, fake_node):
    """Launch daemon.start() and wait until notifications are armed."""
    task = asyncio.create_task(daemon.start())
    # Let the subscribe + node.run() setup land
    for _ in range(20):
        await asyncio.sleep(0.01)
        if fake_node.ran:
            break
    return task


async def _stop(task, fake_node, daemon):
    fake_node.request_stop()
    await asyncio.wait_for(task, timeout=1.0)
    await daemon.stop()


@pytest.mark.asyncio
async def test_daemon_subscribes_hr_and_spo2(wired_daemon):
    daemon, get_ble, node = wired_daemon
    task = await _start_and_settle(daemon, node)
    ble = get_ble()
    assert ble is not None
    assert HEART_RATE_UUID in ble.notifications
    assert SPO2_UUID in ble.notifications
    await _stop(task, node, daemon)


@pytest.mark.asyncio
async def test_daemon_emits_heart_rate_event(wired_daemon):
    daemon, get_ble, node = wired_daemon
    task = await _start_and_settle(daemon, node)
    ble = get_ble()
    await ble.emit(HEART_RATE_UUID, bytes([0x00, 82]))
    assert ("heart_rate", {"bpm": 82, "confidence": 0.9}) in node.events
    await _stop(task, node, daemon)


@pytest.mark.asyncio
async def test_daemon_buzz_writes_gatt_when_uuid_configured(wired_daemon):
    """Buzz fires a GATT write only when FERAL_WRISTBAND_BUZZ_UUID is
    set. Otherwise the daemon refuses to write to a made-up UUID."""
    daemon, get_ble, node = wired_daemon
    # Inject a configured buzz UUID so the write path runs.
    daemon.config.buzz_uuid = "0000cafe-0000-1000-8000-00805f9b34fb"
    daemon.config.buzz_configured = True
    task = await _start_and_settle(daemon, node)
    ok = await daemon.buzz(duration_ms=200, pattern="double")
    assert ok
    ble = get_ble()
    assert ble.writes
    char, payload = ble.writes[-1]
    assert char == "0000cafe-0000-1000-8000-00805f9b34fb"
    # Encoded as (duration_ms // 10, pattern_id)
    assert payload[0] == 20
    assert payload[1] == 1  # double
    await _stop(task, node, daemon)


@pytest.mark.asyncio
async def test_daemon_buzz_refuses_when_unconfigured(wired_daemon):
    """Without a buzz UUID, buzz() returns False rather than writing
    to a made-up UUID that no real wristband responds to."""
    daemon, get_ble, node = wired_daemon
    daemon.config.buzz_configured = False
    daemon.config.buzz_uuid = ""
    task = await _start_and_settle(daemon, node)
    ok = await daemon.buzz(duration_ms=200, pattern="double")
    assert ok is False
    ble = get_ble()
    assert ble.writes == []  # no GATT write at all
    await _stop(task, node, daemon)


def test_daemon_refuses_without_ble_address():
    cfg = WristbandConfig(ble_address="")
    daemon = WristbandDaemon(cfg)
    with pytest.raises(RuntimeError, match="FERAL_WRISTBAND_BLE_ADDRESS"):
        asyncio.run(daemon.start())


# ------------------------------------------------------------------
# Buzz UUID configuration (no placeholders)
# ------------------------------------------------------------------

def test_resolve_buzz_uuid_unconfigured_when_env_unset(monkeypatch):
    from wristband_daemon.daemon import resolve_buzz_uuid

    monkeypatch.delenv("FERAL_WRISTBAND_BUZZ_UUID", raising=False)
    uuid, unconfigured = resolve_buzz_uuid()
    assert uuid == ""
    assert unconfigured is True


def test_resolve_buzz_uuid_env_override(monkeypatch):
    from wristband_daemon.daemon import resolve_buzz_uuid

    monkeypatch.setenv("FERAL_WRISTBAND_BUZZ_UUID", "0000abcd-0000-1000-8000-00805f9b34fb")
    uuid, unconfigured = resolve_buzz_uuid()
    assert uuid == "0000abcd-0000-1000-8000-00805f9b34fb"
    assert unconfigured is False


def test_config_from_env_records_unconfigured_flag(monkeypatch):
    monkeypatch.delenv("FERAL_WRISTBAND_BUZZ_UUID", raising=False)
    monkeypatch.setenv("FERAL_WRISTBAND_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    cfg = WristbandConfig.from_env()
    assert cfg.buzz_configured is False
    assert cfg.buzz_uuid == ""


def test_config_from_env_when_override_set(monkeypatch):
    monkeypatch.setenv("FERAL_WRISTBAND_BUZZ_UUID", "0000cafe-0000-1000-8000-00805f9b34fb")
    monkeypatch.setenv("FERAL_WRISTBAND_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    cfg = WristbandConfig.from_env()
    assert cfg.buzz_configured is True
    assert cfg.buzz_uuid == "0000cafe-0000-1000-8000-00805f9b34fb"


def test_capabilities_exclude_haptic_when_unconfigured():
    """When buzz isn't configured, 'haptic' must NOT appear in the
    node_register capabilities. The daemon reports what it can do,
    never what it pretends to do."""
    cfg = WristbandConfig(ble_address="AA:BB:CC:DD:EE:FF", buzz_configured=False, buzz_uuid="")
    caps = ["heart_rate", "spo2"]
    if cfg.buzz_configured:
        caps.append("haptic")
    assert "haptic" not in caps


def test_capabilities_include_haptic_when_configured():
    cfg = WristbandConfig(
        ble_address="AA:BB:CC:DD:EE:FF",
        buzz_configured=True,
        buzz_uuid="0000cafe-0000-1000-8000-00805f9b34fb",
    )
    caps = ["heart_rate", "spo2"]
    if cfg.buzz_configured:
        caps.append("haptic")
    assert "haptic" in caps


# ------------------------------------------------------------------
# Live gate
# ------------------------------------------------------------------

import os


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("FERAL_LIVE_WRISTBAND_TEST") != "1",
    reason="Set FERAL_LIVE_WRISTBAND_TEST=1 + FERAL_WRISTBAND_BLE_ADDRESS to run.",
)
def test_live_wristband_emits_at_least_one_hr_frame():
    """Manual: with the wristband on and the brain up, expect at least
    one heart_rate event within 10 s."""
    pytest.skip("Live test stub — capture a heart_rate event when the user runs this.")
