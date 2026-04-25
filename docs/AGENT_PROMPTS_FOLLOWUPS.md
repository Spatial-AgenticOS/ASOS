# AGENT_PROMPTS Follow-ups

Out-of-scope discoveries surfaced by W* workers. The Conductor reads this file each sweep (§G of `docs/AGENT_PROMPTS.md`) and either dispatches a new W## or rolls the change into an existing one.

Format: one entry per discovery. Always include date, finder W-id, the exact `path:line`, the user-impact one-liner, and a proposed disposition.

---

## 2026-04-25 — W4 — `feral-client-v2/src/styles/ui.css:80,89,127,263,441,492` — z-index numeric literals

- **Finder.** W4
- **Where.** `feral-client-v2/src/styles/ui.css` z-index literals at lines 80 (`.v2-shell-main` = 1), 89 (`.v2-menubar` = 50), 127 (`.v2-dock` = 50), 263 (`.v2-ambient` = 0), 441 (`.v2-voice-overlay` = 200), 492 (`.v2-modal-backdrop` = 100). Plus `feral-client-v2/src/styles/pages.css:744` (`.v2-chat-pane` = 60), `:1111` (`.v2-hub-backdrop` = 110), `:1219` (`.v2-skills-launcher-backdrop` = 115), `:503` and `:634` (`.v2-ambient-page` / `.v2-ambient-fullpage` = 1000).
- **What W4 did.** Defined the named constants in `feral-client-v2/src/styles/_z.css` (z-base / z-dock / z-orb / z-overlay / z-modal / z-toast). Re-declared `.v2-modal-backdrop` in `pages.css` (devices/modal scope) using `var(--z-modal)` so the cascade lands on the named constant. Cannot edit `ui.css` from the W4 owned set — it is the v2 primitives sheet. Note also that `--z-overlay = 90` is now smaller than `.v2-hub-backdrop` (110) and `.v2-skills-launcher-backdrop` (115); those backdrops are conceptually overlays, so a unified pass should re-rank them as overlays not as toasts.
- **User impact.** Today: none direct, the modal-backdrop fix lands via cascade. Long term: any future component that reads a numeric literal will silently regress the named-constant invariant W4 set up.
- **Proposed disposition.** New ticket `W16` (or fold into W14): single-source migrate every numeric `z-index:` in `ui.css` and the rest of `pages.css` (hub-backdrop, skills-launcher-backdrop, chat-pane, ambient-fullpage, voice-overlay) to the named constants in `_z.css`. Add a stylelint rule (`declaration-property-value-allowed-list` for `z-index`) to gate.

## 2026-04-25 — W4 — `feral-client-v2/src/__tests__/ui_components.test.jsx:51-56` — assertion broken by Modal portal

- **Finder.** W4
- **Where.** `feral-client-v2/src/__tests__/ui_components.test.jsx:51-56`, the `'accepts size prop without crashing'` test asserted on `container.firstChild` — which the Modal portal change to `document.body` makes empty by design.
- **What W4 did.** Updated the assertion in-place to use `getByRole('dialog')` (Testing Library's `render` queries baseElement = document.body, so it traverses the portal). Added a comment explaining why. The file is not strictly under the W4 owned-paths in §C.2, but the failing assertion is a direct consequence of the W4-owned `Modal.jsx` portal change, so coordination via the Conductor would have produced the same fix.
- **User impact.** None — the test now correctly verifies the modal mounts with the expected size class.
- **Proposed disposition.** Conductor should formally extend W4's owned set to include Modal-related test files, or accept the in-PR fix as scope creep documented here.

## 2026-04-25 — W4 — added Playwright dependency + .gitignore entries (out of W4 owned paths)

- **Finder.** W4
- **Where.** `feral-client-v2/package.json` + `feral-client-v2/package-lock.json` (added `@playwright/test` as a devDependency); `feral-client-v2/.gitignore` (added `playwright-report/`, `test-results/`, `playwright/.cache/`).
- **What W4 did.** Step 1 of the W4 deliverable said "create a minimal playwright.config.ts if it does not exist". The compiled spec needs `@playwright/test` to import; without it the spec is dead code. I added the dependency and the artifact ignores so other devs can run `npx playwright test` cleanly. None of these files are in W4's listed owned set.
- **User impact.** Positive — the e2e is actually runnable. Risk is small (a single new devDependency).
- **Proposed disposition.** W14 should accept the dependency on take-over, or move it into a dedicated `e2e/` workspace with its own `package.json`. Either way, the .gitignore additions stand.

## 2026-04-25 — W4 — file-ownership map paths in §C.2 W4 row are wrong

- **Finder.** W4
- **Where.** `docs/AGENT_PROMPTS.md` §C.2 W4 row lists `feral-client-v2/src/components/ui/Modal.jsx` and (in §D.W4 step 2) `feral-client-v2/src/components/{Shell.jsx,Dock.jsx,Orb.jsx,ui/Modal.jsx}`. None of those paths exist. The actual files live at `src/ui/Modal.jsx`, `src/shell/Shell.jsx`, `src/shell/Dock.jsx`, and `src/ui/Orb.jsx`.
- **What W4 did.** Edited the actual file at `src/ui/Modal.jsx` (the only file matching the unambiguous intent of "Modal.jsx in v2"). Read Shell/Dock/Orb for context but did not edit (they don't carry inline z-index — only their CSS classes do, and that CSS lives in `ui.css` which is out of scope per the previous follow-up).
- **User impact.** None.
- **Proposed disposition.** Conductor patches `docs/AGENT_PROMPTS.md` §C.2 W4 row paths in the next maintenance sweep to match the on-disk layout.
