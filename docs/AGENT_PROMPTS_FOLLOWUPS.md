# Agent Prompts — Follow-ups

A running ledger of out-of-scope issues that workers spotted while completing
their assigned workstream. The Conductor (see `docs/AGENT_PROMPTS.md` §G) reads
this file at every sweep and either dispatches a new W## or rolls the change
into an existing one.

Format per row:

```
- YYYY-MM-DD · WID · path:line · one-line user-impact · proposed handler
```

## Open

- 2026-04-24 · W2 · `feral-client-v2/src/pages/Settings.jsx:~1525` · The Twin
  section's "Connect" button (and any future cross-section CTA inside a
  settings panel) currently has to walk the DOM (`querySelectorAll('.v2-settings-btn')`)
  to switch the parent's active section, because the W2 ownership window
  (lines 1443–1654) does not cover the parent `Settings()` component
  (lines 23–63) where `setSection` is defined. Lifting `setSection` (or a
  `navigateToSection` callback) into a prop on every section component
  would let CTAs become a clean `props.onChangeSection('Channels')` call,
  avoid a brittle DOM hop in tests/SSR, and unblock similar cross-links
  from Twin → Channels, Memory → Sync, Voice → Providers, etc. Proposed
  handler: a small refactor in a new W16 (UI plumbing), or rolled into
  the next W14 (v2 e2e + a11y) sweep since it also helps `aria` flows.
