# Agent prompts — cross-workstream follow-ups

Append-only. Each line: `WID | path | reason`.

W11 | feral-core/pyproject.toml | Registered the `chaos` pytest marker so `pytest -m chaos` runs cleanly without `PytestUnknownMarkWarning`. Marker-only addition; no test runner config or coverage threshold changed.
W11 | docs/mintlify/docs.json   | New page `memory/chaos.mdx` is not yet wired into the Mintlify nav (no existing "Memory" group). Conductor or docs owner: add a `Memory` group containing `memory/chaos` when convenient.
