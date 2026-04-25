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

---

## Closed follow-ups

(none yet)
