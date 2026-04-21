"""wristband_daemon — FERAL HUP v1.1 health-wristband node.

Reads heart rate (GATT 0x2A37) and SpO2 (GATT 0x2A5E) from a paired
Bluetooth-LE wristband and emits them as HUP v1.1 ``device_event``
frames. Drives a vendor-specific buzz characteristic when the Brain
dispatches a ``buzz`` action.

The BLE layer is abstracted through a ``BleClientFactory`` callable so
unit tests can inject a fake client without monkeypatching Bleak.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import struct
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from feral_node_sdk import FeralNode

logger = logging.getLogger("feral.wristband_daemon")

# Production note (2026.4.22+):
#
# This desktop BLE daemon is ONLY useful for generic BLE-GATT health
# wristbands that expose the standard GATT Heart Rate (0x2A37) and SpO2
# (0x2A5E) profiles and don't require a vendor iOS/Android SDK. It's
# kept in-tree as a reference implementation of the HUP v1.1 daemon
# pattern.
#
# The first-party Theora wristband uses the Veepoo iOS SDK and ONLY
# pairs through an iPhone — the phone is the HUP daemon, not a
# desktop process. See feral-nodes/ios-node-sdk/ (scaffolded in
# 2026.4.22) for the real production path. Setting a haptic vendor
# UUID here does nothing useful for a Theora wristband because
# Veepoo's haptic is driven through its high-level SDK methods, not
# raw GATT writes.
HEART_RATE_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
SPO2_UUID = "00002a5e-0000-1000-8000-00805f9b34fb"


def resolve_buzz_uuid() -> tuple[str, bool]:
    """Return (uuid, is_unconfigured).

    Reads FERAL_WRISTBAND_BUZZ_UUID. When unset, returns ("", True) and
    the daemon runs without a buzz actuator — not with a pretend one.
    For Theora wristbands: use the iOS FeralNode bridge, not this
    desktop daemon.
    """
    override = (os.environ.get("FERAL_WRISTBAND_BUZZ_UUID") or "").strip()
    if override:
        return override, False
    return "", True


# ------------------------------------------------------------------
# BLE client abstraction
# ------------------------------------------------------------------

class BleClient:
    """Minimal async BLE client protocol used by the daemon.

    We intentionally decouple from Bleak at the type level so tests
    can substitute a fake without monkeypatching.
    """

    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...

    async def start_notify(
        self,
        char_uuid: str,
        callback: Callable[[Any, bytes], None],
    ) -> None: ...

    async def write_gatt_char(self, char_uuid: str, data: bytes) -> None: ...


BleClientFactory = Callable[[str], BleClient]


def _default_ble_factory(address: str) -> BleClient:
    """Wrap bleak.BleakClient in our minimal protocol."""
    try:
        from bleak import BleakClient  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "bleak is not installed. `pip install bleak` or run the daemon's "
            "offline unit tests with a fake client."
        ) from exc

    class _BleakWrapper(BleClient):
        def __init__(self, addr: str) -> None:
            self._client = BleakClient(addr)

        async def connect(self) -> bool:
            return bool(await self._client.connect())

        async def disconnect(self) -> None:
            await self._client.disconnect()

        async def start_notify(self, char_uuid: str, callback) -> None:
            await self._client.start_notify(char_uuid, callback)

        async def write_gatt_char(self, char_uuid: str, data: bytes) -> None:
            await self._client.write_gatt_char(char_uuid, data)

    return _BleakWrapper(address)


# ------------------------------------------------------------------
# Decoders
# ------------------------------------------------------------------

def decode_heart_rate(data: bytes) -> Optional[int]:
    """Decode a GATT Heart Rate Measurement frame (0x2A37).

    Returns BPM or None on a malformed frame.
    """
    if not data:
        return None
    flags = data[0]
    try:
        if flags & 0x01:
            return int.from_bytes(data[1:3], byteorder="little")
        return int(data[1])
    except IndexError:
        return None


def decode_spo2(data: bytes) -> Optional[float]:
    """Decode a SpO2 Measurement frame (0x2A5E).

    Returns percent or None on a malformed frame.
    """
    if not data:
        return None
    try:
        # GATT defines SpO2 as a SFLOAT; tolerate the trivial int case too.
        if len(data) >= 2:
            raw = struct.unpack("<H", data[:2])[0]
            return float(raw) if 0 < raw <= 1000 else None
        return float(data[0])
    except struct.error:
        return None


# ------------------------------------------------------------------
# Daemon
# ------------------------------------------------------------------

@dataclass
class WristbandConfig:
    ble_address: str = ""
    brain_url: Optional[str] = None
    api_key: Optional[str] = None
    node_id: str = "feral-wristband-0001"
    # Resolved at construction time from FERAL_WRISTBAND_BUZZ_UUID.
    # ``buzz_uuid`` is empty string (not a placeholder) when unset — the
    # daemon honestly runs without a haptic actuator rather than writing
    # to a made-up UUID that no real wristband responds to.
    buzz_uuid: str = ""
    buzz_configured: bool = False

    @classmethod
    def from_env(cls) -> "WristbandConfig":
        buzz_uuid, unconfigured = resolve_buzz_uuid()
        return cls(
            ble_address=os.environ.get("FERAL_WRISTBAND_BLE_ADDRESS", ""),
            brain_url=os.environ.get("FERAL_BRAIN_URL"),
            api_key=os.environ.get("FERAL_API_KEY"),
            node_id=os.environ.get("FERAL_WRISTBAND_NODE_ID", "feral-wristband-0001"),
            buzz_uuid=buzz_uuid,
            buzz_configured=not unconfigured,
        )


class WristbandDaemon:
    """Orchestrates BLE notifications -> HUP device_event emissions."""

    def __init__(
        self,
        config: Optional[WristbandConfig] = None,
        *,
        ble_factory: BleClientFactory = _default_ble_factory,
        node_factory: Optional[Callable[[WristbandConfig], FeralNode]] = None,
    ) -> None:
        self.config = config or WristbandConfig.from_env()
        self._ble_factory = ble_factory
        self._node_factory = node_factory or self._make_node
        self.node: Optional[FeralNode] = None
        self.ble: Optional[BleClient] = None
        self._running = False

    def _make_node(self, cfg: WristbandConfig) -> FeralNode:
        # Capabilities reflect what this daemon can actually do, not a
        # wish-list. Haptic only appears when a real buzz UUID is
        # configured (FERAL_WRISTBAND_BUZZ_UUID set). For the Theora
        # production wristband use the iOS FeralNode bridge; the
        # Veepoo SDK runs on-phone and cannot be talked to via this
        # desktop bleak daemon.
        caps = ["heart_rate", "spo2"]
        if cfg.buzz_configured:
            caps.append("haptic")
        node = FeralNode(
            node_id=cfg.node_id,
            name="FERAL Wristband",
            manufacturer="Theora",
            firmware_version="1.1.0",
            node_type="wearable",
            brain_url=cfg.brain_url,
            api_key=cfg.api_key,
            capabilities=caps,
        )

        @node.on_action("buzz")
        async def _buzz(params: dict) -> dict:
            duration_ms = int(params.get("duration_ms", 200))
            pattern = params.get("pattern", "single")
            ok = await self.buzz(duration_ms, pattern)
            return {"ok": ok, "duration_ms": duration_ms, "pattern": pattern}

        return node

    # -- BLE event handlers -----------------------------------------

    async def _on_heart_rate(self, _sender: Any, data: bytes) -> None:
        bpm = decode_heart_rate(data)
        if bpm is None:
            return
        logger.debug("HR sample: %d bpm", bpm)
        if self.node:
            await self.node.emit_event(
                "heart_rate",
                {"bpm": bpm, "confidence": 0.9},
            )

    async def _on_spo2(self, _sender: Any, data: bytes) -> None:
        spo2 = decode_spo2(data)
        if spo2 is None:
            return
        logger.debug("SpO2 sample: %.1f", spo2)
        if self.node:
            await self.node.emit_event(
                "spo2",
                {"current": spo2},
            )

    # -- Actions ----------------------------------------------------

    async def buzz(self, duration_ms: int, pattern: str = "single") -> bool:
        """Drive the vendor-specific haptic characteristic, if configured.

        Returns False when no buzz UUID is configured — we do not
        pretend-actuate against a made-up characteristic. For Theora
        wristbands the production path is the iOS bridge in
        ``feral-nodes/ios-node-sdk/`` which calls Veepoo's SDK haptic
        method directly; this desktop daemon won't reach them.
        """
        if self.ble is None:
            logger.warning("Buzz requested with no BLE client — dropping.")
            return False
        if not self.config.buzz_configured or not self.config.buzz_uuid:
            logger.warning(
                "Buzz requested but no vendor haptic UUID is configured. "
                "This daemon supports only generic GATT BLE wristbands. "
                "For Theora wristbands use the iOS FeralNode bridge "
                "(feral-nodes/ios-node-sdk/) which drives the Veepoo "
                "SDK haptic directly."
            )
            return False
        # 1B duration-tens-of-ms + 1B pattern id (vendor-specific).
        payload = struct.pack(
            "<BB",
            max(1, min(255, duration_ms // 10)),
            {"single": 0, "double": 1, "long": 2}.get(pattern, 0),
        )
        try:
            await self.ble.write_gatt_char(self.config.buzz_uuid, payload)
            return True
        except Exception as exc:
            logger.warning("Buzz GATT write failed: %s", exc)
            return False

    # -- Lifecycle --------------------------------------------------

    async def start(self) -> None:
        """Connect BLE + Brain, subscribe to notifications, block forever."""
        cfg = self.config
        if not cfg.ble_address:
            raise RuntimeError(
                "FERAL_WRISTBAND_BLE_ADDRESS is unset. The wristband daemon "
                "cannot fake a connection; export the real MAC first."
            )
        if not cfg.buzz_configured:
            logger.info(
                "wristband_daemon: buzz actuator not configured "
                "(FERAL_WRISTBAND_BUZZ_UUID unset). Heart-rate and SpO2 "
                "readings will work. For Theora wristbands use the iOS "
                "FeralNode bridge in feral-nodes/ios-node-sdk/ instead "
                "— it drives Veepoo SDK haptic directly."
            )
        else:
            logger.info(
                "wristband buzz actuator wired to vendor UUID %s",
                cfg.buzz_uuid,
            )
        self.node = self._node_factory(cfg)
        self.ble = self._ble_factory(cfg.ble_address)
        logger.info("Connecting to wristband %s...", cfg.ble_address)
        await self.ble.connect()

        await self.ble.start_notify(HEART_RATE_UUID, self._on_heart_rate)
        await self.ble.start_notify(SPO2_UUID, self._on_spo2)

        self._running = True
        logger.info("wristband_daemon online; emitting HUP v1.1 device_events.")
        # FeralNode.run_async opens the WebSocket + services inbound
        # actions. The sync FeralNode.run wraps asyncio.run; calling
        # that from inside an already-running loop would raise
        # RuntimeError, so we await the async variant.
        await self.node.run_async()  # type: ignore[union-attr]

    async def stop(self) -> None:
        self._running = False
        if self.ble is not None:
            await self.ble.disconnect()


# ------------------------------------------------------------------
# Entry points
# ------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FERAL wristband daemon")
    parser.add_argument("--ble-address", default=None, help="BLE MAC address")
    parser.add_argument("--brain-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--node-id", default=None)
    return parser.parse_args(argv)


async def _async_main(argv: Optional[list[str]] = None) -> None:
    args = _parse_args(argv)
    cfg = WristbandConfig.from_env()
    if args.ble_address:
        cfg.ble_address = args.ble_address
    if args.brain_url:
        cfg.brain_url = args.brain_url
    if args.api_key:
        cfg.api_key = args.api_key
    if args.node_id:
        cfg.node_id = args.node_id

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )
    daemon = WristbandDaemon(cfg)
    try:
        await daemon.start()
    finally:
        await daemon.stop()


def main(argv: Optional[list[str]] = None) -> None:
    asyncio.run(_async_main(argv))


if __name__ == "__main__":
    main()
