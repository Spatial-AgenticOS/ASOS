# FERAL-AI — Agent Workstream Follow-ups

Out-of-scope issues discovered by workers while completing their assigned
workstream. Each entry: `YYYY-MM-DD | finder-WID | path:line | one-line user/dev impact | proposed workstream`.

The Conductor (§B) reads this file each cycle and either dispatches a new W## or rolls the issue into an existing workstream.

---

- 2026-04-24 | W3 | `feral-core/mcp/server.py:472,474,477` | `_call_get_perception` reads `frame.heart_rate_bpm`, `frame.temperature_c`, and `frame.gps`, but `PerceptionFrame` exposes `heart_rate`, `skin_temperature_c`, and no `gps` field — every MCP `feral_get_perception` tool call against a populated PerceptionEngine will raise `AttributeError` at runtime. mypy already flags this on `main`. | propose new workstream `W16-mcp-perception-attrs` (single-file fix, also worth a regression test that calls `_call_get_perception` with a populated `PerceptionFrame`).
