# Agent prompts — out-of-scope follow-ups

Per `docs/AGENT_PROMPTS.md` §G, anything a worker discovers that falls
outside its assigned workstream gets a one-line entry here. The
Conductor sweeps this file each cycle and either dispatches a new
W## or rolls the change into an existing one.

| Date | Finder | path:line | User-impact one-liner | Proposed WID |
|------|--------|-----------|----------------------|--------------|
| 2026-04-24 | W10 | `README.md` | The W10 mission asked for a `## CI` section with status badges for the new mobile/desktop/registry/SDK workflows, but `README.md` is not in the W10 owned set (`docs/AGENT_PROMPTS.md` §C.2; W7's read-only context). Need a tiny `## CI` patch under W7 (or a fresh W## for README badge upkeep) that pastes the five badge URLs listed below. | W7 (or W16) |
| 2026-04-24 | W10 | `sdk/node/package.json` | The `sdk/node/` package has no `package-lock.json` and no `test` script, so `npm ci && npm run test` (the W10 brief's literal command) is impossible. The W10 workflow side-steps this by running `npm install` + `npx vitest --no-save`, which keeps W10 strictly within its `sdk/node/tests/**` ownership but means the SDK owner still needs to commit a lockfile and add `"test": "vitest run"` so future SDK PRs can `npm test` locally without remembering the long form. | W16 (sdk-tooling) |
| 2026-04-24 | W10 | `sdk/python/feral_sdk/tool.py:41` and `sdk/python/feral_sdk/client.py:77` | Two pre-existing mypy errors (`attr-defined`, `var-annotated`) block making `mypy` a hard gate in `.github/workflows/sdk.yml`. W10 currently runs mypy with `continue-on-error: true` and a workflow-level warning. Trivial fix: add `# type: ignore[attr-defined]` on the `_feral_tool_meta` attribute access and annotate `response_parts: list[str] = []` in `client.chat`. Out of W10 owned paths. | W16 (sdk-tooling) |
| 2026-04-24 | W10 | `desktop/package-lock.json` | `desktop/` has no committed lockfile, so the desktop workflow falls back from `npm ci` to `npm install` on every run. Acceptable for now (the workflow tolerates both), but a committed lockfile would make builds reproducible. Out of W10 owned paths. | W16 (desktop-tooling) |
| 2026-04-24 | W10 | `feral-registry/tests/conftest.py` | The existing registry tests all use SQLite via `sqlite+aiosqlite` (see `tests/test_publish_flow.py` env override). The W10 workflow exposes a Postgres service container so future tests can opt in by overriding `FERAL_REGISTRY_DB_URL`, but no test exercises the asyncpg path today. Worth adding a single asyncpg-backed smoke once W10's gate lands. | W16 (registry-tests) |

## Badge URLs to paste into README.md `## CI` section

When W7 (or whoever owns README) lands the badge patch, drop these
five lines under a new `## CI` heading:

```markdown
## CI

[![Brain CI](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/ci.yml)
[![Mobile — iOS](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/mobile-ios.yml/badge.svg)](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/mobile-ios.yml)
[![Mobile — Android](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/mobile-android.yml/badge.svg)](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/mobile-android.yml)
[![Desktop](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/desktop.yml/badge.svg)](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/desktop.yml)
[![Registry](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/registry.yml/badge.svg)](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/registry.yml)
[![SDK](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/sdk.yml/badge.svg)](https://github.com/FERAL-AI/FERAL-AI/actions/workflows/sdk.yml)
```

The badges link to the workflow runs in the FERAL-AI/FERAL-AI repo;
adjust the org/repo segment if the canonical URL differs.

## Roadmap diff staged for §3.2

`FEATURE_STABILITY_ROADMAP.md` §3.2 needs to flip from "no per-PR CI"
to the new state once W10 merges. Suggested patch (out of W10's
owned paths — leaving for the Conductor):

- §3.2 #1 (mobile gate): now lands per-PR + Mondays via
  `mobile-ios.yml` and `mobile-android.yml`. Replace "Add `xcodebuild
  test` … to `.github/workflows/`, weekly minimum" with "Landed in
  v2026.4.32 (W10)."
- §3.2 #2 (`pytest feral-nodes/python-node-sdk/tests`): the SDK now
  has 17 passing tests under `feral-nodes/python-node-sdk/tests/` (8
  pre-existing HUP schema tests + 9 new W10 smoke tests).  The
  remaining `wristband_daemon` and `w300_daemon` jobs are unchanged.
- §3.2 #3 (registry): now gated per-PR via `registry.yml`.
- §3.2 #4 (SDK Vitest + python+mypy): now gated per-PR via `sdk.yml`.
- §3.2 #5 (desktop on `main`): PR trigger restored on `desktop/**`,
  cargo test smoke harness landed under `desktop/src-tauri/{src/lib.rs,tests/smoke.rs}`.
