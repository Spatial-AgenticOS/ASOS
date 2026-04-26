## What

Fixes the user-reported "GPT-5.5 missing from Settings → Providers" bug end-to-end (`Roadmap §3.5 P0`, `Appendix A.1`). Three parallel registries used to lock the model dropdown on stale 2025-vintage IDs:
[`feral-core/providers/model_catalog.json`](feral-core/providers/model_catalog.json), [`feral-core/providers/catalog.py`](feral-core/providers/catalog.py)'s `BUILT_IN_DESCRIPTORS`, and [`feral-core/agents/llm_provider.py`](feral-core/agents/llm_provider.py)'s `_PROVIDER_REGISTRY`. The `provider-research.yml` cron that was supposed to refresh the bundled catalog had been disabled since `2026.4.18-dev`, so even the bundled fallback list went stale. This PR replaces every hardcoded model literal with a lazy catalog lookup, re-enables the daily research cron, adds an in-Brain `ProviderCatalog.refresh_async()` 6-hour task, and lands force-refresh-on-stale + a Live/Cached/Stale badge in the v2 Settings → Providers picker.

## Why

- **Roadmap**: `§2.2 LLM/audio/model catalog`, `§3.5 Provider catalog freshness (P0)`, `Appendix A.1` (the literal user complaint thread).
- **Doctrine**: §A's MODEL FRESHNESS rule explicitly bans hardcoded `default_model` literals anywhere in the repo and requires the catalog to be the single source of truth.
- The repo today (per the user's `2026-04-24` recheck) shipped `gpt-4o-mini`, `claude-sonnet-4-5`, `gemini-2.5-flash` as defaults — all three are pre-2026 frontier IDs.

## Test evidence

```
$ cd feral-core && python -m pytest tests/ -q --no-cov
BEFORE (origin/main):
  1952 passed, 1 FAILED, 11 skipped, 138 warnings in 57.67s
  FAILED tests/test_mcp_full.py::TestFeralMCPServerCore::test_get_http_routes_exposes_mcp_endpoints

AFTER (this branch):
  1980 passed, 1 FAILED, 11 skipped, 138 warnings in 53.11s
  FAILED tests/test_mcp_full.py::TestFeralMCPServerCore::test_get_http_routes_exposes_mcp_endpoints
  (same single pre-existing W3-scope failure; +28 new W1 assertions)
```

```
$ cd feral-client-v2 && npm test
BEFORE (origin/main):
  Test Files  31 passed (31)
       Tests  133 passed (133)

AFTER (this branch):
  Test Files  32 passed (32)
       Tests  138 passed (138)
  (+1 new test file Settings.providers.test.jsx, +5 new assertions, no regressions)
```

New test files (4):
- [`feral-core/tests/test_provider_catalog.py`](feral-core/tests/test_provider_catalog.py) — extended with `TestBundledCatalogFreshness` (8 cases: verified-current frontier IDs present, deprecated IDs banned) and `TestDefaultModelLazyResolve` (4 cases: descriptor `default_model==""`, lazy resolve via cache + adapter).
- [`feral-core/tests/test_llm_provider_defaults.py`](feral-core/tests/test_llm_provider_defaults.py) — 8 cases pinning that `LLMProvider()` boots with no hardcoded model literal.
- [`feral-core/tests/test_provider_catalog_refresh.py`](feral-core/tests/test_provider_catalog_refresh.py) — 6 cases for `refresh_async()` (skips uncredentialed providers, writes new `last_refresh`, emits info log, handles failures, respects concurrency cap).
- [`feral-client-v2/src/__tests__/pages/Settings.providers.test.jsx`](feral-client-v2/src/__tests__/pages/Settings.providers.test.jsx) — 5 cases for force-refresh-on-stale (>24h + empty), Live/Cached badge tones, and 401 warning chip.

## Risk

- **Default-model resolution path changed.** `LLMProvider.__init__` and `_get_provider_config` now consult `get_shared_catalog().default_model_for(pid)` instead of a literal. If the catalog hasn't booted (offline `feral setup`, isolated unit tests), defaults fall through to `""` — the v2 picker renders an honest "pick a model" placeholder instead of a stale guess. Mitigation: existing failover tests (`test_llm_failover.py`) continue to pass because they assign `llm.model` directly.
- **`api/server.py` orange-zone touch.** Added a single 8-line additive task at the bottom of `startup()` (`_provider_catalog_refresher`) per §D.W1 step 3's explicit requirement. Filed as a follow-up in `docs/AGENT_PROMPTS_FOLLOWUPS.md` for Conductor + W3/W13 review. No existing lines were modified.
- **Settings.jsx state hook addition.** Added one `useState(modelLastRefresh)` immediately before line 426 (the start of W1's owned range). The hook is consumed by code inside the 426-566 range and lives in the same `ProviderForm` function block as the existing `modelWarning` / `modelSource` state. No overlap with W2's Twin range (1443-1654). Filed as a follow-up note.
- **Rollback.** `git revert` of this commit restores all three hardcoded literal sites and re-disables the cron. The picker would immediately go stale again but the runtime would not break.

## Owned paths edited

W1 paths per §C.2:
- `feral-core/providers/model_catalog.json` — replaced openai/anthropic/gemini model lists; added `last_fetched` + Anthropic `curated_at`.
- `feral-core/providers/catalog.py` — `default_model=""` on every cloud descriptor; new `default_model_for()` + `refresh_async(max_concurrency=4)`; `status_for()` resolves lazily.
- `feral-core/providers/openai_provider.py` — `_models` + `_pricing` updated to verified 2026-04 frontier IDs.
- `feral-core/providers/anthropic_provider.py` — `_models` + `_pricing` updated.
- `feral-core/providers/gemini_provider.py` — `_models` + `_pricing` updated to 3.x preview lineup.
- `feral-core/agents/llm_provider.py` — `_PROVIDER_REGISTRY` shrunk to 2-tuples; new `_default_model_for()`; `__init__` / `switch_provider` / `_get_provider_config` / `LLM_PRESETS` all consult the catalog.
- `feral-core/cli/setup_wizard.py` — `PROVIDERS` dict no longer carries `models`/`default_model`; new `provider_models()` / `provider_default_model()` helpers; updated 4 call sites.
- `feral-core/api/routes/llm.py` — unchanged (already returned `last_refresh` + `warning`).
- `.github/workflows/provider-research.yml` — re-enabled `0 9 * * *` cron with rationale comment.
- `scripts/research_providers.py` — unchanged.
- `feral-client-v2/src/pages/Settings.jsx` — provider section only (lines 426–566 modified; one state hook added at line 419 with cross-reference comment).
- New tests: 4 files listed above.

Out-of-scope coordination touches (filed in `docs/AGENT_PROMPTS_FOLLOWUPS.md`):
- `feral-core/api/server.py` — single additive 8-line `_provider_catalog_refresher` task in `startup()` per §D.W1 step 3 explicit requirement.
- `feral-client-v2/src/pages/Settings.jsx` line 419 — `useState(modelLastRefresh)` declared one line before the W1 range so the hook lives next to its sibling `modelWarning`/`modelSource` state hooks.

## Roadmap diff

- §0 verification numbers: pytest 1980/1/11 (was 1943/1/11 in the snapshot, runtime was 1952/1/11 actual), vitest 138/0 (was 127/3 in the snapshot, runtime was 133/0 actual).
- §2.2 LLM/audio/model catalog: drop the "no live provider model refresh runs on a schedule" line — it now runs daily via cron + every 6h in-Brain.
- §3.5 P0 #1: mark complete; the underlying registries no longer drift.
- Appendix A.1: mark resolved end-to-end (cron re-enabled + in-Brain refresher + UI auto-refresh + age badge).
