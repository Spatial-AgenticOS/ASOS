# Test coverage ratchet

Coverage is **enforced on every `pytest` and `vitest` run**, not a special
invocation. Regressions fail the PR. Raising the floor is a one-file change;
lowering it requires a commit-message justification.

## Current floors (as of this commit)

| Surface        | Tool         | Floor             | Evidence                                    |
|----------------|--------------|-------------------|---------------------------------------------|
| `feral-core/`  | pytest-cov   | 50% lines         | `feral-core/pyproject.toml [tool.coverage]` |
| `feral-client-v2/` | vitest v8 | 24/17/18/26 (stmts/branches/funcs/lines) | `feral-client-v2/vitest.config.js` |

The 50% backend target reflects the 51.51% measured across 1875 tests on
this commit — we set the gate just below so a small single-PR regression
blocks. The v2 thresholds sit one point below the 2026.4.27 measurement
(25.39 / 17.34 / 19.01 / 27.06) so a single-comment edit cannot break
CI while a real regression (skipped page, broken hook) still trips the
gate.

## Ratchet plan

| Milestone         | Backend floor | v2 thresholds (s/b/f/l) |
|-------------------|---------------|--------------------------|
| **This commit**   | 50%           | 24 / 17 / 18 / 26        |
| +3 commits (Supervisor + Twin tests landing) | 55%           | 30 / 22 / 25 / 32        |
| Stable ambient-OS 2026 Q2 | 65% | 45 / 35 / 40 / 45 |
| Stable ambient-OS 2026 Q3 | 75% | 60 / 50 / 55 / 60 |
| **Target**                | 90% | 80 / 70 / 75 / 80 |

Raising the floor follows a simple rule: **after every commit that adds
meaningful tests, check the new measurement and bump the floor to (measured
- 1%)**. Never bump both at once; let the suite prove it.

## What's under-covered (honest list)

Low-coverage modules identified from the most recent pytest-cov run:

| Module                                | Line cov | Reason                         |
|---------------------------------------|----------|--------------------------------|
| `skills/impl/system_settings.py`      | 19%      | Heavy side-effect code (fs + OS) |
| `skills/marketplace.py`               | 19%      | Needs integration harness      |
| `skills/impl/weather.py`              | 25%      | Third-party API calls          |
| `skills/package.py`                   | 27%      | Tarball I/O                    |
| `voice/gemini_realtime.py`            | 34%      | Live WebSocket session needed  |
| `skills/impl/workspace_scripts.py`    | 29%      | Spawns subprocesses            |

Each follow-up commit that backfills one of these will update this table +
ratchet the floor.

## How to check locally

```bash
# Backend
cd feral-core && pytest                # coverage runs by default
cd feral-core && pytest --no-cov       # opt out (dev / debugging only)

# Frontend (v2)
cd feral-client-v2 && npm test                 # tests, no coverage
cd feral-client-v2 && npm run test:coverage    # tests + v8 coverage gate
```

## CI

- `.github/workflows/ci.yml` → job `brain-tests`: `pytest --cov-fail-under=50`
- `.github/workflows/ci.yml` → job `client-v2`: `npm run test:coverage`

Both jobs block merge on regression.
