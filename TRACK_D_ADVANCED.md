# Track D — Remote Teleop / Camera Triggers / 3D Reconstruction

> Runs **after** Tracks A + B + C are closed. Each pillar depends on
> Track B's HUP v1.1 audio + video frame types, Track A's Voice Call
> channel, and Track C's Home-Ops / Security-Analyst personas. Starting
> Track D before those are GA means duplicating work.

These are Pillars D, E, F from [`ASOS/ROADMAP_NEXT.md`](ROADMAP_NEXT.md).
That file already scopes each pillar with day estimates, phase plans,
and success criteria. Track D does not re-scope them — it **binds** them
to the prerequisites they actually need.

## Prerequisite gate (updated 2026-04-21)

Current state of the four dependency gates:

- [x] Track A: Matrix + Signal + Voice Call channel **stubs** shipped as of commit `f34d2da` (2026.4.18-dev). Each is honest-stub only — it refuses to fake a connection. Live Voice-Call (Twilio) implementation for Pillar D's "voice-command glue" still needs Twilio credentials wired. Pillar D can prototype against the stub to validate the end-to-end dispatch path while the live round-trip is pending.
- [x] Track B: HUP v1.1 `video_frame` + `audio_frame` **merged into the normative spec** (`HUP_SPEC.md` §5.4.1 / §5.4.2) as of commit `14f5f2f` (2026.4.18-dev). Python + TypeScript SDKs updated; Brain `/v1/node` WebSocket handler dispatches both. `w300_daemon` streams real frames (commit `c13460b`) when paired with a UVC-accessible W300.
- [ ] Track B: HomeKit + Matter bridges shipped (Pillar E's actuator catalog depends on them). **Still queued** — this is the next Track B PR after `w300_daemon` / `wristband_daemon`.
- [x] Track C: `home_ops` + `security_analyst` personas shipped at runtime as of commit `8b6f213` (2026.4.18-dev). `GET /api/agents/personas/home_ops` and `GET /api/agents/personas/security_analyst` both resolve live; v2 Agents page lists them on the Personas tab. See [`TRACK_C_PERSONAS_WORKFLOWS.md`](TRACK_C_PERSONAS_WORKFLOWS.md).

Gate summary: **3 of 4 dependencies met**. Pillar D and Pillar F can start now using the stubbed Voice-Call + the shipped video_frame. Pillar E is the one that still needs HomeKit + Matter bridges first.

## The three pillars (pass-through)

Each item below points to the canonical plan in `ROADMAP_NEXT.md`. The
only change Track D introduces is the re-ordered dependency chain.

### Pillar D — Remote teleop (phone / robot / Roomba) off-LAN

- **Full plan:** [`ROADMAP_NEXT.md` Pillar D](ROADMAP_NEXT.md).
- **New prerequisite added by Track D:** Voice Call channel from Track A,
  so the Pillar D Phase 4 "voice-command glue" has a working voice path.
- **Net work:** ~9 days (unchanged from ROADMAP_NEXT).

### Pillar E — Camera-aware brain triggering actions

- **Full plan:** [`ROADMAP_NEXT.md` Pillar E](ROADMAP_NEXT.md).
- **New prerequisite added by Track D:** HUP v1.1 `video_frame` from
  Track B, and the `home_ops` + `security_analyst` personas from Track C.
- **Net work:** ~7 days (unchanged from ROADMAP_NEXT).

### Pillar F — 3D reconstruction from streaming camera data

- **Full plan:** [`ROADMAP_NEXT.md` Pillar F](ROADMAP_NEXT.md).
- **New prerequisite added by Track D:** HUP v1.1 `video_frame` from
  Track B. The LingBot-Map stream ingests `video_frame` events directly.
- **Net work:** ~7 days + open-ended for robot navigation.

## Why Track D is a plan, not an implementation

Every pillar in this track needs HUP v1.1, a live smart-glasses stream,
a remote relay service (Fly-deployed, per Pillar D Phase 1), or a
vision-LLM + Three.js integration. None of that is safe to ship
speculatively — it requires the prerequisite artifacts to be real and
tested against the maintainer's hardware.

The correct Track D ship is this tracking doc + the cross-track
dependency gate. When a contributor starts Pillar D / E / F, they come
here first to confirm prerequisites and then follow the per-pillar plan
in `ROADMAP_NEXT.md`.

## Success rollup

When Track D closes, the FERAL ambient-OS story is complete:

- Talk to FERAL from a coffee shop → FERAL dispatches a Roomba at home.
- Walk around with smart glasses → ask "what am I looking at?" → answer in < 3 s.
- Home camera notices a mess → FERAL offers to send the Roomba → you reply "yes".
- Later that evening: "where did I leave my keys?" → FERAL searches the
  rolling 3D map of your space + its vision captions → tells you.

That's the "local-first AI operating system for your personal life"
pitch from [`STATE_OF_FERAL.md § Executive summary`](STATE_OF_FERAL.md),
end-to-end.
