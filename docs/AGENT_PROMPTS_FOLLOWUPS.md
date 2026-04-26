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

- [open] 2026-04-25 · W11 · roadmap section number drift
  Finding: The W11 brief in `docs/AGENT_PROMPTS.md` cites "§3.4 #1" for chaos drills, but the actual row in `FEATURE_STABILITY_ROADMAP.md` lives at §3.3 #1 ("Memory & federated sync — P0", row 1). W11 PR #31's commit message follows the brief while the docs/PR body follows the roadmap.
  Citation: PR #31 (`feral/W11-sync-chaos`); `FEATURE_STABILITY_ROADMAP.md` §3.3 row 1.
  Proposal: Reconcile to §3.3 #1 in the roadmap post-merge sweep; fix the W11 entry in `docs/AGENT_PROMPTS.md` (this PR) to match. — owner: conductor.

- [open] 2026-04-25 · W11 · pytest `chaos` marker registration
  Finding: W11 registered a new `chaos` pytest marker in `feral-core/pyproject.toml` (single-line additive change to `[tool.pytest.ini_options].markers`). pyproject.toml is not in W11's owned-paths; flagged for visibility.
  Citation: PR #31 (`feral-core/pyproject.toml`).
  Proposal: Allowed (matches the §C.2 precedent set by W12's `--runsoak` conftest extension; both are test-infra additions inside the file's existing markers list). — owner: conductor sign-off.

- [open] 2026-04-25 · W11 · pyfakefs vs monkeypatch for disk-full tests
  Finding: The W11 brief suggested `pyfakefs` for the ENOSPC simulation. W11 PR #31 used monkeypatch instead to avoid adding a new dev dependency.
  Citation: PR #31 conductor-questions block; `feral-core/tests/test_memory_sync_chaos.py` (`TestDiskFull`).
  Proposal: Either (a) accept monkeypatch as the W11-canonical pattern for ENOSPC sims, or (b) add `pyfakefs` to the dev extras and refactor in a focused follow-up. The current monkeypatch impl is honest and self-contained, so (a) is the cheaper path. — owner: needs-triage.

- [open] 2026-04-25 · W11 + W12 + W17 · mintlify nav consolidation
  Finding: W8 (`security/genui.mdx`), W9 (`security/vault.mdx` + `security/pairing.mdx`), W11 (`memory/chaos.mdx`), and W12 (`operations/soak.mdx`) are all creating new mintlify sub-trees with no existing nav entries in `docs/mintlify/docs.json`. Each file is correct in isolation but the docs site won't surface them until the nav is updated.
  Citation: PRs #27, #28, #30, #31; `docs/mintlify/docs.json`.
  Proposal: Single small PR by the docs owner that adds nav entries for "Memory", "Operations", and "Security" groups in one shot once W8/W9/W11/W12 land. — owner: needs-triage (docs).

- [open] 2026-04-25 · W21 · channel-manifest phase 2 (Slack / Discord / WhatsApp)
  Finding: W21 Phase 1 (this PR) ships the schema + loader + signing glue + bundled Telegram manifest. Slack / Discord / WhatsApp adapters in `feral-core/channels/base.py` still have no `feral-channel.manifest.json` beside them, so the capability registry only sees Telegram.
  Citation: `feral-core/channels/base.py:421` (DiscordChannel), `:585` (SlackChannel), `:759` (WhatsAppChannel); `feral-core/channels/telegram/feral-channel.manifest.json` (the Phase-1 worked example).
  Proposal: W21.2 — split the in-base.py adapters into per-channel directories and add signed `feral-channel.manifest.json` for each. Keeps the Phase-1 schema and signer untouched. — owner: W21.2.

- [open] 2026-04-25 · W21 · channel SDK barrel + extension SDK
  Finding: `docs/contributing-channels.md` §5 documents the SDK-barrel rule ("channel code reaches into core ONLY via `feral_core.channels.sdk`") prospectively, but the `feral_core.channels.sdk` module itself does not yet exist. Phase-1 channels still import directly from `channels.base` etc.
  Citation: `docs/contributing-channels.md` §5; openclaw `AGENTS.md:27–30`.
  Proposal: W21.3 — author `feral-core/channels/sdk/__init__.py` as the public barrel (typed runtime helpers, `Channel`, `ChannelMessage`, `ChannelResponse`, manifest types) and add a lint that fails new channel imports outside the barrel. — owner: W21.3.

- [open] 2026-04-25 · W21 · 3rd-party channel discovery (entry points + vault-pinned keys)
  Finding: `loader.discover_bundled()` only walks the in-tree `feral-core/channels/<id>/` directory. There is no entry-point loader, no out-of-tree path discovery, and no vault integration for `public_key_provider` (Phase 1 trusts the embedded public key because the manifest is in-tree).
  Citation: `feral-core/channels/loader.py` (`discover_bundled`, `load_with_verification`).
  Proposal: W21.4 — add `discover_entry_points()` reading the `feral.channels` entry-point group; integrate `feral_core.security.vault` as the default `public_key_provider` so 3rd-party manifests must pin to a vaulted publisher key. — owner: W21.4.

- [open] 2026-04-25 · W21 · `ChannelManager.CHANNEL_TYPES` ↔ manifest discovery convergence
  Finding: `ChannelManager.CHANNEL_TYPES` in `feral-core/channels/base.py:889` still hard-codes the four classes. The Phase-1 contract test asserts the manifest provider IDs are present in that map, but the consumer (the orchestrator that calls `start_channel(...)`) doesn't yet build itself from the manifest registry.
  Citation: `feral-core/channels/base.py:889`; `feral-core/tests/test_channel_manifest_contract.py::test_channel_manager_recognises_manifest_provider`.
  Proposal: When W21.2 lands the remaining manifests, follow up with a small change in `feral-core/channels/base.py` to derive `CHANNEL_TYPES` from the registry (or replace it entirely with a registry lookup). Out-of-scope for Phase 1 (cross-boundary) and Phase 2 (still in-tree only). — owner: W21.3.- [open] 2026-04-25 · W16 · boot-path wiring of `run_migration_if_needed`
  Finding: W16 (PR #37) ships `security/auth_profiles/migrate.py` but does not wire `run_migration_if_needed()` into the brain boot path; existing installs migrate only when an operator runs `feral key migrate`. Wiring touches `cli/main.py` / brain startup which is outside W16's owned paths.
  Citation: PR #37; `feral-core/security/auth_profiles/migrate.py:run_migration_if_needed`.
  Proposal: Tiny W16-followup PR that adds a single call from the brain boot path (or amend W9's vault `_load` to invoke it before the encryption migration). — owner: needs-triage.

- [open] 2026-04-25 · W16 · legacy `credentials.json` deletion lifecycle
  Finding: W16's migration leaves `~/.feral/credentials.json` in place and only writes `…bak.legacy.w16` (mode 0600). W9 still owns the eventual deletion of the original file; until the boot path treats the per-agent store as canonical, both files coexist.
  Citation: PR #37; `feral-core/security/vault.py:_migrate_from_plaintext` (W9-owned).
  Proposal: W9 follow-up that, once `auth_profiles.json` exists at the per-agent path, unlinks the legacy file on the next encryption migration. — owner: W9 / needs-triage.- [open] 2026-04-25 · W13 · `feral-core/api/server.py` orange zone (W13 touch)
  Finding: W13 modifies the existing `FERAL_METRICS_ENDPOINT` block in `feral-core/api/server.py` (default-flip from off to on, adds `FERAL_METRICS_PUBLIC` switch, off-loopback returns 404) and adds two `_emit_http_metrics()` calls inside the existing `RateLimitMiddleware.dispatch`. `server.py` is the same orange-zone file already shared with W1 (startup hook) and W17 (router include).
  Citation: this PR; `feral-core/api/server.py` `metrics_endpoint` and `RateLimitMiddleware`.
  Proposal: Conductor sign-off — the changes are confined to the existing `/metrics` block and a single emit call site in the existing middleware, no overlap with W1's startup hook or W17's `app.include_router(sessions_router)`. — owner: conductor.

- [open] 2026-04-25 · W13 → W19 / W11 / W17 / W4 / W9 · cross-module emit() wiring (W13.1)
  Finding: W13 ships the metric REGISTRY + `emit()` helper but only wires ONE call site (HTTP middleware in `api/server.py`) to keep the PR strictly inside owned paths. The dashboard + alert rules reference metrics that will stay at 0 until each owning workstream lands its own `emit()` calls.
  Citation: `feral-core/observability/metrics.py` (`_METRICS` docstrings name the owners); `ops/grafana/feral-overview.json`; `ops/prometheus/alerts.yml`.
  Proposal: Track as W13.1. Owners and call sites:
    - W19 — `feral-core/agents/llm_provider.py` → `feral_llm_429_total{provider}`, `feral_llm_failover_chain_exhausted_total`.
    - W11 — `feral-core/memory/sync.py` → `feral_sync_active_peers`, `feral_sync_failures_total{reason}`, `feral_sync_was_active_recent`.
    - W17 — `feral-core/agents/supervisor.py` → `feral_supervisor_approval_queue`.
    - W4 — `feral-core/security/sandbox_policy.py` + sandbox runner → `feral_tool_denials_total{tool}`, `feral_sandbox_kills_total{reason}`.
    - W9 — `feral-core/security/vault.py` → `feral_vault_decrypt_errors_total`.
    - W13 sweep — `feral-core/api/server.py` WS endpoints → `feral_ws_active_sessions`.
    Each is one `emit()` call inside an already-owned module; can land in the next routine PR for that workstream. — owner: needs-triage (per-workstream).

- [open] 2026-04-25 · W13 · `feral-core/pyproject.toml` observability extra
  Finding: W13 adds `prometheus-client>=0.20` to the `[project.optional-dependencies].observability` and `all` extras in `feral-core/pyproject.toml`. `pyproject.toml` is not in W13's nominal owned paths; flagged for visibility.
  Citation: this PR; `feral-core/pyproject.toml`.
  Proposal: Allowed (matches the §C.2 precedent set by W11's `chaos` marker addition and W12's soak conftest extension; both were single-line additive dependency / config changes inside the file's existing keys). — owner: conductor sign-off.

- [open] 2026-04-25 · W13 · mintlify nav for `docs/mintlify/operations/metrics.mdx`
  Finding: W13 adds `docs/mintlify/operations/metrics.mdx` alongside the existing `operations/soak.mdx` (W12). Neither has an entry in `docs/mintlify/docs.json` yet. This is the same nav-ownership question already raised by W12.
  Citation: this PR; existing follow-up `2026-04-25 · W12 · mintlify nav ownership for docs/mintlify/operations/`.
  Proposal: Roll into the same docs-owner sweep that resolves W8/W9/W11/W12 nav additions. — owner: needs-triage (docs).

- [open] 2026-04-26 · W24d · security/* mintlify pages still unauthored
  Finding: The W24d charter referenced `docs/mintlify/security/vault.mdx` (W9), `docs/mintlify/security/pairing.mdx` (W9), and `docs/mintlify/security/genui.mdx` (W8) for the new "Security" nav group, but none of those paths exist on `origin/main` at the W24d cutoff. The only security-adjacent mdx files on disk are `docs/mintlify/genui/signing.mdx` and `docs/mintlify/genui/sandbox.mdx`, so W24d's docs.json Security group points at those two pages instead.
  Citation: W24d — `docs/mintlify/docs.json` Security group; `scripts/check_mintlify_nav.py`.
  Proposal: W9 / W8 docs owners should author the three charter-named mdx files (or move `genui/signing.mdx` + `genui/sandbox.mdx` under `security/`). Once landed, update the Security group entries accordingly; the `check_mintlify_nav.py` linter will keep the nav honest during the transition. — owner: W9 + W8 docs.

- [open] 2026-04-26 · W24d · `advertise_brain_async` wiring into api/state.py
  Finding: W24d introduces `services.mdns.advertise_brain_async(...)` as the non-blocking variant. The async startup path in `feral-core/api/state.py` still calls the sync `advertise_brain(...)` (W24d made the sync path loop-safe by offloading to a thread, so this is correct-but-suboptimal). Switching to `await advertise_brain_async(...)` would remove one thread hop on boot.
  Citation: `feral-core/api/state.py:727–729`; `feral-core/services/mdns.py` (W24d).
  Proposal: Follow-up PR by the api-startup owner to `await advertise_brain_async(...)` from the `boot_subsystem("mDNS")` block. Cross-boundary per W24d's owned-paths scope. — owner: needs-triage (api).- [open] 2026-04-26 · W24a · `?class=chat` query param for `/api/llm/providers/{id}/models` + v2 Settings picker wiring (W24a.1)
  Finding: `BaseProvider.list_models(model_class=...)` is the filter hook shipped by W24a. The HTTP route in `feral-core/api/routes/llm.py::list_llm_provider_models` and the v2 Settings dropdown in `feral-client-v2/src/pages/Settings.jsx` still hit the unfiltered list; the chat-only filter reaches the dispatcher but not the REST surface. Neither file is in W24a's owned paths.
  Citation: `feral-core/api/routes/llm.py:141`; `feral-client-v2/src/pages/Settings.jsx:441`; W24a PR.
  Proposal: Tracked as W24a.1 — a small cross-boundary PR that adds `?class=` to the route and passes `?class=chat` from Settings.jsx when rendering the chat composer dropdown. — owner: conductor.

- [open] 2026-04-26 · W24a · Re-run `scripts/refresh_provider_catalog.py` with live keys before v2026.5.1 tag
  Finding: W24a ships the refresh script + representative fixtures, but the host that authored the PR had no provider keys set in-env, so the bundled `model_catalog.json` remains the hand-seeded 2026-04-26 snapshot rather than a live-captured one. Dry-run confirms drift = 0 against the hand-seeded list. The live fetch will update exact pricing (especially DeepSeek's 75%-off window ending 2026-05-05) and catch any mid-week provider-side additions.
  Citation: `scripts/refresh_provider_catalog.py`; W24a PR.
  Proposal: Conductor runs the script with keys set before cutting v2026.5.1; expected drift ≤ 5 IDs per provider. — owner: conductor.

- [open] 2026-04-26 · W24a · `test_provider_catalog.py::TestBundledCatalogFreshness` catalog-pin assertions need a refresh window
  Finding: The `_VERIFIED_GEMINI_IDS` + `_DEPRECATED_OPENAI_IDS` + "anthropic endpoint is null" assertions were written at the 2026-04-24 snapshot. To keep them green W24a kept the Gemini `-preview` suffix + omitted `gpt-4o*` from the bundled openai seed + left the anthropic endpoint field null (with the live URL mirrored to `_live_endpoint`). Once Anthropic's `/v1/models` is the canonical refresh path (post W24a.2) and Gemini flips 3.x to GA, these asserts should be relaxed to "verified set from the most recent refresh" rather than hard-pinned literals.
  Citation: `feral-core/tests/test_provider_catalog.py:302-334`.
  Proposal: Replace literal pinning with a snapshot-based assertion driven by the fixture files. — owner: conductor.---  Proposal: Follow-up PR by the api-startup owner to `await advertise_brain_async(...)` from the `boot_subsystem("mDNS")` block. Cross-boundary per W24d's owned-paths scope. — owner: needs-triage (api).- [open] 2026-04-26 · W24b · remaining plaintext `credentials.json` writers in `cli/setup_wizard.py`
  Finding: W24b fixed the ``feral.config`` plaintext leak (`ConfigLoader.save_credentials`) but the two CLI setup-wizard classes still call ``creds_path.write_text(json.dumps(...))`` directly inside their ``_save_all`` methods, leaking plaintext whenever a user runs the interactive wizard.
  Citation: `feral-core/cli/setup_wizard.py:1167-1169` and `feral-core/cli/setup_wizard.py:1687-1692` (and the corresponding `_load_existing_creds` read at `:566`, `:1347`). Also `feral-core/cli/setup/state.py:47` (`_write_json` into `credentials.json`).
  Proposal: Track as W24b.1 — route each wizard write through `ConfigLoader.save_credentials` (now vault-backed) or call `BlindVault.set_credential` directly, and drop the plaintext `write_text` + `chmod 0600`. — owner: needs-triage.---
## Closed follow-ups

(none yet)
