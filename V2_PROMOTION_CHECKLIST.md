# v2 Promotion Checklist

> When the maintainer has lived in `?v2=1` for a full week without hitting
> a blocker and signs off, run this checklist to flip v2 to default. The
> choice stays reversible via `?v1=1` for two full releases so anyone who
> regresses can fall back instantly.

## Pre-flip verification

- [ ] Sign-off: maintainer has daily-driven `http://localhost:9090/?v2=1` for ≥ 7 days.
- [ ] `cd feral-client-v2 && npx vitest run` → green (20 tests).
- [ ] `cd feral-client && npx vitest run` → green (51 tests).
- [ ] `cd feral-core && python -m pytest tests/test_webui_v2_mount.py -x` → 3 passed.
- [ ] `cd feral-client-v2 && npx vite build` → clean, no CSS warnings.
- [ ] `feral-core/webui-v2/index.html` + `feral-core/webui-v2/assets/` present and match the most recent `feral-client-v2/dist/`.
- [ ] Voice mode round-trip verified end-to-end against a real Brain (start → transcribe → reply → end, provider labels honest).

## The flip (one commit)

1. Edit [`feral-client/src/bootstrap.js`](feral-client/src/bootstrap.js) so the default is v2. Invert the logic:

   ```javascript
   export function maybeRedirectToV2() {
     try {
       if (typeof window === 'undefined') return false;
       const params = new URLSearchParams(window.location.search || '');
       const explicitV1 = params.get('v1') === '1';
       const explicitV2 = params.get('v2') === '1';

       if (explicitV1) {
         try { localStorage.setItem('feral_ui_v1', '1'); } catch {}
         return false;
       }
       if (explicitV2) {
         try { localStorage.removeItem('feral_ui_v1'); } catch {}
       }
       let stayOnV1 = false;
       try { stayOnV1 = localStorage.getItem('feral_ui_v1') === '1'; } catch {}
       if (stayOnV1) return false;

       if (window.location.pathname.startsWith('/v2')) return false;
       window.location.replace('/v2/');
       return true;
     } catch { return false; }
   }
   ```

2. Rebuild v2 and copy to `feral-core/webui-v2/`:

   ```bash
   cd feral-client-v2 && npx vite build
   rm -rf ../feral-core/webui-v2 && mkdir -p ../feral-core/webui-v2
   cp -R dist/. ../feral-core/webui-v2/
   ```

3. Update [`CHANGELOG.md`](CHANGELOG.md) with a release section:

   ```markdown
   ## [YYYY.M.D] - YYYY-MM-DD

   ### Changed
   - **feral-client-v2 is now the default UI.** Open http://localhost:9090/ and
     you land in the ambient-OS shell. Add `?v1=1` to keep using the
     previous client — the choice persists in localStorage. v1 will be
     removed in the release after next.
   ```

4. Bump version (CalVer per [`ASOS/HANDOFF.md § 4`](HANDOFF.md)):

   ```bash
   python scripts/bump_version.py YYYY.M.D
   ```

5. Commit + tag + push.

## Two-release deprecation window

After the flip:

- **Release +1:** v1 still buildable + reachable via `?v1=1`. No code changes to `feral-client/`.
- **Release +2:** v1 still buildable + reachable. Changelog entry: "v1 will be removed in the next release."
- **Release +3:** Delete `feral-client/`, the v1-redirect in `feral-client-v2` (if any), and the v1 bootstrap redirect plumbing. Update `CHANGELOG.md`.

## Emergency rollback (during the 2-release window)

Any user who hits a v2 regression can run:

```bash
# Desktop (browser)
# Visit http://localhost:9090/?v1=1 — sticks in localStorage.

# HA Add-on / server-side force-v1
FERAL_UI=v1 feral start   # if the env knob is wired (optional)
```

If a Brain-side bug is on the critical path, the maintainer reverts the
one-commit flip on `main` and publishes a patch release. `feral-client/`
is untouched until Release +3.
