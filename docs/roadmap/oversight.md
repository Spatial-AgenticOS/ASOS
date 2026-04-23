# Oversight roadmap

## Current state

- [x] `Supervisor` wraps the orchestrator's three public methods
  (`handle_command`, `handle_command_stream`, `handle_ui_event`) —
  Commit 6.
- [x] SQLite audit table `supervisor_events` — Commit 6.
- [x] `supervisor_event` WS frame for live UI — Commit 6.
- [x] Kill switch (`Supervisor.set_paused`) — Commit 6.
- [x] Policy gate hook for Twin — Commit 7.
- [x] `/oversight` v2 page — Commit 6.

## Near-term (next 30 days)

- [ ] **First-party policy rules.** Wire into the policy_gate:
  * `TimeOfDayPolicy(deny_hours=[0, 1, 2, 3, 4, 5, 6])` — skip the
    orchestrator during sleep hours unless explicitly overridden.
  * `KeywordDenyPolicy(["credit card", "ssn", "password"])` — defer
    to a live user before any handler sees the text.
  * `DestructiveConfirmPolicy({"shell_command:rm -rf", …})` — force
    an approval loop for known destructive surfaces.
  Rules compose; the first non-`allowed` verdict wins.
- [ ] **Retention + purge CLI.** `feral oversight prune --older-than 90d`
  so the supervisor log doesn't grow unbounded.
- [ ] **Export to NDJSON.** `feral oversight export > oversight.ndjson`.

## Mid-term (60 days)

- [ ] **Policy editor in Settings.** Today policies live in code. Move
  to SQLite + CRUD so the user can flip "deny keyboard shortcuts
  before 7am" without a redeploy.
- [ ] **Per-source rate limits** inside the supervisor (not just the
  top-level middleware). e.g. proactive can fire at most 5 commands
  per hour; cron 20.
- [ ] **Anomaly alerts.** When supervisor sees a sudden spike of
  `error` decisions, push a proactive alert.

## Long-term (90 days)

- [ ] **Decision provenance**. Every audit row points at which policy
  emitted the verdict (an id + version). Makes "why was this blocked?"
  trivially answerable.
- [ ] **Federated oversight**. Export a slice of the audit log to a
  family / team "watcher" brain for shared trust scenarios (parent
  overseeing a child's twin).
- [ ] **Sandbox rollbacks**. Treat every twin execution as a mini-
  transaction — if the user rejects the audit row within 60 s, invoke
  the executor's `undo()` hook.
