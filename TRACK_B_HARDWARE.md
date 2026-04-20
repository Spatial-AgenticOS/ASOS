# Track B — HUP v1.1 + First-Party Daemons + Desktop v1 (Weeks 8-11)

> Makes the "AI OS" claim real on hardware. Currently
> [`STATE_OF_FERAL.md § 4`](STATE_OF_FERAL.md) admits zero first-party
> HUP daemons are shipped and the desktop app is `workflow_dispatch`-only
> pending signing certificates.

## Why not merge all of Track B into one commit

- HUP v1.1 (audio + video frame types) is additive and can ship as a
  text-only spec update — no live-device verification needed to publish
  the spec itself.
- First-party daemons (W300 smart-glasses, wristband, HomeKit bridge,
  Matter bridge) *must* be verified on real hardware the maintainer owns
  (W300 devkit + wristband devkit per
  [`ROADMAP_NEXT.md` Pillar A](ROADMAP_NEXT.md)). Shipping a daemon that
  has never talked to its device would be faking.
- Desktop v1 requires Apple Developer ID + Windows Authenticode + Tauri
  updater keypair rotation. These are secrets; they cannot be provisioned
  from a PR.

Same pattern as Track A: ship the spec now, ship one daemon at a time
with live verification, unblock desktop when certs are available.

## Shared templates

- **Daemon skeleton:** copy
  [`feral-nodes/templates/hardware-daemon/`](feral-nodes/templates/hardware-daemon/)
  — this is a cookiecutter template that already scaffolds
  `node_register`, heartbeats, device-event senders, capability list.
- **SDK:** Python via `feral-node-sdk`, TypeScript via
  `@feral-ai/node-sdk`.
- **Registration:** publish each daemon as a `kind=daemon` item via
  `feral publish --kind daemon ./daemon-dir/`.

## Work breakdown

### Week 8 — HUP v1.1 (additive spec bump)

Shipped **as documentation + schema-mirror sync in this commit**. See
[`feral-nodes/HUP_V1_1_PROPOSAL.md`](feral-nodes/HUP_V1_1_PROPOSAL.md)
for the exact additive message types:

| New event type | Purpose | Payload |
|---|---|---|
| `audio_frame` | Opus / PCM audio push from a glasses or wristband mic | `codec`, `sample_rate`, `sequence`, `data_b64` |
| `video_frame` | JPEG keyframe or H.264 keyframe/delta from a camera node | `codec`, `width`, `height`, `sequence`, `keyframe`, `data_b64` |

Systematic-sync per AGENT_PROMPT.md: when HUP v1.1 lands in
`feral-nodes/HUP_SPEC.md`, update
- `feral-nodes/python-node-sdk/src/feral_node_sdk/schemas.py`
- `feral-nodes/ts-node-sdk/src/schemas.ts`
- `feral-core/api/server.py::/v1/node` handler
- `feral-nodes/templates/hardware-daemon/` cookiecutter
in the **same commit**. Anything less introduces drift that AGENT_PROMPT
bans.

### Week 9 — W300 + wristband daemons

| Daemon | Dir | Hardware | Verification |
|---|---|---|---|
| W300 smart-glasses | `feral-nodes/w300-daemon/` | Maintainer owns W300 devkit per ROADMAP Pillar A | Voice command "FERAL, look at this" answers in < 3s |
| Wristband | `feral-nodes/wristband-daemon/` | Maintainer owns devkit; `feral-core/hardware/adapters/wristband.py` already wired | Live HR + SpO2 frames flow to dashboard; buzz actuator fires on `hup_action_request` |

### Week 10 — HomeKit + Matter bridges

| Bridge | Dir | Underlying | Notes |
|---|---|---|---|
| HomeKit | `feral-nodes/homekit-bridge/` | `HAP-python` | Requires iCloud device to pair |
| Matter | `feral-nodes/matter-bridge/` | `python-matter-server` | Requires a Thread border router + commissioner |

Each ships as a `kind=daemon` registry item.

### Week 11 — Desktop app v1

`[`desktop/`](desktop/)` is scaffolded in Tauri 2. Blocker list:

- [ ] Apple Developer ID cert acquired + imported into repo secrets as `APPLE_CERT_P12` + `APPLE_CERT_PW`.
- [ ] Apple Developer Notarization credentials (`APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`).
- [ ] Windows Authenticode cert as `WINDOWS_CERT_P12` + `WINDOWS_CERT_PW`.
- [ ] Tauri updater keypair generated (`tauri signer generate`) — public key committed, private key in repo secrets as `TAURI_SIGNING_PRIVATE_KEY` + `TAURI_KEY_PASSWORD`.
- [ ] Re-enable `.github/workflows/desktop.yml` from `workflow_dispatch` only → push/tag triggers.

Ship:
1. Signed DMG for Intel + Apple Silicon.
2. Signed MSI for Windows x64.
3. `.deb` + `.rpm` + `.AppImage` for Linux.
4. Auto-updater manifest at `https://updates.feral.sh/stable/` served
   from Render or Fly.

## Success criteria

When Track B is closed:
- [`STATE_OF_FERAL.md § 2.4`](STATE_OF_FERAL.md) lists four first-party
  HUP daemons with their `kind=daemon` registry IDs.
- A maintainer plugs in the W300, says "FERAL, look at this," and gets
  an answer in < 3 seconds — Pillar A success criterion, verified.
- `feral install desktop-v1` downloads a signed DMG that launches on
  a fresh macOS 26.x box with no Gatekeeper warning.

## Immediate shippable artifact in this commit

[`feral-nodes/HUP_V1_1_PROPOSAL.md`](feral-nodes/HUP_V1_1_PROPOSAL.md)
fully specifies `audio_frame` + `video_frame`. It's a text-only
additive spec bump — safe to publish without live device verification.
The implementation PRs that wire them into the SDKs, brain, and
reference daemons are Week 8's work per the breakdown above.
