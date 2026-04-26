# Agent Prompts — Follow-ups

**Purpose.** Append-only log of out-of-scope discoveries surfaced by worker agents while running their assigned workstream. The Conductor reads this file every cycle and either dispatches a new W## or rolls the change into an existing one. Do **not** delete entries; mark them `[done WID:PR#]` when closed.

**Format per entry:**

```
- [<status>] <YYYY-MM-DD> · <finder agent ID / WID> · <area>
  Finding: <one-line description>
  Citation: <path:line> (or PR/commit URL)
  Proposal: <suggested resolution> — owner: <WID or "needs-triage">
```

`<status>` ∈ `open`, `triaged`, `dispatched:WID`, `done:WID:PR#`, `wontfix:reason`.

---

## Open follow-ups

- [open] 2026-04-25 · conductor · doctrine
  Finding: `FEATURE_STABILITY_ROADMAP.md` §0 (test counts) was authored 2026-04-24 against an unfetched local tree; `origin/main` had already silently fixed the 3 vitest failures via commit `b4c3aec` (release v2026.4.29). W2 wrote regression tests against the live behaviour rather than re-introducing a stale failure to fix.
  Citation: this PR's CHANGELOG entry; W2 PR #19 body.
  Proposal: When this PR merges, §0 of the roadmap will be reconciled to the post-Wave-1 state. — owner: conductor.

- [open] 2026-04-25 · conductor · labels hygiene
  Finding: PRs #19 (W2), #20 (W3), #21 (W10), #24 (W5), #25 (W4) were opened before the `workstream:W*` and `release-impact:*` labels existed on the repo, so the labels in `gh pr list` are incomplete.
  Citation: `gh pr list --json number,labels`.
  Proposal: This PR creates the missing labels and back-applies them to the listed PRs. — owner: conductor (this PR).

- [open] 2026-04-25 · W1 · `feral-core/api/server.py` orange zone
  Finding: W1's PR #23 adds an additive `_provider_catalog_refresher()` background task to `api/server.py` startup. `server.py` is an orange-zone file (W3, W13 also touch it).
  Citation: PR #23 (`feral/W1-provider-catalog-freshness`).
  Proposal: Conductor sign-off granted in this PR via the §C.2 orange-zone rules update (W1's hook is additive-only, scoped to startup, no behavioural change to existing code paths). — owner: conductor.

- [open] 2026-04-25 · W7 · `feral-core/services/mdns.py`
  Finding: W7's PR #22 refactors a literal version string in `mdns.py` to read from `feral-core/version.py`. `mdns.py` is in W7's owned set per §C.2 already, but flagging here because the refactor crosses the `feral-core/services/` boundary which has no other current owner.
  Citation: PR #22 (`feral/W7-version-singlesrc`).
  Proposal: Allowed; matches W7 charter. — owner: conductor.

- [open] 2026-04-25 · conductor · merge order
  Finding: Wave-1 PRs are all branched from the same `origin/main` SHA (`a1db911`); their owned-path sets are disjoint, so they merge in any order without rebase. Recommended merge order to minimise CI churn: **#20 (W3, fixes failing test) → #22 (W7, version coherence CI) → #19 (W2, fixes failing tests) → #23 (W1, biggest PR, last)**. Wave-2A (#24, #25) can merge immediately after.
  Citation: `git log origin/main..feral/W*` shows zero overlap on owned paths.
  Proposal: Surface in this PR body so reviewers see the recommended sequence; do not auto-merge. — owner: conductor.

- [open] 2026-04-25 · W17 · `feral-core/api/server.py` orange zone
  Finding: W17 PR #29 adds a one-line `app.include_router(sessions_router)` registration in `feral-core/api/server.py` to expose `POST /api/sessions/{id}/spawn`. `server.py` is the orange-zone file already shared with W1 (startup hook) and W13 (planned `/metrics` block).
  Citation: PR #29 (`feral/W17-subagent-spawn`).
  Proposal: Conductor sign-off granted — the registration is additive, single line, and located in the routers section (no overlap with W1's startup hook or W13's planned `/metrics` block). — owner: conductor.

- [open] 2026-04-25 · W17 · BrainState shared LLMProvider wireup
  Finding: `subagent_spawner.register_llm_provider(...)` exists but is never auto-wired to `BrainState`'s shared `LLMProvider` at boot. Spawned children today only have an LLM if a caller registers one explicitly. W17 deliberately held the one-line boot wireup off-PR to stay strictly inside owned paths.
  Citation: PR #29 conductor-questions block.
  Proposal: Add a one-line `register_llm_provider(brain_state.llm_provider)` call in the existing brain-state initialiser. — owner: needs-triage (small, can fold into next PR touching the boot path or a tiny standalone PR).

- [open] 2026-04-25 · W17 · `Supervisor.steer` channel does not exist
  Finding: W17's `steer_subsession` takes an injectable `steer_hook` and falls back to `getattr(supervisor, "steer", None)` because `feral-core/agents/supervisor.py` does not expose a `steer` method. Real supervisor-driven steering is therefore a no-op until the channel exists.
  Citation: PR #29 conductor-questions block; `feral-core/agents/supervisor.py`.
  Proposal: Author a real `Supervisor.steer(child_session_id, intervention) -> SteerDecision` API. Candidate W18 work item or a focused W18.5 ticket. — owner: needs-triage.

- [open] 2026-04-25 · conductor · doctrine docs not yet on `origin/main`
  Finding: Multiple worker agents (W17 most recently in PR #29) cite `docs/OPENCLAW_LESSONS.md` and `docs/AGENT_PROMPTS.md` in their commit/PR bodies, but those files only exist on the `feral/docs-doctrine-housekeeping` branch (PR #26). Until #26 merges, those citations resolve to 404 in the GitHub PR UI.
  Citation: PR #26 (this PR); PR #29 body anchor links.
  Proposal: Merge PR #26 first (or at minimum before any W## PR that cites these docs is reviewed externally). — owner: conductor (already top of recommended merge order).

- [open] 2026-04-25 · W12 · mintlify nav ownership for `docs/mintlify/operations/`
  Finding: W12 PR #30 created `docs/mintlify/operations/soak.mdx` as a brand-new sub-tree under the mintlify docs. There is no current §C.2 owner for this path and no entry in the mintlify `mint.json` nav.
  Citation: PR #30 (`feral/W12-soak`).
  Proposal: Confirm `docs/mintlify/operations/` is the intended home and add a nav entry, or move the file to the canonical location once chosen. Same question applies to W8's `docs/mintlify/genui/*` and W9's `docs/mintlify/security/*` if/when those land. — owner: needs-triage (small, one-line nav change).

- [open] 2026-04-25 · W12 · real-provider soak coverage
  Finding: W12 PR #30 ships a fake-WS-peer soak harness only. Real provider regressions (OpenAI Realtime auth churn, Gemini Live half-open sockets, channel adapter rate-limit cascades) are NOT exercised because no long-lived test accounts exist.
  Citation: PR #30 conductor-questions block; `feral-core/tests/test_voice_soak.py`.
  Proposal: Optional follow-up workstream once we have dedicated long-lived test accounts; gate behind a separate `--runsoak-real` flag and a CI secret. — owner: needs-triage.

- [open] 2026-04-25 · W12 · soak-nightly silent failures
  Finding: `.github/workflows/soak-nightly.yml` uses `continue-on-error: true` per the W12 charter (so a flaky soak doesn't break the green CI history). Net effect: failures are visible only to whoever opens the workflow run page.
  Citation: PR #30 (`.github/workflows/soak-nightly.yml`).
  Proposal: Wire a Slack/PagerDuty/issue-creator notifier on non-success so canary regressions get active eyes. Belongs in a small ops-tooling follow-up, not a new W##. — owner: needs-triage.

---

## Closed follow-ups

(none yet)
