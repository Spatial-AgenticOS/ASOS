# Agent Prompts — Follow-ups

This file is the catch-all queue for issues discovered while running a workstream that lie **outside** the W## owned-paths set the worker was dispatched against. Per `docs/AGENT_PROMPTS.md` §G, the rule is: file the follow-up here, keep working on your own workstream, let the Conductor decide where the work lands.

Each entry: `date • finder • path:line • impact • proposed workstream`.

---

## Open

### 2026-04-24 • W7 • `desktop/package.json:4` • npm `version` literal duplicates `feral-core/pyproject.toml::[project] version` • W7 follow-up or W10 (multi-CI)

`desktop/package.json` carries `"version": "2026.4.32"` next to `desktop/src-tauri/tauri.conf.json` (which is W7-owned and refactored). The literal is currently in sync, and `scripts/sync_versions.py --check` will fail loudly the moment it drifts. But the file itself sits under `desktop/` which is owned by W10 (`.github/workflows/desktop.yml` and `desktop/src-tauri/src/lib.rs` smoke harness, see §C.2 W10 row). Today's W7 PR did NOT mutate this file. Suggested fix is to either (a) absorb `desktop/package.json` into the W7 owned set in §C.2 or (b) have W10 cite W7's `scripts/sync_versions.py` as the source of truth for the `version` field and call it from `desktop.yml` before `pnpm tauri build`.

### 2026-04-24 • W7 • `feral-extension/manifest.json:4` • Chrome MV3 `version` literal • file unowned

Same situation as above: the file is in sync, the script enforces drift = 0, but `feral-extension/` has no W## owner in the §C.2 map. Either give it an owner (a new W17?) or extend W7's owned set.

### 2026-04-24 • W7 • `feral-ha-addon/UPGRADE.md:26` • prose example `ARG FERAL_VERSION=2026.4.32` • file unowned

The W7 owned set in §C.2 lists `feral-ha-addon/config.yaml` and `feral-ha-addon/Dockerfile`. `UPGRADE.md` lives in the same component but is documentation. `scripts/sync_versions.py` already syncs it, but a future PR that edits the prose around the snippet should not have to ask. Suggest adding `feral-ha-addon/UPGRADE.md` to W7's owned set — it is the canonical upgrade-procedure doc for the add-on this workstream owns.

### 2026-04-24 • W7 • `.github/workflows/ha-addon.yml:21,27` • workflow defaults still cite a literal version • W10 coordination

`scripts/sync_versions.py --check` keeps these lines from drifting, but the file itself is a CI workflow and W10 owns `.github/workflows/*` for mobile/desktop/registry/SDK. W7 did NOT edit this file. Conductor: please decide whether the version-injecting publish workflow should fetch the version from `feral-core/pyproject.toml` at build time (preferred) instead of carrying a default literal.

### 2026-04-24 • W7 • `feral-core/agents/self_model.py:125` • literal `version=2026.4.32` in docstring example • out-of-scope

The `build_runtime_line` docstring shows an example with the version baked into the prose. `scripts/sync_versions.py` keeps it syncing on each release, but ideally the docstring should use a placeholder like `version=<calver>` so future readers don't trip over it. Single-line edit, but the file is owned by W15 (`agents/llm_provider.py` + `agents/router.py` are W15's; `self_model.py` is in the same `agents/` package). Hand to W15 to decide.

### 2026-04-24 • W7 • `scripts/bump_version.py` • predates W7's `scripts/sync_versions.py` • cleanup

`scripts/bump_version.py` is the legacy version-bumping script. It is still referenced by `feral-core/tests/test_version_consistency.py`. W7 did NOT delete it (out of scope: legacy script is not in W7's owned paths). Once `scripts/sync_versions.py` is the canonical entry point, `bump_version.py` can be retired and `test_version_consistency.py` rewritten to import from the new location. Owner: TBD by Conductor.

### 2026-04-24 • W7 • `README.md:39` test-count line • W7 added a marker; ongoing maintenance falls on every PR that adds/removes tests • all workstreams

The `<!-- sync-versions:test-counts pytest=N vitest=M -->` marker now lives in `README.md`. The `version-coherence` CI gate fails any PR whose live test counts don't match the marker. Workers W1, W2, W3, W4, W5, W6, etc. all add/remove tests; their PRs MUST update the marker AND the human-readable line above it (`**N backend + M frontend tests pass**`). Document this in the §E push protocol so future workers don't get blindsided by a red gate.

### 2026-04-24 • W7 • `.github/workflows/ci.yml:96` notice text references stale coverage gate `25/18/19/27` and `20/40/18/20` • W14

The CI workflow's `notice` lines still reference old coverage thresholds. W14 owns `vitest.config.js` thresholds; coordinating an update with the same PR that ratchets the floors is the natural place.

---

## Closed

(none yet)
