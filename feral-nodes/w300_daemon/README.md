# w300_daemon — FERAL HUP v1.1 W300 Smart-Glasses Node

First-party HUP v1.1 daemon for the W300 (or W300-compatible)
smart glasses. Streams JPEG video frames to the FERAL Brain using
HUP v1.1 `video_frame` (§5.4.2) and optional microphone audio using
`audio_frame` (§5.4.1).

This daemon talks to **real hardware the user owns**. Unit tests run
offline against fake camera + audio sources; the live test is gated
behind `FERAL_LIVE_W300_TEST=1` so CI never tries to open a ghost
device.

## Usage

```bash
# Offline unit tests
pytest feral-nodes/w300_daemon/tests -m 'not live'

# Live test — user plugs the glasses in and runs this
export FERAL_LIVE_W300_TEST=1
export FERAL_BRAIN_URL=ws://127.0.0.1:9090
export FERAL_API_KEY=$NODE_API_KEY
pytest feral-nodes/w300_daemon/tests -m live

# Run as a daemon
python -m w300_daemon --vision-interval 5
```

## HUP mapping

| Daemon behaviour | HUP v1.1 wire frame |
|---|---|
| Periodic JPEG frame grab | `device_event` with `payload.event_type = "video_frame"` (v1.1 §5.4.2) |
| Microphone stream (Opus) | `device_event` with `payload.event_type = "audio_frame"` (v1.1 §5.4.1) |
| IMU sample | `device_event` with `payload.event_type = "imu"` |
| Nod / shake / tap gesture | `device_event` with `payload.event_type = "gesture"` |

## Honest limitations

- Camera access uses the local UVC path (`/dev/video0` or macOS AVFoundation).
  If your W300 variant exposes frames over BLE or WiFi-Direct, swap the
  backend in `daemon.py::CameraCapture.open()`. The historical
  `feral-nodes/python-node-sdk/w300_daemon.py` reference implementation
  covers all three backend paths and can be copied verbatim when ready.
- Audio relay requires an OS-level audio-input device; `pyaudio` /
  `sounddevice` integration is left as a TODO because the codec choice
  (hardware Opus vs CPU Opus) depends on the exact glasses SKU.
- Display actuators are scaffolded via `hup_action_request` but the
  actual drawing surface is vendor-specific.

## Relationship to the historical `w300_daemon.py`

[`feral-nodes/python-node-sdk/w300_daemon.py`](../python-node-sdk/w300_daemon.py)
is a 1-file monolithic reference implementation written before HUP v1.1.
This directory is the Track B canonical package layout that:

1. Publishes as a `kind=daemon` registry item (via
   `feral-registry/scripts/seed_first_party.py`).
2. Uses the HUP v1.1 `FeralNode.emit_video_frame()` helper so the
   wire contract is validated locally before every send.
3. Keeps unit tests that run in CI without real hardware.

The historical file stays in-tree as a reference.
