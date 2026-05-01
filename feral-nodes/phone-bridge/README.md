# FERAL Phone Bridge (Reference Daemon)

Reference Python daemon that connects a phone-like node to FERAL Brain over WebSocket.

This is a developer template for the architecture:

```text
Glasses/Sensors --> Phone (Bridge) --> Brain (localhost:9090) --> Actions
```

## What it does

- Connects to `wss://<brain-host>/v1/node` (or `ws://` for LAN-only) with an
  `Authorization: Bearer <token>` header
- Falls back to `?api_key=` query if the brain rejects Bearer with close code
  4001 (pre-Bearer brains during the deprecation window)
- Registers as a `phone` node with capabilities (camera, location, health,
  audio, notifications)
- Listens for `command` messages and replies with `execute_result`
- Emits `sensor_batch` and `glasses_status` events on an interval
- Includes stub handlers you can replace with native iOS/Android calls

## Quick start

```bash
cd feral-nodes/phone-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python bridge.py --brain wss://my-brain.<tailnet>.ts.net --api-key <token>
```

For LAN-only setups (Mode A), `ws://` is accepted:

```bash
python bridge.py --brain ws://192.168.1.42:9090 --api-key <token>
```

## Authentication

The bridge sends credentials via the `Authorization: Bearer` HTTP header
during the WebSocket upgrade. This is the recommended method for all new
deployments.

**Deprecation notice:** The legacy `?api_key=` query-string method is
deprecated and will be removed in **2026.7.0**. During the deprecation
window the bridge automatically retries with query auth if Bearer is
rejected (close code 4001), but you should upgrade your brain to accept
Bearer as soon as possible.

## Transport security

Use `wss://` (TLS) for any deployment outside a trusted LAN. The bridge
preserves the scheme you pass — it will **never** silently downgrade
`wss://` to `ws://`. If a TLS handshake fails, the error is surfaced
directly so you can fix certificates or connectivity.

## Notes

- This daemon is intentionally lightweight and cross-platform.
- For production mobile apps, port this logic to Swift/Kotlin/React Native/Flutter.
- `system.run` is disabled by default for safety.
  Enable only for trusted test environments:
  `FERAL_PHONE_BRIDGE_ALLOW_SYSTEM_RUN=1`.
