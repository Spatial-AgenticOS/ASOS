# Billing and CI — Triage

Short guide for when GitHub Actions refuses to start a job with:

> The job was not started because recent account payments have failed
> or your spending limit needs to be increased. Please check the
> 'Billing & plans' section in your settings.

This message has three distinct root causes. The first job in a CI
run fails before anything else prints, so the symptom is always a
red workflow within a few seconds of push. Check all three in order.

## 1. A past payment actually failed

- Open https://github.com/settings/billing.
- If there is a red banner that says "Your last payment failed",
  update the card on file and explicitly retry the unpaid invoice.
- Adding a new valid card does **not** retroactively settle a past
  failure — the old unpaid balance can keep blocking new jobs until
  GitHub marks the invoice paid.

## 2. A spending limit (or "budget") is exhausted

- Same page, click "Budgets and alerts".
- Any budget with "Stop usage when budget limit is reached" enabled
  and exhausted blocks runs until the next billing cycle OR until
  the ceiling is raised.
- FERAL-AI is an organization repo, so the binding budget is almost
  always at **organization** level, not personal. Visit
  https://github.com/organizations/FERAL-AI/billing and raise or
  remove the org-level Actions budget.
- A common false trail: you raise your personal limit, the error
  keeps happening, you conclude GitHub is broken. The real culprit
  is the org budget that has priority.

## 3. An org-level admin block

- Only an org admin can see and edit the org's Actions budget.
- If you are a collaborator but not an org admin, the error will
  persist regardless of what you do in your personal billing page.
- Ask the org admin to visit the org billing page above.

## Reducing future runner-minute burn

Once billing is unblocked, prune workflows that trigger for no
payoff. Two were trimmed in 2026.4.18-dev:

- [`.github/workflows/desktop.yml`](../.github/workflows/desktop.yml)
  — removed the `pull_request: paths: ['desktop/**']` trigger until
  Apple Developer ID + Windows Authenticode + Tauri updater certs
  land in repo secrets. Desktop builds are `workflow_dispatch`-only
  for now.
- [`.github/workflows/provider-research.yml`](../.github/workflows/provider-research.yml)
  — removed the daily `schedule: 0 9 * * *` cron until the first
  Track A live-credential provider lands. With all four new
  providers at stub level, the poll was burning ~30 runner-min/month
  for no catalog delta.

Re-enable each trigger the day its gating prerequisite is met; both
files carry an inline comment pointing at the reactivation condition.

## Dependabot hygiene

See [`.github/dependabot.yml`](../.github/dependabot.yml). Every npm
+ pip + github-actions update is batched **weekly** (Mondays) with
minor/patch bumps grouped into a single PR per package. That
collapses roughly 7× the CI runs a daily schedule would fire, at
the cost of a one-week latency on non-security bumps.

Critical / High security advisories still open immediately per
Dependabot's default behaviour — the schedule only applies to
routine version bumps.

## Local test parity

Brain, two SDKs, daemons, v2 client all run offline in the local
dev environment. When Actions is billing-blocked, the
`pre-push-checklist` in this doc below is the local substitute for
a green CI signal.

### pre-push-checklist

```bash
cd feral-core && python -m pytest -q
cd ../feral-nodes/python-node-sdk && python -m pytest -q
cd ../wristband_daemon && python -m pytest tests -m 'not live' -q
cd ../theora_glasses_daemon && python -m pytest tests -m 'not live' -q
cd ../../feral-registry && python -m pytest -q
cd ../feral-client-v2 && npx vitest run
cd ../feral-client && npx vitest run --coverage
cd ../feral-nodes/ts-node-sdk && npx tsc --noEmit
```

All seven steps must exit 0 before a push. CI will verify the same
once billing is restored.
