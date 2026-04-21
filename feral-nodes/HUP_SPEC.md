# Hardware Unification Protocol (HUP) — Public Specification

**Version:** `HUP v1.1.0`
**Status:** Stable
**License:** Apache-2.0
**Canonical schemas:** this file (normative) + Pydantic mirror in
`feral-nodes/python-node-sdk/src/feral_node_sdk/schemas.py` + Zod mirror in
`feral-nodes/ts-node-sdk/src/schemas.ts`.

HUP is FERAL's public wire contract between a "brain" (the FERAL orchestrator
runtime) and a "node daemon" (a process running on or near a piece of
hardware). It is the equivalent, for heterogeneous hardware, of what the USB
HID class spec was for input devices: a stable, versioned, vendor-neutral
protocol that lets any vendor plug hardware into any FERAL brain without
proprietary glue.

If you can terminate TLS and speak JSON over WebSocket, you can speak HUP.

---

## 1. Overview and Versioning

- HUP is a JSON message protocol carried over a single persistent WebSocket.
- Versioning follows semantic versioning (`MAJOR.MINOR.PATCH`):
  - **MAJOR** — breaking changes to message envelopes, handshake, or
    required field types. Clients MUST negotiate (see `node_register`).
  - **MINOR** — additive fields, new message types, or new capability
    categories. Clients MUST ignore unknown fields and unknown message
    types (forward-compatibility requirement).
  - **PATCH** — clarifications, non-normative edits.
- Daemons announce the spec they were built against in `node_register.hup_version`.
  Brains SHOULD accept any `HUP v1.*` daemon but MAY reject `HUP v2.*` with
  error code `1002 bad_schema`.
- **Backward-compat rule:** once a field is published in a minor version, it
  stays. New fields MUST be optional.

---

## 2. Transport

| Property            | Value                                                        |
|---------------------|--------------------------------------------------------------|
| URL                 | `wss://<brain-host>:<port>/v1/node`                          |
| Subprotocol         | `feral.hup.v1` (optional — for middlebox negotiation)        |
| TLS                 | Required on non-loopback addresses. `ws://` allowed only on `localhost`, `127.0.0.1`, or `::1`. |
| Message format      | JSON text frames, UTF-8, one message per frame.              |
| Max frame size      | 1 MiB. `device_event` frames carrying binary (base64) MUST stay ≤ 512 KiB of decoded payload. |
| Connections         | Exactly **one** persistent WS per `node_id`. A second connect with the same `node_id` kicks the first. |
| Reconnect           | Client MUST reconnect with jittered exponential backoff: initial 100 ms, factor 2, cap 30 s, full jitter. |
| Keepalive           | `node_heartbeat` every `heartbeat_ms` (default 10000). Brain MAY close with `1001 unauthorized` style code `4004 stale_heartbeat` if 3× interval elapses with no frame. |

---

## 3. Handshake Sequence

```
daemon                                    brain
  |  --- WS upgrade (Authorization: Bearer <key>) --->
  |  <-- 101 Switching Protocols ----------------------
  |  --- node_register --------------------------->
  |  <-- node_ack  {node_id,session_token,heartbeat_ms}
  |
  |  === steady state ===
  |  --> node_heartbeat (every heartbeat_ms)
  |  --> device_event  (sensor pushes)
  |  <-- hup_action_request
  |  --> hup_action_response
  |  ...
  |  --> node_bye                 (graceful shutdown)
  |  <-- TCP FIN
```

1. Client opens WS. First message MUST be `node_register`.
2. Brain validates schema + credentials and replies with `node_ack` within
   5 s, or closes the socket with one of the error codes in §8.
3. After `node_ack`, either side MAY send any valid post-handshake message
   (`device_event`, `hup_action_request`, `hup_action_response`,
   `node_heartbeat`, `node_bye`).
4. If the daemon does not receive `node_ack` within 5 s it MUST close and
   reconnect with backoff.

---

## 4. Pairing and Authentication

HUP separates **first-time pairing** (how the daemon gets a long-lived API
key) from **steady-state auth** (how it authenticates each WS session).

### 4.1 First-time pairing

1. On first launch the daemon generates and prints a **6-digit numeric
   code** (uniform random, leading zeros preserved). Example: `417 392`.
2. The user opens the FERAL UI → **Settings → Devices → Pair**, types the
   6-digit code, optionally a friendly name (e.g. "Acme Wristband"), and
   hits *Pair*.
3. The brain calls `POST /api/devices/pair` with
   `{"code":"417392","name":"Acme Wristband","node_id":"acme-wb-001"}`
   and returns `{"token":"<api-key>","device_id":"..."}`.
4. The daemon polls `GET /api/devices/pair/status?code=417392` (or receives
   the token over mDNS — see §4.3) until it gets the token.
5. The daemon persists the token to `~/.feral/node-keys/<node_id>.key`
   (mode `0600`) and forgets the 6-digit code.

The pairing window is 5 minutes; codes expire after that or after one
successful redemption, whichever comes first. Failed codes rate-limit at
5 attempts / 5 minutes per source IP.

### 4.2 Steady-state

Every WS upgrade MUST carry the API key in exactly one of:

- `Authorization: Bearer <key>` header (preferred).
- `?api_key=<key>` query parameter (fallback for clients that cannot set
  headers, e.g. browser `WebSocket`).
- `Sec-WebSocket-Protocol: feral-token-<key>` (fallback for environments
  that only expose the subprotocol hook).

### 4.3 Discovery (mDNS)

Brains SHOULD advertise `_feral-brain._tcp.local.` with TXT records:

```
version=1
node_path=/v1/node
tls=1
```

Node SDKs SHOULD prefer discovered brains on the local network over any
hard-coded URL.

---

## 5. Message Envelope

Every HUP frame is a JSON object with:

```json
{
  "hup_version": "1.0.0",
  "type": "<message-type>",
  "ts": 1734369922.123,
  "payload": { ... }
}
```

- `type` — one of the types below. Unknown types MUST be ignored (not
  errored).
- `ts` — seconds since Unix epoch, float, millisecond precision.
- `payload` — per-message schema.

### 5.1 `node_register` (daemon → brain, first frame)

```json
{
  "hup_version": "1.0.0",
  "type": "node_register",
  "ts": 1734369920.001,
  "payload": {
    "node_id": "acme-wb-001",
    "node_type": "wearable",
    "name": "Acme Wristband",
    "manufacturer": "Acme Corp",
    "model": "WB-1",
    "firmware_version": "1.2.3",
    "platform": "zephyr",
    "os": "",
    "capabilities": ["heart_rate", "accelerometer", "buzzer", "battery"],
    "sensors": ["heart_rate", "accelerometer", "battery"],
    "actuators": ["buzzer"],
    "location": "wrist",
    "tags": ["wearable", "health"]
  }
}
```

JSON Schema:

```json
{
  "$id": "https://feral.ai/schemas/hup/v1/node_register.json",
  "type": "object",
  "required": ["node_id", "node_type", "capabilities"],
  "properties": {
    "node_id":          {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,128}$"},
    "node_type":        {"type": "string", "enum": [
      "desktop", "server", "rpi", "robot", "glasses", "phone",
      "actuator", "sensor", "wearable", "camera", "vehicle", "appliance"
    ]},
    "name":             {"type": "string", "maxLength": 128},
    "manufacturer":     {"type": "string", "maxLength": 128},
    "model":            {"type": "string", "maxLength": 128},
    "firmware_version": {"type": "string", "maxLength": 64},
    "platform":         {"type": "string"},
    "os":               {"type": "string"},
    "capabilities":     {"type": "array", "items": {"$ref": "#/$defs/capability"}},
    "sensors":          {"type": "array", "items": {"type": "string"}},
    "actuators":        {"type": "array", "items": {"type": "string"}},
    "location":         {"type": "string"},
    "tags":             {"type": "array", "items": {"type": "string"}}
  },
  "$defs": {
    "capability": {"type": "string", "enum": [
      "heart_rate", "spo2", "temperature", "uv", "accelerometer",
      "gyroscope", "ambient_light", "steps", "battery",
      "gps", "microphone", "camera",
      "display", "speaker", "haptic", "buzzer", "led", "motor",
      "relay", "valve", "keyboard", "applescript", "filesystem",
      "gpio", "shell", "telemetry", "passive_sensor", "active_actuator"
    ]}
  }
}
```

The capability vocabulary is derived verbatim from the `sensors`/
`actuators` and `category` fields in `ASOS/feral-core/hardware/protocol.py`
and from the raw capability string list in `NodeRegisterPayload`
(`ASOS/feral-core/models/protocol.py`). New vendors MAY add capability
strings outside the enum, but brains MAY ignore unknown capabilities for
gating. Each capability string maps to a **tier** for policy purposes:

| Tier                | Examples                                  | Default allowed |
|---------------------|-------------------------------------------|-----------------|
| `passive_sensor`    | heart_rate, spo2, temperature, accelerometer, ambient_light, battery | yes |
| `camera`            | camera                                    | requires user opt-in |
| `audio`             | microphone, speaker                       | requires user opt-in |
| `active_actuator`   | haptic, buzzer, led, display              | yes, rate-limited |
| `motor`             | motor, relay, valve, vehicle              | off by default — per-command confirmation |

### 5.2 `node_ack` (brain → daemon)

```json
{
  "hup_version": "1.0.0",
  "type": "node_ack",
  "ts": 1734369920.040,
  "payload": {
    "node_id": "acme-wb-001",
    "session_token": "b58c2c34-...",
    "heartbeat_ms": 10000,
    "server_time": 1734369920.040,
    "granted_capabilities": ["heart_rate", "buzzer", "battery"],
    "denied_capabilities":  ["camera"]
  }
}
```

### 5.3 `node_heartbeat` (daemon → brain, every `heartbeat_ms`)

```json
{
  "hup_version": "1.0.0",
  "type": "node_heartbeat",
  "ts": 1734369930.000,
  "payload": {
    "ts": 1734369930.000,
    "battery_pct": 87,
    "rssi": -54
  }
}
```

Fields:

- `ts` (float, required) — daemon-local timestamp.
- `battery_pct` (int 0–100, optional).
- `rssi` (int, dB, optional) — radio signal strength if applicable.

### 5.4 `device_event` (daemon → brain)

```json
{
  "hup_version": "1.0.0",
  "type": "device_event",
  "ts": 1734369931.210,
  "payload": {
    "node_id": "acme-wb-001",
    "event_type": "heart_rate",
    "data": {"bpm": 72, "confidence": 0.94},
    "ts": 1734369931.210
  }
}
```

JSON Schema:

```json
{
  "$id": "https://feral.ai/schemas/hup/v1/device_event.json",
  "type": "object",
  "required": ["node_id", "event_type", "data", "ts"],
  "properties": {
    "node_id":    {"type": "string"},
    "event_type": {"type": "string",
                   "description": "Capability or sensor identifier.",
                   "examples": ["heart_rate","spo2","temperature","accelerometer","button_press","camera_frame","microphone_chunk"]},
    "data":       {"type": "object"},
    "ts":         {"type": "number"}
  }
}
```

Conventions for common events:

| `event_type`       | `data` shape                                                           |
|--------------------|------------------------------------------------------------------------|
| `heart_rate`       | `{"bpm": int, "confidence": float?}`                                   |
| `spo2`             | `{"current": int, "high": int?, "low": int?}`                          |
| `temperature`      | `{"celsius": float}`                                                   |
| `accelerometer`    | `{"x": float, "y": float, "z": float}`                                 |
| `button_press`     | `{"button": str, "pressed": bool, "count": int?}`                      |
| `camera_frame`     | `{"encoding": "jpeg", "resolution": [w,h], "data_b64": str (≤512KB)}`  |
| `microphone_chunk` | `{"encoding": "pcm16", "sample_rate": int, "data_b64": str}`           |
| `audio_frame`      | v1.1 media frame — see §5.4.1                                           |
| `video_frame`      | v1.1 media frame — see §5.4.2                                           |

`camera_frame` and `microphone_chunk` remain valid for v1.0.0 daemons.
New daemons SHOULD emit `audio_frame` / `video_frame` instead — those
names are first-class in v1.1 with explicit codec + sequence fields
for jitter buffering.

### 5.4.1 `audio_frame` (v1.1+)

Push audio samples from a daemon (glasses, wristband, phone-bridge,
room mic) to the brain. Rides inside the existing `device_event`
envelope; only `payload.event_type` and `payload` shape are new.

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
drop frames older than that. Route to `state.audio.ingest_frame(node_id, payload)`.

### 5.4.2 `video_frame` (v1.1+)

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
| `data_b64` | string | yes | Base64 of the codec payload. Decoded size MUST be ≤ 512 KiB per §2. |

Brain behaviour: drop non-keyframes that arrive before the first
keyframe of an H.264 stream. Route every decoded frame into
`state.vision_buffer.push(node_id, payload)`. Every 10 s, run a
vision-LLM caption on the most recent frame and store it in episodic
memory.

### 5.5 `hup_action_request` (brain → daemon)

```json
{
  "hup_version": "1.0.0",
  "type": "hup_action_request",
  "ts": 1734369940.000,
  "payload": {
    "action_id": "f8c3e1a2-...",
    "name": "buzz",
    "params": {"duration_ms": 250, "pattern": "double"},
    "timeout_ms": 5000,
    "requires_confirmation": false
  }
}
```

JSON Schema:

```json
{
  "$id": "https://feral.ai/schemas/hup/v1/hup_action_request.json",
  "type": "object",
  "required": ["action_id", "name", "params"],
  "properties": {
    "action_id":             {"type": "string", "minLength": 1, "maxLength": 64},
    "name":                  {"type": "string", "minLength": 1, "maxLength": 64},
    "params":                {"type": "object"},
    "timeout_ms":            {"type": "integer", "minimum": 1, "maximum": 120000, "default": 5000},
    "requires_confirmation": {"type": "boolean", "default": false}
  }
}
```

This is the direct wire form of `HUPAction` in
`ASOS/feral-core/hardware/protocol.py`; `action_id`, `name`, `params`,
and `timeout_ms` correspond to `HUPAction.action_id`,
`HUPAction.capability_id`, `HUPAction.parameters`, and
`HUPAction.timeout_ms` respectively.

### 5.6 `hup_action_response` (daemon → brain)

```json
{
  "hup_version": "1.0.0",
  "type": "hup_action_response",
  "ts": 1734369940.180,
  "payload": {
    "action_id": "f8c3e1a2-...",
    "success": true,
    "result": {"vibrated_ms": 250},
    "error": null,
    "duration_ms": 178
  }
}
```

JSON Schema:

```json
{
  "$id": "https://feral.ai/schemas/hup/v1/hup_action_response.json",
  "type": "object",
  "required": ["action_id", "success"],
  "properties": {
    "action_id":   {"type": "string"},
    "success":     {"type": "boolean"},
    "result":      {"type": "object"},
    "error":       {"type": ["string", "null"]},
    "duration_ms": {"type": "integer", "minimum": 0}
  }
}
```

This is the wire form of `HUPResult` (`hardware/protocol.py`). The
mapping is: `success = (HUPResult.status == "success")`,
`error = HUPResult.error or null`, `result = HUPResult.data`.

### 5.7 `node_bye` (either side)

```json
{
  "hup_version": "1.0.0",
  "type": "node_bye",
  "ts": 1734369999.000,
  "payload": {"reason": "shutdown", "restart_in_s": 0}
}
```

After sending `node_bye`, the sender SHOULD close the socket within 2 s.

---

## 6. Capability Allowlist and Security

Per-device capability gating happens in the FERAL UI at
**Settings → Devices → <device> → Capabilities**. Each capability tier
(§5.1) has a per-device toggle. Brains:

- MUST NOT issue `hup_action_request` for a capability that is not in
  `granted_capabilities` from the `node_ack`.
- MUST issue an inline user confirmation (SDUI prompt) before sending any
  action whose declared tier is `motor`, or whose
  `requires_confirmation: true`.
- SHOULD rate-limit `active_actuator` actions to 10/min/device by default.
- MUST drop `camera_frame` and `microphone_chunk` events from nodes whose
  `camera`/`audio` tier is disabled, even if the daemon sends them.

Nodes:

- MUST refuse any `hup_action_request` whose `name` is not in their
  registered capabilities, replying with `success=false, error="capability_denied"`.
- MUST NOT send `device_event`s for capabilities they did not register.

---

## 7. Example Session — Wristband Registering, Streaming HR, Buzzing

```
# 1. TLS + WS upgrade
GET /v1/node HTTP/1.1
Host: feral.local:9090
Upgrade: websocket
Connection: Upgrade
Authorization: Bearer fkn_live_b58c2c34dd8e4c03b9e...
Sec-WebSocket-Key: ...
Sec-WebSocket-Version: 13

HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade

# 2. daemon → brain
{"hup_version":"1.0.0","type":"node_register","ts":1734369920.001,
 "payload":{"node_id":"acme-wb-001","node_type":"wearable",
            "name":"Acme Wristband","manufacturer":"Acme",
            "firmware_version":"1.2.3","platform":"zephyr",
            "capabilities":["heart_rate","buzzer","battery"],
            "sensors":["heart_rate","battery"],"actuators":["buzzer"]}}

# 3. brain → daemon
{"hup_version":"1.0.0","type":"node_ack","ts":1734369920.040,
 "payload":{"node_id":"acme-wb-001","session_token":"b58c2c34-...",
            "heartbeat_ms":10000,"server_time":1734369920.040,
            "granted_capabilities":["heart_rate","buzzer","battery"],
            "denied_capabilities":[]}}

# 4. daemon → brain (streaming)
{"hup_version":"1.0.0","type":"device_event","ts":1734369931.210,
 "payload":{"node_id":"acme-wb-001","event_type":"heart_rate",
            "data":{"bpm":72,"confidence":0.94},"ts":1734369931.210}}

# 5. daemon → brain (heartbeat)
{"hup_version":"1.0.0","type":"node_heartbeat","ts":1734369930.000,
 "payload":{"ts":1734369930.000,"battery_pct":87,"rssi":-54}}

# 6. brain → daemon (user: "buzz my wrist")
{"hup_version":"1.0.0","type":"hup_action_request","ts":1734369940.000,
 "payload":{"action_id":"f8c3e1a2","name":"buzz",
            "params":{"duration_ms":250,"pattern":"double"},"timeout_ms":5000}}

# 7. daemon → brain
{"hup_version":"1.0.0","type":"hup_action_response","ts":1734369940.180,
 "payload":{"action_id":"f8c3e1a2","success":true,
            "result":{"vibrated_ms":250},"error":null,"duration_ms":178}}

# 8. graceful shutdown (daemon → brain)
{"hup_version":"1.0.0","type":"node_bye","ts":1734369999.000,
 "payload":{"reason":"shutdown","restart_in_s":0}}
```

---

## 8. Errors

Whenever a brain rejects a frame or closes a socket for protocol reasons,
it uses the standard error envelope:

```json
{
  "hup_version": "1.0.0",
  "type": "error",
  "ts": 1734369921.000,
  "payload": {
    "code": 1002,
    "name": "bad_schema",
    "message": "node_register.capabilities must be an array of strings",
    "recoverable": false,
    "ref_action_id": null
  }
}
```

Reserved codes:

| Code | Name                  | Meaning                                                          |
|------|-----------------------|------------------------------------------------------------------|
| 1001 | `unauthorized`        | Missing/invalid API key, expired pairing token.                  |
| 1002 | `bad_schema`          | Frame failed JSON-Schema validation or unsupported `hup_version`.|
| 1003 | `capability_denied`   | Action or event references a capability the user disabled.       |
| 1004 | `rate_limited`        | Too many frames — back off per tier.                             |
| 1005 | `node_id_conflict`    | Another session holds this `node_id`; retry after 2 s.           |
| 1006 | `payload_too_large`   | Frame > 1 MiB or decoded base64 > 512 KiB.                       |
| 1007 | `timeout`             | Action deadline exceeded.                                        |
| 1099 | `internal`            | Brain-side bug. Daemon should retry with backoff.                |
| 4020 | `frame_too_large`     | v1.1+: `audio_frame.data_b64` > 64 KiB decoded, or `video_frame.data_b64` > 512 KiB decoded. Brain closes the socket; daemon MUST reconnect with a saner encoder bitrate. |

Codes `>= 2000` are reserved for vendor-private extensions.

WS close codes mirror a subset: `4001` unauthorized, `4002` bad_schema,
`4003` capability_denied, `4004` stale_heartbeat.

---

## 9. Reference Implementations

- **Python** — [`feral-nodes/python-node-sdk/`](./python-node-sdk/)
  (`pip install feral-node-sdk`).
- **TypeScript / Node.js** — [`feral-nodes/ts-node-sdk/`](./ts-node-sdk/)
  (`npm install @feral-ai/node-sdk`).
- **Vendor starter template** — [`feral-nodes/templates/hardware-daemon/`](./templates/hardware-daemon/)
  (cookiecutter-compatible; `cp -r` also works).

Both SDKs embed the schemas in §5 as runtime validators (Pydantic /
Zod) so daemons written with them are conformant by construction.

---

## 10. Compliance Statement

- HUP is published under **Apache-2.0**. Any vendor is free to implement
  it, fork it, or build atop it commercially.
- There is **no certification program**. Vendors self-declare conformance
  by shipping a daemon that passes the reference SDK test suites against
  a stock FERAL brain. A passing daemon MAY advertise "HUP v1 compatible"
  in marketing.
- Patent grant follows Apache-2.0 §3 — implementing HUP does not grant
  rights to any vendor's hardware patents, only to the protocol itself.
- There is no trademark on the string "HUP". The mark "FERAL" belongs to
  its owner; vendor daemons MUST NOT use it except to state compatibility.

---

## Appendix A — Mapping to `feral-core` Types

| HUP wire field                        | feral-core type                                    |
|---------------------------------------|----------------------------------------------------|
| `node_register.payload`               | `models.protocol.NodeRegisterPayload` (extended)   |
| `device_event.payload.event_type`     | `DeviceCapability.id` or sensor string             |
| `hup_action_request.payload`          | `hardware.protocol.HUPAction`                      |
| `hup_action_response.payload`         | `hardware.protocol.HUPResult`                      |
| Capability enum                       | Union of `NodeRegisterPayload.capabilities` strings and `DeviceCapability.category`/sensors/actuators seen in `FERAL_GLASSES_MANIFEST` |

Deltas from the current `/v1/node` handler are tracked in
`feral-nodes/README.md`.

---

## Appendix B — Version Changelog

### v1.1.0 (2026-04-21)

- **Added** `audio_frame` event type (§5.4.1) — Opus/PCM16 frames with
  `sample_rate`, `channels`, `frame_ms`, `sequence`, `data_b64`. Cap:
  64 KiB decoded per frame.
- **Added** `video_frame` event type (§5.4.2) — JPEG/H.264 frames with
  `width`, `height`, `sequence`, `keyframe`, `data_b64`. Cap: 512 KiB
  decoded per frame.
- **Added** error code `4020 frame_too_large` for over-cap media frames.
- **Backward-compat:** strictly additive. v1.0.0 daemons remain
  conformant. v1.0.0 brains MUST ignore unknown event types per §1's
  forward-compat rule. Legacy `camera_frame` / `microphone_chunk` stay
  valid; new daemons SHOULD migrate to `video_frame` / `audio_frame`.

### v1.0.0

- Initial public release of the Hardware Unification Protocol.
