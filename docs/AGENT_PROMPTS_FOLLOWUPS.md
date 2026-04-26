# Agent Prompts — Follow-ups

One-line entries for cross-boundary edits made by workstream subagents.
Used to keep the W-series owned-paths discipline auditable.

## W17 — Subagent spawn (feral/W17-subagent-spawn)

- `feral-core/api/server.py`: 1-line registration of the new
  `sessions_router` (`app.include_router(sessions_router)  # W17`).
  Required to expose `POST /api/sessions/{id}/spawn`.
