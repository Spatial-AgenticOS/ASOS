# HUP v1.1.0 — Additive Proposal (`audio_frame` + `video_frame`)

> **Status:** proposed (not yet merged into `HUP_SPEC.md` §5.4).
> **Version bump:** `v1.0.0` → `v1.1.0`. Strictly additive — no breaking
> changes — so daemons on v1.0.0 remain conformant and brains on v1.1.0
> must accept them.
> **Backward compatibility:** v1.0.0 brains that don't understand these
> event types MUST ignore them per the forward-compat rule in
> `HUP_SPEC.md § 1`.

## Why

[`ROADMAP_NEXT.md` Pillar A](ROADMAP_NEXT.md) needs livestream audio +
video from smart glasses into the Brain so the user can ask "what am I
looking at?" and get an answer in under 3 seconds. HUP v1.0.0 supports
sensor-scalar events but has no mechanism for frame-rate media, so each
vendor currently invents their own channel — defeating the whole point
of the protocol.

## Schema additions

Both new event types ride inside the existing `device_event` envelope
(`HUP_SPEC.md § 5.4`). Only the `payload.event_type` and `payload.data`
shape are new.

### `audio_frame`

Push audio samples from a daemon (glasses, wristband, phone-bridge,
room mic) to the brain.

```json
{
  "hup_version": "1.1.0",
  "type": "device_event",
  "ts": 1734369931.210,
  "node_id": "feral-w300-0001",
  "seq": 842,
  "payload": {
    "event_type": "audio_frame",
    "codec": "opus",
    "sample_rate": 24000,
    "channels": 1,
    "frame_ms": 20,
    "sequence": 842,
    "data_b64": "…base64(opus packet)…"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `codec` | `"opus" \| "pcm16"` | yes | Opus strongly preferred over wireless links |
| `sample_rate` | int | yes | Hz; SHOULD be 16000 or 24000 |
| `channels` | int | yes | 1 or 2 |
| `frame_ms` | int | no, default 20 | Duration of this frame |
| `sequence` | int | yes | Per-stream monotonic counter for jitter buffer |
| `data_b64` | string | yes | Base64 of the raw codec payload. Decoded size MUST be ≤ 64 KiB. |

Brain behaviour: sequence-number reorder buffer with ≤ 200 ms tolerance;
drop frames older than that. Route to
[`feral-core/perception/audio_pipeline.py`](feral-core/perception/audio_pipeline.py).

### `video_frame`

Push JPEG or H.264 video frames from a camera-capable node.

```json
{
  "hup_version": "1.1.0",
  "type": "device_event",
  "ts": 1734369931.250,
  "node_id": "feral-w300-0001",
  "seq": 843,
  "payload": {
    "event_type": "video_frame",
    "codec": "jpeg",
    "width": 1280,
    "height": 720,
    "sequence": 127,
    "keyframe": true,
    "data_b64": "…base64(frame)…"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `codec` | `"jpeg" \| "h264"` | yes | JPEG easiest for glasses at 2-5 fps; H.264 for higher rates |
| `width` | int | yes | Pixels |
| `height` | int | yes | Pixels |
| `sequence` | int | yes | Per-stream monotonic counter |
| `keyframe` | bool | H.264 only | Required for H.264; ignored for JPEG (always keyframe) |
| `data_b64` | string | yes | Base64 of the codec payload. Decoded size MUST be ≤ 512 KiB per `HUP_SPEC.md § 2`. |

Brain behaviour: drop non-keyframes that arrive before the first
keyframe of an H.264 stream. Route every decoded frame into
[`feral-core/perception/fusion.py`](feral-core/perception/fusion.py) as
a `scene_frame` input. Every 10 s, run a vision-LLM caption on the most
recent frame and store it in episodic memory.

## Systematic sync requirements

Per AGENT_PROMPT.md's systematic-sync table, the PR that promotes this
proposal into `HUP_SPEC.md` MUST also update:

1. **Pydantic mirror** — `feral-nodes/python-node-sdk/src/feral_node_sdk/schemas.py`:
   add `AudioFrameEvent` + `VideoFrameEvent` dataclasses; update
   `DEVICE_EVENT_PAYLOAD_UNION` to include them.
2. **Zod mirror** — `feral-nodes/ts-node-sdk/src/schemas.ts`: same types
   in TypeScript Zod schemas.
3. **Cookiecutter** — `feral-nodes/templates/hardware-daemon/` gains an
   `audio_or_video_example.py` showing how to wire a gstreamer pipeline
   into the SDK.
4. **Brain handler** — `feral-core/api/server.py::/v1/node` dispatches
   `event_type == "audio_frame"` to `state.audio.ingest_frame(node_id, payload)`
   and `"video_frame"` to `state.vision_buffer.push(node_id, payload)`.
5. **Version declaration** — `HUP_SPEC.md § 1`: bump the canonical
   version string and add a line to the change-log at the bottom of the
   spec file.
6. **Contract tests** — `feral-core/tests/test_hup_audio_video.py`:
   round-trip a known Opus packet and a known JPEG frame through the
   perception pipeline.

## Error codes

Reuse `HUP_SPEC.md § 8` error codes. New code:

| Code | Meaning |
|---|---|
| `4020 frame_too_large` | `data_b64` decoded to more than the per-frame cap (64 KiB for audio, 512 KiB for video). Brain closes the socket; daemon MUST reconnect with a saner encoder bitrate. |

## Acceptance gate

This proposal is merge-ready when:

1. All six systematic-sync points above have commits.
2. A test at `feral-core/tests/test_hup_audio_video.py` demonstrates
   round-trip of both event types using the Python SDK.
3. One real daemon (`w300-daemon` or `wristband-daemon`) streams
   a recorded sample that passes `perception.update_vision`.
4. A short demo clip or log is attached to the PR.

Until all four, HUP v1.1.0 remains a proposal and the spec declares
v1.0.0.
