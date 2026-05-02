# Release pipeline

This is the maintainer-facing runbook for cutting a FERAL release.

The release workflow (`.github/workflows/publish.yml`) is a **staged
pipeline** with three jobs and two manual-approval gates:

```
  build  ─▶  stage  ─▶  publish
 (smoke)   (canary)     (prod)
            ├ env: testpypi-stage  ← approval gate
            └ env: pypi            ← approval gate
```

## Why a staged pipeline

The earlier single-job workflow published straight to PyPI after an
in-tree smoke test. That smoke ran against the wheel on disk, not
against the artifact PyPI actually distributes, so a subset of
regressions (metadata drift, missing files, index resolution, dep
conflicts with real-world installs) could only be caught *after* the
version had already shipped to users.

The staged pipeline closes that gap with a real canary:

1. **build** — wheel + sdist; run `scripts/release_wheel_smoke.py`
   against an in-venv install of the freshly built wheel. Fails fast
   on anything that is broken before we hand an artifact to an index.
2. **stage** — upload the artifact to **TestPyPI**, wait for it to
   surface in the TestPyPI index, `pip install` it from TestPyPI in a
   clean venv (with `--extra-index-url https://pypi.org/simple/` so
   runtime deps still resolve), and run the same runtime smoke again,
   this time asserting `importlib.metadata.version("feral-ai")` matches
   the tag.
3. **publish** — only runs after the stage job succeeds. Pushes the
   artifact to real PyPI and creates the GitHub Release.

Both the stage and publish jobs run under GitHub Actions **environments**
(`testpypi-stage` and `pypi`), so maintainers can configure required
reviewers on each environment and keep a manual approval step in front
of the canary upload and the production upload.

After `publish` completes, `install-smoke.yml` continues to run as a
post-prod matrix check against real PyPI (Ubuntu/macOS × Py 3.11/3.12).

## One-time setup

### GitHub environments

In **Settings → Environments** create two environments:

| Environment | Purpose | Suggested protection |
|---|---|---|
| `testpypi-stage` | Canary uploads to TestPyPI. | Required reviewers: at least one maintainer. Wait timer: 0. |
| `pypi` | Production uploads to PyPI. | Required reviewers: at least one maintainer. Wait timer (optional): 5–15 min to leave room for a human abort. |

### Trusted publishers (OIDC)

The workflow uses `pypa/gh-action-pypi-publish` with OIDC, so there are
no long-lived API tokens in repo secrets. On both sides:

1. **PyPI** → project `feral-ai` → *Publishing* → *Add a pending
   publisher*:
   - Owner: `<org/user>`
   - Repository: `<repo>`
   - Workflow filename: `publish.yml`
   - Environment: `pypi`
2. **TestPyPI** → project `feral-ai` → *Publishing* → same as above
   with environment `testpypi-stage`.

You must register the project on TestPyPI the first time (a single
manual upload of any version is enough to create the project slot;
after that the workflow owns it via trusted publishing).

## Normal release flow

1. Run `scripts/release.py <bump>` locally to bump the version, sync
   every declared literal, stub a CHANGELOG entry, run tests, build
   artifacts, and open the release PR. (Unchanged from before.)
2. Merge the release PR on `main`.
3. Tag the merged commit:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

4. The `Release` workflow starts. In the Actions UI:
   - Approve the `testpypi-stage` environment when prompted.
   - Watch the canary smoke in the `stage` job logs. It must report
     `wheel serves v2 bundle and passes /health + / contract`.
   - Approve the `pypi` environment when prompted.
5. After `publish` finishes, `install-smoke.yml` fires automatically
   and re-verifies the published artifact on each supported Python /
   OS combination.

## `workflow_dispatch` inputs

From *Actions → Release → Run workflow* you can trigger the pipeline
manually. Two inputs are available:

| Input | Default | When to use |
|---|---|---|
| `skip_stage` | `false` | **Emergency only.** Bypass the TestPyPI canary and publish straight to PyPI from a dispatched run. Use when TestPyPI itself is down and a hot-fix must ship. Document the reason in the release PR. |
| `dry_run` | `false` | Run **build + stage** only. Useful to exercise the pipeline end-to-end (including a real TestPyPI upload) without touching production PyPI. Pair with `skip_stage=false`. |

Tag-push events (`v*`) always run the full three-stage flow; the
dispatch inputs are only read when the trigger is `workflow_dispatch`.

## What the runtime smoke asserts

`scripts/release_wheel_smoke.py` is the single source of truth for
"does the installed wheel work?" It is reused by both the build-time
and canary-time smoke steps. Contract:

- `feral-ai` is importable and `importlib.metadata.version(...)`
  matches `--expected-version`.
- `webui_v2/` is a site-packages sibling of `api/`, with
  `index.html` and at least one `assets/*.js` + `assets/*.css`.
- FastAPI app boots under `TestClient`; `/health` is 200; `/` (with
  the smoke API key) is 200, contains `FERAL` + `v2` markers, and
  does **not** contain the v1-only `leaflet` marker (guards against
  the silent v1 fallback regression that shipped 2026.4.17).

Anything that breaks this contract fails the release before the
publish job runs.

## Rollback

If the canary smoke fails:
- Nothing has been pushed to production PyPI.
- A version bucket on TestPyPI has been consumed. Bump the patch
  component (`scripts/release.py patch`), re-tag, and re-run.

If production PyPI has shipped a bad version:
- Yank the release on PyPI (`pypi.org/manage/project/feral-ai/release/…`).
- Cut a fixed patch release through the normal flow.
- Do **not** reuse the same version number; PyPI forbids overwrite.
