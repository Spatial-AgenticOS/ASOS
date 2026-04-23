# Pairing roadmap

## Current state

- [x] Typed `/api/devices/pair` body (name / hup / browser) — Commit 5
- [x] `/pair?t=<TOKEN>` landing page — Commit 5
- [x] Browser HUP node (`BrowserNode.js`) — Commit 5
- [x] Phone-bridge one-liner (`scripts/install-phone-bridge.sh`) — Commit 5
- [x] `feral bridge install --token --brain-url` CLI — Commit 5
- [x] `/api/devices/pair/complete` claim marker — Commit 5

## Near-term (next 30 days)

- [ ] **Camera / mic frames from BrowserNode.** Today sensor streaming is
  opt-in but only `location` is actually pushed. Add:
  * `camera_frame` HUP payload (JPEG + size + timestamp) emitted on
    demand when the brain sends a `perception.request` frame.
  * `audio_chunk` HUP payload (16kHz PCM 200-400ms) for voice on
    mobile browsers — uses the same permission already requested.
  * Per-frame rate limits (≤10 frames / minute default) so a hostile
    site can't spam.
- [ ] **WebRTC fallback for audio** for browsers where MediaRecorder
  doesn't emit 16kHz — graceful downgrade to getUserMedia + AudioContext
  encoding.
- [ ] **Brave-compatible PWA manifest** (deprecated-meta fix landed, but
  the manifest.json is minimal).

## Mid-term (60 days)

- [ ] **Devices page**: one live card per paired device, grouped by
  kind, with a "Re-pair" button when `claimed_at` is null.
- [ ] **Revocation UX** from the Devices page (currently only via API).
- [ ] **Multi-brain discovery** — iOS/Android browsers can browse a
  `_feral._tcp` Bonjour service and show a picker. Brain broadcasts
  host + fingerprint via `services/mdns.py`.

## Long-term (90 days)

- [ ] **E2EE token rotation** — pairing token is the first step; after
  claim we rotate to a device-bound keypair so a stolen laptop backup
  doesn't leak brain access.
- [ ] **Cross-brain handoff** — BrowserNode that paired to one brain
  can re-pair to another in <5s without re-granting permissions.
