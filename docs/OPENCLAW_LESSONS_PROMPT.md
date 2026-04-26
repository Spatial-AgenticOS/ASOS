# Self-prompt — Comparative study of `openclaw-main 2` for FERAL adoption

**Use.** Paste this prompt verbatim into a fresh agent session (or run it as a Cursor `explore` subagent in read-only mode). It produces a deliverable at `/Users/mahmoudomar/Desktop/thoera-mac/ASOS/docs/OPENCLAW_LESSONS.md` that maps openclaw's mature subsystems to concrete FERAL workstreams (W16+).

**Why.** FERAL's operator complaints (stale model dropdowns, theatre UI, fragile channels, a partial twin, a partial supervisor, an in-development WASM sandbox, etc.) are problems openclaw has already solved at scale. Before we keep iterating in isolation, do a brutally honest comparative study so we either copy what works or document explicitly why it doesn't fit our threat/UX model.

---

## Prompt (paste this whole block)

```
You are a world-class software analyst doing a comparative architecture study. You operate
in READ-ONLY mode. Do not edit any source file in either tree. The only file you write is
the deliverable at /Users/mahmoudomar/Desktop/thoera-mac/ASOS/docs/OPENCLAW_LESSONS.md.

REPOS
  Source A (mature reference):  /Users/mahmoudomar/Desktop/thoera-mac/openclaw-main 2/
  Source B (target — FERAL):    /Users/mahmoudomar/Desktop/thoera-mac/ASOS/

Today is 2026-04-25.

GOAL
Produce a deep, citation-backed comparative report covering the eight subsystem clusters
listed below. For each cluster, I need:

  1. What openclaw does, with `path:line` citations (don't paraphrase; quote types, function
     signatures, key state shapes).
  2. What FERAL does today, with `path:line` citations (use the existing
     FEATURE_STABILITY_ROADMAP.md as a starting index but verify everything against the live
     code).
  3. The honest delta — where openclaw is materially better, where FERAL is, and where the
     two have made different but defensible choices for different threat models / users.
  4. A concrete FERAL adoption proposal — specifically, a new workstream WID (W16, W17, …)
     with: mission one-liner, owned paths, dependencies on existing W1–W15, acceptance
     tests to write, and an effort estimate (S/M/L/XL).
  5. A short "do NOT copy" callout for any openclaw choice that would be wrong for FERAL
     (single-user-local, Python+TS+Swift, SQLite-first, optional-dependency-heavy).

OUTPUT FILE FORMAT
Write the deliverable as a single Markdown file at the path above with this skeleton:

  # openclaw → FERAL: lessons audit (2026-04-25)
  ## 0. Method + verification evidence
  ## 1. Provider auth + credential storage
  ## 2. Subagent / supervisor / session lifecycle
  ## 3. Async + parallel execution + rate-limit + cost
  ## 4. Model catalog + provider freshness + routing
  ## 5. Plugin / extension / channel model
  ## 6. Sandboxing + security
  ## 7. Realtime voice + audio surfaces
  ## 8. MCP + gateway protocol + tool registration
  ## 9. Synthesis: top 8 patterns to adopt (P0/P1) + anti-patterns to avoid
  ## 10. Proposed new workstreams (W16…) with mission + scope + dependencies

Each numbered section MUST contain the four sub-items in order: openclaw evidence, FERAL
evidence, delta, FERAL proposal. No section is allowed to omit citations. Citations look
like `openclaw-main 2/src/secrets/runtime.ts:412` or `ASOS/feral-core/security/vault.py:88`.

CLUSTER GUIDANCE — READ BEFORE DIVING

§1 Provider auth + credential storage
  openclaw sources of truth: src/secrets/runtime.ts and friends, src/secrets/target-registry.ts,
  src/secrets/runtime-config-collectors-*.ts, src/secrets/storage-scan.ts. Look at
  runtime-gateway-auth-surfaces.ts for how channel-specific surfaces share secrets without
  cross-leaking. Find their answer to "where does the master key live, what protects it,
  what happens on rotation, what happens on a failed read."
  FERAL: feral-core/security/vault.py (plaintext+chmod 600; W9 will fix).

§2 Subagent / supervisor / session lifecycle
  openclaw sources: src/agents/harness/, src/agents/runtime-plan/, src/agents/openclaw-tools.subagents.*.ts,
  src/process/supervisor/, src/sessions/session-lifecycle-events.ts, src/sessions/send-policy.ts,
  src/sessions/model-overrides.ts.
  Especially examine the subagents.sessions-spawn family (allowlist, cron-note, lifecycle,
  applies-thinking-default, steer-failure-clears-suppression). This is the production-tested
  version of the "main agent fires worker agents" pattern the user wants in FERAL.
  FERAL: feral-core/agents/orchestrator.py (per-session asyncio.Lock, parallel tool calls
  via Semaphore), agents/supervisor.py (audit + kill switch).

§3 Async + parallel execution + rate-limit + cost
  openclaw: search the runtime layer (src/runtime.ts, src/agents/harness/) and routing
  (src/routing/) for backoff, queue depth, per-provider concurrency caps, cost accounting.
  FERAL: agents/llm_provider.py:34 (_retry_llm_call linear backoff 1/2/4s), :130
  (ProviderCooldownTracker with 60/300/86400 cooldown map), :167 (_PROVIDER_REGISTRY).
  Specifically look for openclaw's answer to "5 agents in parallel hammer one provider; one
  starts 429-ing — how does the system rebalance?"

§4 Model catalog + provider freshness + routing
  openclaw: src/model-catalog/ — look at how they refresh, where the canonical list lives,
  whether they ship cron-style refresh or in-process, how they handle providers without a
  /v1/models endpoint (Anthropic), and how they expose freshness to the UI.
  FERAL: providers/catalog.py, providers/model_catalog.json, agents/llm_provider.py
  _PROVIDER_REGISTRY (now WIP under W1; PR #23). Quote both before and after the W1 changes
  if both versions are in tree (FERAL local has W1 unmerged; main does not yet).

§5 Plugin / extension / channel model
  openclaw: extensions/*/openclaw.plugin.json (~140+ extensions: telegram, slack, whatsapp,
  discord, matrix, signal, zalo, voice-call, x, …) + src/plugins/runtime/ + src/plugin-sdk/
  + src/channels/. Examine the manifest schema, the trust boundary (signed? unsigned?
  permission scopes?), and how new extensions hot-load.
  FERAL: feral-core/channels/* (handwritten per-channel adapters), feral-core/integrations/*,
  feral-core/genui/ (A2UI manifest spec, currently unsigned — W8 will fix).
  This is the cluster where openclaw is most ahead. Be explicit about whether FERAL should
  adopt openclaw's plugin-manifest model or stay with hand-rolled channels.

§6 Sandboxing + security
  openclaw: Dockerfile.sandbox, Dockerfile.sandbox-browser, src/security/, podman scripts,
  scripts/systemd/openclaw-auth-monitor.{service,timer}, INCIDENT_RESPONSE.md, SECURITY.md.
  FERAL: feral-core/security/{docker_sandbox.py, wasm_sandbox.py, wasm_host.py, tool_genesis.py,
  fetch_guard.py, content_defense.py}.
  Specifically: how does openclaw treat agent-generated code, browser surfaces, and exec
  approvals? What's their answer to "the model wants to run shell"?

§7 Realtime voice + audio surfaces
  openclaw: src/realtime-voice/, src/realtime-transcription/, src/tts/.
  FERAL: feral-core/voice/{openai_realtime.py, gemini_live.py, realtime_proxy.py, wakeword.py},
  voice/voice_router.py.
  Specifically: how does openclaw deal with WS reconnect, half-open sockets, mid-utterance
  provider failover, and audio-frame backpressure?

§8 MCP + gateway protocol + tool registration
  openclaw: src/mcp/openclaw-tools-serve.ts, src/agents/openclaw-tools*.ts (huge surface),
  src/agents/openclaw-plugin-tools.ts, src/gateway/protocol/.
  FERAL: feral-core/mcp/server.py (recently fixed under W3, PR #20), api/routes/mcp.py,
  agents/orchestrator.py tool dispatch.
  Specifically: how does openclaw register tools, gate access, version the protocol, and
  expose them over HTTP/WS for third parties?

§9 Synthesis
  Rank the patterns you found by impact-on-FERAL × engineering effort. Format:
    | Rank | Pattern | Where it lives in openclaw | Why FERAL needs it | Effort | Becomes |
  Top 5 must be P0; next 5 P1.

§10 Proposed new workstreams
  Author each as a self-contained block matching the §D.W## format in
  ASOS/docs/AGENT_PROMPTS.md. Each W## block must contain: one-liner mission, owned paths,
  read-only context, mandatory tests, acceptance criteria, branch/PR convention, dependency
  on prior W##.

QUALITY BAR
- Brutal honesty. If FERAL is materially behind, say so. If openclaw made a choice that
  doesn't fit FERAL's local-first single-user model, say so explicitly with the reason.
- No marketing copy. No "modernize" or "robust" without a citation.
- Cite, cite, cite. Every claim has a `path:line`.
- Quote 5–15 lines of openclaw code at the most critical 1–2 spots per cluster, not
  everywhere. Use markdown code blocks with the literal `openclaw-main 2/...:line`.
- For FERAL, prefer references over snippets (the reader has the repo open).
- Distinguish what's already in flight (W1–W15) vs new work (W16+). Don't propose redoing
  in-flight work.

ANTI-RABBIT-HOLES
- Do not read every test in openclaw. Sample 3-5 per cluster.
- Do not fully audit src/secrets/ — quote the ~5 most relevant types and runtimes.
- If a cluster turns out to be near-parity, say so in 5 lines and move on. The point is the
  unequal clusters.
- If you cannot reach a cluster in your context budget, ship what you have and write an
  explicit "deferred to a follow-up" line at the top of the missing section. Do NOT
  hallucinate.

DELIVERABLE LOCATION
  /Users/mahmoudomar/Desktop/thoera-mac/ASOS/docs/OPENCLAW_LESSONS.md

Begin. First action: list the openclaw src/ tree to confirm the path, then jump into §1.
```

---

## How I'd dispatch it

Three options, ranked by speed:

1. **As a parallel `explore` subagent right now** (read-only, no merge risk, runs alongside whatever wave 2 we kick off). I'd back it with `claude-opus-4-7-thinking-max` per the workspace rule and let it produce `OPENCLAW_LESSONS.md` while wave 2 lands.
2. **In a fresh foreground chat** when you want to read along. Same prompt, no parallelism — slower but you see the citations as they come in.
3. **Save it for later.** The prompt is now in the repo at `docs/OPENCLAW_LESSONS_PROMPT.md`; reach for it whenever.

The output of running it (`OPENCLAW_LESSONS.md`) is what feeds into the W16+ definitions. Without that audit, wave 2's W8 (GenUI signing/sandbox) and W9 (vault encryption) are "FERAL inventing in isolation"; with it, they become "FERAL adopting battle-tested patterns from a shipping product".

Say:

- **"Run the openclaw audit now"** → I dispatch it as a read-only explore subagent in parallel with whatever you choose for wave 2.
- **"Run it after wave 2"** → I queue it.
- **"Skip it for now"** → file stays in the repo for later use.

What's your wave 2 plan? I'd suggest **W4 + W5 + W6** (the three cosmetic but visible v2 client bugs) running in parallel with the openclaw audit — they're disjoint, low-risk, and clear out the v2 UX issues that have been bugging you. Then a second sub-wave **W8 + W9 + W15** afterward, with the audit's findings shaping how W8/W9 are scoped.