# FERAL — honest critique + 90-day roadmap

Written the day the supervisor + browser-node + twin-on-behalf stack
landed. Not marketing. The questions it answers:

1. What did FERAL *actually* become?
2. Where is it still thin?
3. Could a "souped-up OpenClaw" replicate this? (Short answer: no.)
4. What's the 90-day plan to widen the moat?

## 1. What FERAL is, precisely

A **local-first ambient operating system for a personal agent**, organised
as a small number of durable contracts:

- **5-tier memory** — working, episodic, semantic KG, execution log, and
  consciousness ([`memory/store.py`](feral-core/memory/store.py),
  [`memory/consciousness.py`](feral-core/memory/consciousness.py)). Every
  LLM turn now routes the user's utterance through all five
  ([`memory/context_builder.py`](feral-core/memory/context_builder.py),
  wired by [`agents/identity_loader.py`](feral-core/agents/identity_loader.py)).
- **HUP v1 node mesh** — every device that attaches to
  `/v1/node?api_key=TOKEN` with a `NodeRegisterPayload` is a live first-
  class node. Python, TypeScript, iOS, Android SDKs exist. Commit 5
  added a **browser-side Node** ([`feral-client-v2/src/node/BrowserNode.js`](feral-client-v2/src/node/BrowserNode.js))
  so a phone pairs with zero app install.
- **Third-party GenUI app platform** —
  [`models/app_manifest.py`](feral-core/models/app_manifest.py) defines
  the publisher contract; [`agents/app_registry.py`](feral-core/agents/app_registry.py)
  + [`agents/hybrid_genui.py`](feral-core/agents/hybrid_genui.py) render
  authored / generated / hybrid surfaces with per-user caches. `feral
  app init / validate / install / publish` and the v2 `/apps/publish`
  flow ship end-to-end.
- **Digital Twin with real agency** — Commit 7 turned the twin from
  "read-only advisor" into a policy-gated actor with per-domain modes
  (draft_only / auto_send / disabled), time windows, daily caps, and an
  approval queue. `DigitalTwin.execute(...)` is the one entry point.
- **Supervisor oversight seat** — Commit 6 wraps every orchestrator
  entry point (web, /v1/node, voice, cron, channels, proactive, ui
  events, twin) through
  [`agents/supervisor.py`](feral-core/agents/supervisor.py). One SQLite
  audit table, a live `/oversight` page, a single kill switch that
  halts every action.
- **Proactive engine** — [`agents/proactive_engine.py`](feral-core/agents/proactive_engine.py)
  emits alerts + small automations from baseline + calendar + memory +
  health signals.
- **Channels** — real Telegram / Slack / Discord / WhatsApp bridges;
  every inbound message lands as a supervisor-audited session.
- **GenUI Canvas** (`/canvas`) — developer inspector for every live
  SDUI frame + per-app regenerate button.

## 2. Where it's still thin (no spin)

| Area | Gap | Why it matters | Planned fix |
|------|-----|-----------------|--------------|
| Supervisor | Today the audit is observe-then-allow. The policy gate is wired but has no built-in rules beyond Twin's per-domain policy. | Users can't say "never call shell_command between 0-6am". | Commit 10: cross-cutting policy rules (time-of-day, keyword deny, destructive-action confirmation). |
| Twin | Exactly one "action" shape: `DigitalTwin.execute(domain, action, context, executor)`. Real integrations (iMessage / Mail / Slack send) still need wiring as executor callables. | Users can set policy for `respond_imessage` today but the Brain doesn't know how to send one yet. | Commit 11: four first-party executor bindings (iMessage via AppleScript, Mail via MCP, Slack via channel, Telegram via channel). |
| Browser-Node | Location streams; camera / mic are permissioned but not pushed as HUP frames yet. | The Brain doesn't see what the phone sees unless the user opens `/chat` + PerceptionShare. | Commit 12: `camera_frame` + `audio_chunk` frames emitted from BrowserNode into the HUP perception pipeline. |
| Multi-memory | KG + episode search fire per turn (Commit 2), but vector-backed episode_search_hybrid only ever looks back ~30 days by default. | Long-term anchors (birthdays, major life events) can drop out of active context. | Commit 13: anchor-promote — any episode confirmed ≥3 times or tagged `important` never decays. |
| Coverage | Backend 51.5%, v2 28%. | Big, gnarly integrations (voice, gemini-realtime, sandbox) bring the floor down. | Commit 14-17: one per under-tested module listed in [`docs/coverage.md`](docs/coverage.md). |
| Endpoint parity | 66 backend routes still have no frontend witness (scripts/audit_routes.py). Many are legit (CLI / WS / webhook). | The remainder is likely dead. | Commit 18: walk the audit, delete or wire each. |
| Offline / local LLM | Ollama + LM Studio providers ship, but the default flow prefers a cloud key. | The "your brain runs on your Mac" story isn't quite the default. | Commit 19: first-run picker defaults to Ollama if it's reachable + pulled. |
| Hardware executor contracts | `HUPAction` supports buzz / light / display / custom, but there's no schema per node_type. | Publishers can't rely on specific actuators. | Commit 20: `capabilities.yaml` per node class. |

## 3. OpenClaw comparison

Someone claimed a configured OpenClaw could do what FERAL does. It
can't. OpenClaw is a computer-use LLM loop: take screenshot, reason,
click, type, repeat. That's one surface. FERAL is seven:

| Surface | OpenClaw | FERAL |
|---------|----------|-------|
| Sees the user's screen, clicks, types | Yes (its whole thing) | Yes (via `skills/impl/*_automation.py`) |
| Persists memory across sessions       | No                    | 5-tier, per-user, vector-indexed |
| Runs device nodes (wearables, glasses, phone bridges) over HUP | No | Yes — iOS, Android, Python, TS SDKs + browser |
| Hosts third-party apps with a GenUI contract | No | Yes — AppManifest + install + publish |
| Has a proactive engine firing baseline alerts | No | Yes |
| Acts "on your behalf" with policy + approval queue + kill switch | No | Yes (Commit 7) |
| Has a single oversight seat auditing every action | No | Yes (Commit 6) |
| Pairs to any phone with zero app install | No | Yes (Commit 5) |

The OpenClaw claim collapses on "persists memory across sessions" alone.
Add HUP + GenUI + twin + supervisor and it stops being a comparable
product.

## 4. The 90-day roadmap

One-line summaries. Each links to a roadmap page.

1. **Policy hardening** — [`docs/roadmap/oversight.md`](docs/roadmap/oversight.md)
2. **Twin executor bindings** — [`docs/roadmap/twin.md`](docs/roadmap/twin.md)
3. **Browser-Node sensor frames** — [`docs/roadmap/pairing.md`](docs/roadmap/pairing.md)
4. **Memory anchors + long-term retention**
5. **Coverage ratchet to 65%**
6. **Endpoint parity cleanup**
7. **Local-first LLM default**
8. **Hardware capability schemas**
9. **Voice stack: faster-whisper + piper default**
10. **Wristband signal fusion pipeline**

This file is the contract. Every commit that closes one of the gaps
above updates the table in §2 and ticks its number in §4.
