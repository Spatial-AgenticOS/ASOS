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

- [open] 2026-04-25 · W8 · `feral-core/security/vault.py` (W9 territory)
  Finding: W8 needs a `publisher_keys` namespace inside the existing vault to pin Ed25519 publisher pubkeys. The vault interface lacked namespaced put/get, so W8 added additive `put_namespace`/`get_namespace`/`list_namespace`/`remove_namespace` methods (flat `<ns>::<key>` storage on top of the existing JSON store). Existing `put`/`get` are unchanged.
  Citation: `feral-core/security/vault.py` (`BlindVault.put_namespace` etc.).
  Proposal: W9 should fold these into whatever proper namespace hierarchy it lands; until then they are additive and non-breaking. — owner: W9.

- [open] 2026-04-25 · W8 · `feral-core/models/app_manifest.py` (orange zone)
  Finding: W8 widened `AppManifest.permissions` from `list[str]` to `list[str] | dict[str, Any]` so the GenUI sandbox + signing layer can carry the structured `{network: [...], justification: "..."}` shape end-to-end. `list(manifest.permissions)` keeps working on both shapes (dict iteration yields keys), and existing tests + code paths (`api/routes/apps.py::_manifest_summary`, registry tests) still pass.
  Citation: `feral-core/models/app_manifest.py` (`AppManifest.permissions`).
  Proposal: Conductor confirm the union is acceptable, or dispatch a W## to formalise a `Permissions` model. — owner: needs-triage.

- [open] 2026-04-25 · W8 · `feral-core/cli/app_commands.py`
  Finding: W8 added `feral app sign` and `feral app verify` subcommands. The W8 charter explicitly named this file ("you may edit this; it's adjacent to your owned api/routes/apps.py"). No other workstream is currently editing it.
  Citation: `feral-core/cli/app_commands.py` (`cmd_app_sign`, `cmd_app_verify`, `register_app_subparser`).
  Proposal: Allowed by charter; flag here for visibility in case a CLI-owning workstream emerges later. — owner: needs-triage.

- [open] 2026-04-25 · W8 · `docs/mintlify/genui/**` (read-only zone for W8)
  Finding: W8's charter lists `docs/mintlify/genui/**` as read-only context, but also lists the two new mdx files (`signing.mdx`, `sandbox.mdx`) as W8 deliverables. W8 created them; flagging the boundary crossing here per doctrine.
  Citation: `docs/mintlify/genui/signing.mdx`, `docs/mintlify/genui/sandbox.mdx`.
  Proposal: Conductor confirm the docs mdx pages are W8's responsibility, or hand off to the docs workstream. — owner: needs-triage.

- [open] 2026-04-25 · W8 · CSP test lives in vitest, not pytest
  Finding: §C.2 W8 row says `feral-core/tests/test_genui_*.py`; the W8 charter spec text says "Vitest, NOT pytest" and asks for `feral-client-v2/src/__tests__/pages/AppSurface.csp.test.jsx`. W8 followed the charter spec text because AppSurface itself is a React component — assertions on `<iframe sandbox>` and CSP `<meta>` only make sense in jsdom, and the file lives in `feral-client-v2/`.
  Citation: `feral-client-v2/src/__tests__/pages/AppSurface.csp.test.jsx`.
  Proposal: Update §C.2 to allow W8 vitest files under `feral-client-v2/src/__tests__/pages/AppSurface.*`. — owner: conductor.

---

## Closed follow-ups

(none yet)
