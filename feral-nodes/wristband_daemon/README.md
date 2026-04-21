# wristband_daemon — FERAL HUP v1.1 Wristband Node

First-party HUP v1.1 daemon for a Bluetooth-LE health wristband. Streams
heart-rate + SpO2 telemetry to the FERAL Brain over the HUP
`device_event` envelope and drives a haptic buzz actuator from
`hup_action_request`. If the wristband exposes an audio GATT stream,
the daemon relays it as HUP v1.1 `audio_frame` events.

This is a real daemon intended to talk to real hardware the user owns.
Unit tests run offline against a mocked Bleak client; the live test is
gated behind `FERAL_LIVE_WRISTBAND_TEST=1` so CI never tries to pair a
ghost device.

## Usage

```bash
# One-shot install into the Python SDK environment
cd feral-nodes/python-node-sdk && pip install -e .

# Offline unit tests
pytest feral-nodes/wristband_daemon/tests -m 'not live'

# Live test — user runs this with the wristband on the wrist
export FERAL_LIVE_WRISTBAND_TEST=1
export FERAL_WRISTBAND_BLE_ADDRESS=AA:BB:CC:DD:EE:FF
export FERAL_BRAIN_URL=ws://127.0.0.1:9090
export FERAL_API_KEY=$NODE_API_KEY
pytest feral-nodes/wristband_daemon/tests -m live

# Run as a daemon
python -m wristband_daemon
```

## HUP mapping

| Daemon behaviour | HUP v1.1 wire frame |
|---|---|
| Heart-rate notification from BLE GATT 0x2A37 | `device_event` with `payload.event_type = "heart_rate"` |
| SpO2 reading from BLE GATT 0x2A5E | `device_event` with `payload.event_type = "spo2"` |
| Brain asks to buzz | Inbound `hup_action_request` name `buzz` with `duration_ms` |
| Optional mic stream | `device_event` with `payload.event_type = "audio_frame"` (v1.1 §5.4.1) |

## Honest limitations

### Scope: generic GATT BLE wristbands only

This desktop daemon is intended for **generic** BLE-GATT health
wristbands that expose the standard Heart Rate (0x2A37) and SpO2
(0x2A5E) profiles and don't require a vendor SDK. It's a reference
implementation of the HUP v1.1 daemon pattern.

**It is NOT the right path for the first-party Theora wristband.**
The Theora wristband uses the Veepoo iOS SDK and only pairs through
an iPhone — the phone is the HUP daemon in that topology, not a
desktop process. See [`feral-nodes/ios-node-sdk/`](../ios-node-sdk/)
for the production bridge (scaffolded in `2026.4.22`).

### Haptic / buzz actuator

The daemon emits `heart_rate` and `spo2` events by default. It does
**not** include a `haptic` capability unless you've configured a real
vendor GATT UUID for the buzz characteristic:

```bash
export FERAL_WRISTBAND_BUZZ_UUID="0000xxxx-0000-1000-8000-00805f9b34fb"
python -m wristband_daemon
```

When unset (the default), calls to `buzz()` return `False` with a
clear log line rather than writing to a made-up UUID. The `haptic`
capability simply doesn't appear in the daemon's `node_register`
payload, so v2 Devices correctly shows it as "Haptic: unwired".

### Audio relay

Audio relay is opt-in and only fires if the wristband exposes a
recognised audio stream. Most wristbands don't — this is scaffolded
for the glasses+wristband combo case where the wristband is a
mic-on-wrist companion.
