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

### Buzz actuator uses a placeholder GATT UUID by default

The default `WRISTBAND_BUZZ_UUID` (`0000fe10-...`) is a **placeholder**.
No real wristband on the market will vibrate when we write to it — the
UUID isn't standardised anywhere.

Three signs you're running with the placeholder:

1. At daemon boot you'll see a warning log:

   ```
   WRISTBAND_BUZZ_UUID is a PLACEHOLDER (0000fe10-...). Heart-rate and
   SpO2 readings will work, but the buzz actuator will not actually
   vibrate any real wristband until you export
   FERAL_WRISTBAND_BUZZ_UUID=<vendor-uuid>.
   ```

2. Every successful buzz call emits another warning:

   ```
   Buzz GATT write succeeded against the PLACEHOLDER UUID ... Real
   wristbands won't actuate.
   ```

3. v2 Devices page shows a yellow **"Buzz: placeholder UUID"** chip on
   the wristband card. This is driven by the daemon declaring a
   ``haptic_placeholder`` capability in its ``node_register`` payload
   alongside the regular ``haptic`` one.

### Fix: set the real vendor UUID

Find the vendor haptic GATT characteristic UUID in your wristband's
SDK docs and export:

```bash
export FERAL_WRISTBAND_BUZZ_UUID="0000xxxx-0000-1000-8000-00805f9b34fb"
python -m wristband_daemon
```

On next boot the warning disappears, the Devices page drops the chip,
and buzz writes hit the real characteristic.

### Audio relay

Audio relay is opt-in and only fires if the wristband exposes a
recognized audio stream. Most wristbands don't — this is scaffolded for
the glasses+wristband combo case where the wristband is a mic-on-wrist
companion.
