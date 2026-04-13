# FERAL Phone Bridge (Reference Daemon)

Reference Python daemon that connects a phone-like node to FERAL Brain over WebSocket.

This is a developer template for the architecture:

```text
Glasses/Sensors --> Phone (Bridge) --> Brain (localhost:9090) --> Actions
```

## What it does

- Connects to `ws://<brain-host>:9090/v1/node?api_key=<NODE_API_KEY>`
- Registers as a `phone` node with capabilities (camera, location, health, audio, notifications)
- Listens for `command` messages and replies with `execute_result`
- Emits `sensor_batch` and `glasses_status` events on an interval
- Includes stub handlers you can replace with native iOS/Android calls

## Quick start

```bash
cd feral-nodes/phone-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export NODE_API_KEY=<your-secret-key>
python bridge.py --brain ws://localhost:9090
```

## Notes

- This daemon is intentionally lightweight and cross-platform.
- For production mobile apps, port this logic to Swift/Kotlin/React Native/Flutter.
- `system.run` is disabled by default for safety.
  Enable only for trusted test environments:
  `FERAL_PHONE_BRIDGE_ALLOW_SYSTEM_RUN=1`.
