# Security Policy

If you believe you've found a security issue in FERAL, please report it
privately to the maintainers before disclosing publicly. FERAL is a
single-trusted-operator, local-first AI agent — the threat model is
small and explicit, and the bar for what counts as a vulnerability is
shaped by that model.

## What FERAL is

FERAL is a personal-assistant brain that runs on the operator's
machine. There is exactly **one** trusted operator per running brain.
The operator owns the host, owns the credential vault, owns every
paired device, and owns every tool the brain may invoke. FERAL's
security boundaries protect this operator from external prompt
injection, from adversarial channel ingress, from sandbox escape by
tool-genesis-generated code, and from supervisor or twin policy
bypass — they are **not** designed to keep the operator from acting
against their own machine.

## In Scope

The following are vulnerabilities in the brain itself and are in scope:

- **Remote code execution (RCE)** in the brain process from any
  externally reachable surface (HTTP API, `/v1/node` WebSocket, a
  channel adapter ingress, the GenUI iframe, an MCP request).
- **Credential theft / vault exfiltration** — anything that lets an
  external party read `~/.feral/credentials.enc`, the vault master key,
  or paired-device tokens. Cite W9: the vault is encrypted at rest with
  ChaCha20-Poly1305 and pairing tokens are Argon2id-hashed.
- **Sandbox escape** — code running inside the W22 sandbox image
  (`Dockerfile.sandbox` or `Dockerfile.sandbox-browser`) reaching the
  host filesystem, host network namespace, host PID namespace, or
  another container.
- **Supervisor bypass** — any path that lets an action reach an
  orchestrator entry point (`handle_command`, `handle_command_stream`,
  `handle_ui_event`, `handle_daemon_result`) without the audited
  Supervisor wrapper, or that lets a paused brain still execute.
- **Vault tampering** — undetected modification of the encrypted vault
  blob. The AEAD tag must catch this; `VaultTamperedError` must be
  raised.
- **Channel adapter abuse against the operator** — a malicious payload
  on Slack / iMessage / Telegram / email that crosses an auth,
  allowlist, approval, or sandbox boundary and acts on the operator's
  behalf.
- **Twin / executor approval bypass** — calling a registered
  `TwinExecutor` or a high-risk MCP tool without the per-domain or
  per-tool consent record (`agents.twin_policy.TwinPolicyEngine`,
  `security.exec_approvals.ApprovalManager`).
- **Subagent allowlist bypass** — invoking
  `agents.subagent_spawner.spawn_subsession(parent_id, child_kind, …)`
  with a `child_kind` that is not in `agents.subagent_policy`'s default
  allowlist (or operator-supplied override) and reaching the runner.

## Out of Scope

The following are **not** vulnerabilities and reports about them will
typically be closed as `invalid` / `no-action`:

- Issues the operator can introduce by acting on their own machine —
  e.g. compromised host OS, compromised browser profile, malware the
  operator installed under the same OS user as the brain.
- A FERAL skill, channel adapter, or tool-genesis-installed package
  that the operator authored or installed themselves performing
  privileged actions. Skills are part of the operator's trusted
  computing base; see "Plugin trust boundary" below.
- Credentials stored *outside* the FERAL vault by the operator
  (`OPENAI_API_KEY` exported in the operator's shell, secrets in
  `~/.config/something-else.json`, plaintext keys in `.env` files
  the operator chose to keep around).
- "The operator can shut down the brain" / "the operator can revoke a
  paired device" / "the operator can edit `MEMORY.md`" — these are
  intentional operator-control surfaces, not bugs.
- Prompt-injection-only chains where no auth, policy, approval, or
  sandbox boundary is crossed. The model is **not** a trusted
  principal; defenses come from boundaries, not from the model.
- Reports against the demo / scenarios fixtures, dev tooling under
  `dev/`, or test harnesses under `feral-core/tests/`.
- Reports requiring write access to `~/.feral/`. Anyone who can write
  there is already a trusted operator.
- Reports that depend on a multi-tenant deployment where mutually
  untrusted users share one brain instance. FERAL is not designed for
  that and does not try to provide per-user isolation.
- Heuristic / parity drift between exec surfaces (e.g. a deny rule
  applied to one surface but not another) that does **not** demonstrate
  a concrete bypass of an in-scope boundary.
- Reports that depend on the operator setting `FERAL_AUTONOMY_MODE=loose`
  or a similar break-glass flag. Those are explicit operator-selected
  trade-offs.

## Threat model — single-trusted-operator boundary

FERAL runs on **one** machine for **one** operator. That operator's OS
account is FERAL's trust boundary; everything inside it is trusted,
everything outside it is untrusted (and crosses one of the documented
ingress paths: `/v1/node`, HTTP API, WebSocket, channel adapter, MCP).
The primary defenses against the in-scope risks are:

1. **W8 sandboxing** — tool-genesis code, GenUI app code, and W17
   subagent worker code execute inside `Dockerfile.sandbox` /
   `Dockerfile.sandbox-browser` containers with `--cap-drop=ALL
   --network=none --read-only` plus a watchdog. Dropped capabilities,
   no network, no host filesystem mount, non-root `feral` user.
2. **W9 vault encryption + token hashing** — credentials live in
   `~/.feral/credentials.enc` (ChaCha20-Poly1305, master key in the
   OS keychain, recovery code shown once at first boot). Pairing
   tokens are Argon2id-hashed; legacy plaintext rows are migrated to
   `needs_rotation_log` on first boot.
3. **Supervisor audit + kill switch** — every orchestrator entry point
   is wrapped (`agents.supervisor.Supervisor`); every call is recorded
   to `supervisor.db` with `decision=allowed/denied/queued/error`; a
   single `set_paused(True)` blocks every dispatch.
4. **Per-tool / per-domain approvals** —
   `security.exec_approvals.ApprovalManager` for high-risk tools and
   `agents.twin_policy.TwinPolicyEngine` for twin domains. Both are
   default-deny without an explicit consent record; per-session grants
   never promote across sessions.
5. **Subagent allowlist (W17)** — `agents.subagent_policy.is_allowed`
   is default-deny; the orchestrator can spawn only the small set of
   child kinds in `_DEFAULT_ALLOWLIST`. Denials are audited via
   `supervisor.record(kind="subagent_spawn", decision="denied")`.

The W22 approval-bypass test family
(`feral-core/tests/security/test_*_approval_bypass.py`) demonstrates
that each of these boundaries holds against an attempted bypass — not
just that the API returns 403, but that the bypassed call never reaches
the underlying side effect AND the supervisor sees a denial event.

## Reporting

Email **security@feral.sh** with reproduction steps, affected
component(s), and a clear impact statement. A PGP key fingerprint will
be published in this section by the maintainer; until then, reports
that need to ship sensitive payloads should request the public key in
a first contact email.

Required in reports:

1. Title and severity assessment.
2. Affected component (file path + commit SHA you tested against).
3. Reproduction steps that work against the current `main`.
4. Demonstrated impact tied to one of the in-scope categories above.
5. Suggested remediation, if any.

Reports without reproduction steps or demonstrated impact will be
deprioritized.

### Fast-path triage gate

Reports that demonstrate any of the following are triaged at **HIGH**
within one business day:

- [ ] Credential exfiltration — vault, OS-keychain master key, pairing
      tokens, channel adapter API keys, or any vault-backed secret.
- [ ] Sandbox escape — code in `Dockerfile.sandbox` or
      `Dockerfile.sandbox-browser` reaching the host filesystem,
      host network namespace, or host PID namespace.
- [ ] Supervisor bypass — an action reaching an orchestrator entry
      point without audit, or executing while the supervisor is
      `paused=True`.

Everything else is triaged at **NORMAL** (target: one week to first
substantive response).

## Common false-positive patterns

The following report shapes are commonly filed but are **not**
vulnerabilities under FERAL's trust model:

- "The operator can shutdown the brain by killing the process." —
  intentional, the operator is trusted.
- "I configured `FERAL_AUTONOMY_MODE=loose` and the brain executed a
  dangerous tool without prompting." — operator-selected break-glass.
- "The brain ran a skill the operator installed and that skill made
  HTTP requests / wrote to the filesystem / read the vault." — skills
  are trusted plugins.
- "An LLM with prompt injection produced text that references the
  operator's email address." — the LLM is not a trusted principal;
  context visibility is not, by itself, an authorization boundary.
- "I sent a malicious string in a channel and the model `replied` to
  it." — out of scope unless the reply crosses a tool, approval, or
  sandbox boundary.
- "I can `docker exec` into the brain container as root." — that
  requires root on the host, which already collapses the operator
  boundary.
- "I supplied a custom regex in `~/.feral/config.yaml` that
  catastrophically backtracks." — operator-supplied configuration;
  hardening at best, not a security boundary bypass.
- "The HTTP API accepts requests from `127.0.0.1` without an auth
  header." — local loopback is the trusted-operator surface; bind to
  loopback only and rely on OS user isolation.

## Plugin trust boundary

Skills, channel adapters, and tool-genesis-installed packages are part
of the operator's trusted computing base. Once installed, they run
in-process with the brain and have the brain's OS privileges. Reports
that show a malicious operator-installed plugin doing privileged things
are out of scope. Reports that show an *unauthenticated* path that lets
a remote party install or invoke a plugin **are** in scope.

## Sandbox image hygiene

The two shipped sandbox images (built from `Dockerfile.sandbox` and
`Dockerfile.sandbox-browser`, both `FROM` `Dockerfile.sandbox-common`)
are versioned via
`feral-core/security/sandbox_image.SANDBOX_IMAGE_VERSION`, which
embeds a sha256 of the three Dockerfile contents. Any change to those
files changes the image tag — the launcher in
`feral-core/security/docker_sandbox.py` will only run the image whose
tag matches the brain's pinned `SANDBOX_IMAGE_VERSION`, so a partial
upgrade can never produce a brain talking to a stale sandbox recipe.

References:

- `docs/OPENCLAW_LESSONS.md` §6 — sandboxing + security audit.
- `docs/OPENCLAW_LESSONS.md` §10 W22 — this workstream's mission.
