# Digital Twin roadmap

## Current state

- [x] `TwinPolicy` + `TwinPolicyStore` + `TwinPolicyEngine` — Commit 7
- [x] `DigitalTwin.execute(domain, action, context, executor)` — Commit 7
- [x] Per-domain modes (draft_only / auto_send / disabled) — Commit 7
- [x] Time windows + daily caps + `requires_user_online` — Commit 7
- [x] Approval queue + `/api/twin/approvals` CRUD — Commit 7
- [x] Kill switch via `Supervisor.set_paused` — Commit 7
- [x] v2 Settings → Twin & Delegation surface — Commit 7
- [x] `feral twin grant / list / revoke / pending` CLI — Commit 7

## Near-term (next 30 days)

- [ ] **First-party executor bindings.** The twin is policy-ready but
  the actual "send iMessage" / "post Slack" / "reply Telegram" /
  "draft Mail" executor callables are not wired yet. Each is a short
  module:
  * `agents/twin_executors/imessage.py` — AppleScript via
    `desktop_control__shell_command`. macOS only.
  * `agents/twin_executors/mail.py` — MCP mail tool wrapper.
  * `agents/twin_executors/slack.py` — `channels.slack.send`.
  * `agents/twin_executors/telegram.py` — `channels.telegram.send`.
- [ ] **Draft preview in the approval card**. Today we show the raw
  context JSON; fetch the executor's `.preview(context)` when present.
- [ ] **Per-contact overrides**. A policy can be `auto_send` globally
  but fall back to draft-only for a named contact ("always draft for
  my boss").

## Mid-term (60 days)

- [ ] **Twin-initiated proposals.** Twin suggests actions by surfacing
  approval rows with `actor='twin'` even when the user didn't ask.
  Requires periodic evaluation against inboxes + calendar.
- [ ] **Multi-turn conversation as twin**. Today `ask()` is one-shot.
  Let the twin conduct a short Slack DM thread up to N turns, each
  gated by a single approval the user can escalate to live-take-over.
- [ ] **Refusal reason surfacing**. When `decide()` returns `queued`
  the reason is stored; show it on the card ("daily cap reached" /
  "outside 09:00-21:00 window").

## Long-term (90 days)

- [ ] **Policy learning**. Every time the user approves or rejects an
  approval row, feed it back into a per-domain preference so auto_send
  windows adapt.
- [ ] **Calibrated boldness**. Expose a single slider in v2 Settings
  that remaps every domain's mode + cap in one place; the twin's
  current "boldness" is audited into the supervisor log.
- [ ] **Twin handoff to a family member**. Support a "standby" mode
  where another paired device + user identity can approve on your
  behalf during travel.
