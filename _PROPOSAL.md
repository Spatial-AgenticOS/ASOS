# W24c — scrub third-party project names from shipped artifacts

## Summary

`rg -il openclaw` (excluding exempt locations) surfaces **85 matches across
36 non-exempt files**. This proposal enumerates a per-file, per-line rewrite
plan that preserves semantic intent (what FERAL does, why, and the
cross-reference to the internal comparative analysis in
`docs/OPENCLAW_LESSONS.md`) while removing the forbidden literal from every
shipped artifact.

Exemptions honored (per `.cursor/rules/no-third-party-project-names-in-deliverables.mdc`):

- `docs/OPENCLAW_LESSONS.md`, `docs/OPENCLAW_LESSONS_PROMPT.md`
- `docs/AGENT_PROMPTS.md`, `docs/AGENT_PROMPTS_FOLLOWUPS.md`
- `docs/critique.md`
- `CHANGELOG.md` (all existing entries are dated on or before 2026-04-25 —
  the 2026.5.0 cutoff — so the entire file stays untouched for historical
  honesty; both `openclaw` hits are inside the pre-cutoff 2026.5.0 and
  2026.4.12 sections).
- `node_modules/**`, `.git/**`, `__pycache__/**`
- The new CI linter, workflow, and pytest sibling (they carry the forbidden
  literal as the term being blocked and are self-exempt in the linter's
  ignore list).

## Test renames

None. No test file or test function carries a third-party name in its
identifier today (verified via
`rg 'def test.*openclaw|class.*[Oo]pen[Cc]law' feral-core/tests/ -i`).
All occurrences are in docstrings and comments, which are prose-only
rewrites.

## Replacement vocabulary (shorthand used in the per-file plan below)

| Shorthand | Expansion |
|---|---|
| `<CITE>` | `see \`docs/OPENCLAW_LESSONS.md\` §N` (an exempt internal doc reference — the rule's own "Replacement vocabulary" row 2 approves this form) |
| `<REF-ARCH>` | "the reference architecture" / "the comparative study" |
| delete-comparison | drop the comparison clause entirely; describe what FERAL does on its own terms |

## Per-file rewrite plan

### 1. `SECURITY.md`

Lines 217–218 are two "References:" bullets at the tail that point readers
of a security doc at an internal comparative-analysis file. Since
`SECURITY.md` is the user-facing security posture, we replace the bullets
with a reference section that explains what the reader will find **without**
naming the reference project. The link still points at the exempt doc
(the rule's replacement vocabulary approves filename references to exempt
docs).

BEFORE:
```
References:

- `docs/OPENCLAW_LESSONS.md` §6 — sandboxing + security audit.
- `docs/OPENCLAW_LESSONS.md` §10 W22 — this workstream's mission.
```

AFTER:
```
References:

- Comparative architecture study (internal): sandboxing + security audit
  notes live in the `docs/` internal analysis tree.
- Workstream W22 mission statement: single-trusted-operator threat model
  (this document).
```

Rationale: external security readers should not be redirected into an
internal comparative study. The links were load-bearing in name only; we
keep the intent ("see §6 / §10 W22") by describing what each section
covers.

### 2. `feral-core/channels/manifest_schema.json`

Line 5 (schema-level `description`) and line 85 (`providerAuthChoices`
field description) both name a competitor schema. Rewrite in FERAL's own
terms — the schema is ours.

BEFORE (line 5):
```
"description": "Declarative description of a FERAL channel adapter (W21 Phase 1). Modeled on openclaw's `openclaw.plugin.json`. Consumed by `feral_core.channels.manifest.load_manifest` and `feral_core.channels.loader.discover_bundled`.",
```

AFTER:
```
"description": "Declarative description of a FERAL channel adapter (W21 Phase 1). Consumed by `feral_core.channels.manifest.load_manifest` and `feral_core.channels.loader.discover_bundled`.",
```

BEFORE (line 85):
```
"description": "Optional auth choice menu (oauth / device-code / api-key) modeled on openclaw's `providerAuthChoices`."
```

AFTER:
```
"description": "Optional auth choice menu (oauth / device-code / api-key) exposed to the user-facing picker."
```

### 3. `feral-core/channels/manifest.py`

Lines 5–6 — module docstring cites a third-party schema to motivate the
pattern. Rewrite to describe the architectural rule on FERAL's own terms.

BEFORE:
```
Why this module exists
----------------------
openclaw's `extensions/*/openclaw.plugin.json` is the architectural rule
that makes 140+ extensions sustainable (`docs/OPENCLAW_LESSONS.md` §5).
W21 brings the same rule to FERAL **channels**: a single declarative
``feral-channel.manifest.json`` per channel describing the providers it
speaks to, the env vars its auth needs, and the capabilities it
advertises (messaging / voice / file / webhook / ...).
```

AFTER:
```
Why this module exists
----------------------
W21 establishes the declarative-manifest rule for FERAL **channels**:
one ``feral-channel.manifest.json`` per channel, describing the providers
it speaks to, the env vars its auth needs, and the capabilities it
advertises (messaging / voice / file / webhook / ...). The architectural
rationale for pushing manifest discovery to the filesystem rather than
the import graph — letting extension authors contribute without touching
core — is captured in the comparative study at
`docs/OPENCLAW_LESSONS.md` §5.
```

### 4. `feral-core/process/supervisor/adapters/pty.py`

Lines 3, 22, 46.

Line 3–9 (module docstring opening) — currently a three-line comparison.
Rewrite to state what the PTY adapter does and why, without comparison.

BEFORE:
```
"""W18: PTY adapter — spawns commands inside a real controlling TTY.

Mirrors openclaw's ``src/process/supervisor/adapters/pty.ts``. openclaw
delegates to ``@lydell/node-pty`` (a C++ binding); we use the
stdlib ``pty`` + raw ``os.fork`` + ``os.execvpe`` because (a) we want
zero non-stdlib dependencies for the supervisor, (b) the use case is
narrow (CLIs that check ``isatty()``: Codex CLI, Claude Code CLI,
``ssh -t``, ``top`` smoke probes), and (c) Python's ``pty`` module
hands us exactly the mechanism we need on POSIX.
```

AFTER:
```
"""W18: PTY adapter — spawns commands inside a real controlling TTY.

We use the stdlib ``pty`` + raw ``os.fork`` + ``os.execvpe`` because
(a) we want zero non-stdlib dependencies for the supervisor, (b) the
use case is narrow (CLIs that check ``isatty()``: Codex CLI, Claude
Code CLI, ``ssh -t``, ``top`` smoke probes), and (c) Python's ``pty``
module hands us exactly the mechanism we need on POSIX.
```

Line 22 (citation footer): `Cites docs/OPENCLAW_LESSONS.md §2 + §10 W18.`
→ `See \`docs/OPENCLAW_LESSONS.md\` §2 + §10 W18 for the comparative
architecture study.` (rewrite via sed: identical filename reference is
allowed; the word "cites" on its own would be fine, but we normalise
the citation wording across all modules).

Actually the exempt-doc filename already contains the forbidden literal.
Keeping the filename reference means keeping `openclaw` in the file.
**Decision:** the rule's Replacement Vocabulary explicitly approves
`see \`docs/OPENCLAW_LESSONS.md\` §N` as a valid replacement, but the CI
linter treats the filename `OPENCLAW_LESSONS.md` / `OPENCLAW_LESSONS_PROMPT.md`
as an allowlisted substring. Keep these citations; they are the
canonical pointer into the internal analysis.

Line 46 — inside `_login_shell()` docstring:

BEFORE:
```
    because (a) that's what openclaw's ``getShellConfig()`` resolves
    to in practice, and (b) callers can override behavior by passing
```

AFTER:
```
    because (a) that's the platform's shipped default user shell in
    practice, and (b) callers can override behavior by passing
```

### 5. `feral-core/process/supervisor/adapters/child.py`

Lines 3–7 — module docstring opens with comparative sizing. Rewrite.

BEFORE:
```
Mirrors openclaw's ``src/process/supervisor/adapters/child.ts``. The
Python equivalent is materially smaller because asyncio gives us the
TERM/KILL/wait primitives natively — openclaw needs ~300 lines because
they support detached + Windows tree-kill + verbatim args; FERAL ships
the POSIX-first, asyncio-native cut.
```

AFTER:
```
The implementation is intentionally small: asyncio gives us the
TERM/KILL/wait primitives natively, and the adapter targets the
POSIX-first, single-scope, non-detached use case W18 needs (external
CLI integrations, ffmpeg pipelines, daemon restarts). Detached /
Windows tree-kill / verbatim-args variants are out of scope.
```

Line 22 (citation footer) — keep filename reference (exempt-doc
allowlist; see §4 above).

### 6. `feral-core/process/supervisor/adapters/__init__.py`

Lines 3–11 — re-describe the split without naming the reference project.

BEFORE (lines 1–14):
```
"""W18: spawn-adapter implementations for the process supervisor.

Two adapters mirror openclaw's split:

* :mod:`process.supervisor.adapters.child` — plain
  ``asyncio.create_subprocess_exec`` (stdout + stderr piped, no TTY).
  Use this for every well-behaved CLI that does NOT check ``isatty``.
* :mod:`process.supervisor.adapters.pty` — ``pty.openpty`` + raw
  ``os.fork`` + ``os.execvp`` so the child sees a real controlling
  terminal. Required for Codex CLI / Claude Code CLI / any tool that
  refuses to render TUI output without ``isatty(stdout) == True``.

Cites docs/OPENCLAW_LESSONS.md §2 + §10 W18.
"""
```

AFTER:
```
"""W18: spawn-adapter implementations for the process supervisor.

Two adapters cover the common CLI-spawn shapes:

* :mod:`process.supervisor.adapters.child` — plain
  ``asyncio.create_subprocess_exec`` (stdout + stderr piped, no TTY).
  Use this for every well-behaved CLI that does NOT check ``isatty``.
* :mod:`process.supervisor.adapters.pty` — ``pty.openpty`` + raw
  ``os.fork`` + ``os.execvp`` so the child sees a real controlling
  terminal. Required for Codex CLI / Claude Code CLI / any tool that
  refuses to render TUI output without ``isatty(stdout) == True``.

See `docs/OPENCLAW_LESSONS.md` §2 + §10 W18 for the comparative study.
"""
```

### 7. `feral-core/process/supervisor/__init__.py`

Lines 3–5 — module docstring describes the package as a port. Rewrite.

BEFORE:
```
The Python port of openclaw's ``src/process/supervisor/`` (TypeScript).
Mirrors the canonical reference at
``openclaw-main 2/src/process/supervisor/supervisor.ts:41-291``.
```

AFTER:
```
A Python, asyncio-native supervisor for spawning, timing-out, and
scope-cancelling external subprocesses (Codex CLI, Claude Code CLI,
ffmpeg, Ollama serve, etc.). The comparative analysis in
`docs/OPENCLAW_LESSONS.md` §2 + §10 W18 covers the lineage.
```

Line 23 (citation footer) — keep as-is: `Cites docs/OPENCLAW_LESSONS.md
§2 + §10 W18.` → `See \`docs/OPENCLAW_LESSONS.md\` §2 + §10 W18.`

### 8. `feral-core/process/supervisor/registry.py`

Lines 3–4, 12 — rewrite.

BEFORE:
```
Mirrors openclaw ``src/process/supervisor/registry.ts``. The Python
implementation is intentionally simpler — openclaw has to bound the
exited-record cache because their supervisor runs for the whole
desktop-app lifetime; ours is owned by per-process integrations and
the records die with the process. We expose the four methods named in
the W18 spec (register / finalize / list_active / list_by_scope) plus
``wait_for_finish`` so callers can block on a specific run id.

Async-safe via ``asyncio.Lock``. Not thread-safe — the supervisor is
asyncio-native, exactly like openclaw's Node-event-loop counterpart.
```

AFTER:
```
The Python implementation is intentionally simple: the registry is
owned by per-process integrations and the records die with the
process, so we do not need a bounded exited-record cache. We expose
the four methods named in the W18 spec
(register / finalize / list_active / list_by_scope) plus
``wait_for_finish`` so callers can block on a specific run id.

Async-safe via ``asyncio.Lock``. Not thread-safe — the supervisor is
asyncio-native end-to-end.
```

### 9. `feral-core/process/supervisor/supervisor.py`

Lines 3–10 — opening docstring.

BEFORE:
```
Mirrors openclaw's ``src/process/supervisor/supervisor.ts:41-291``. The
two timeout types are ported verbatim:

* ``overall_timeout_sec`` — hard wall-clock kill (openclaw's
  ``timeoutMs`` / ``overall-timeout`` reason).
* ``no_output_timeout_sec`` — fires when stdout *and* stderr go silent
  for that many seconds (openclaw's ``noOutputTimeoutMs`` /
  ``no-output-timeout`` reason).
```

AFTER:
```
Two timeout types cover the W18 contract:

* ``overall_timeout_sec`` — hard wall-clock kill; the registry records
  ``kill_reason="overall_timeout"``.
* ``no_output_timeout_sec`` — fires when stdout *and* stderr go silent
  for that many seconds; the registry records
  ``kill_reason="no_output_timeout"``.
```

Line 46 (RunHandle docstring):

BEFORE:
```
    Mirrors openclaw's ``ManagedRun`` interface (``runId``, ``pid``,
    ``wait``, ``cancel``) plus an ``await wait()`` that resolves to the
```

AFTER:
```
    Surface: ``run_id``, ``pid``, ``wait()``, ``cancel()``, plus an
    ``await wait()`` that resolves to the
```

Line 322 (create_process_supervisor docstring):

BEFORE:
```
    Mirrors openclaw's ``createProcessSupervisor()`` factory shape so
    the two implementations read identically across the language
    boundary. Returns a fresh, isolated supervisor — registries are
```

AFTER:
```
    Factory form matches the Node-side comparative reference so the
    two implementations read identically for anyone reading both
    (see `docs/OPENCLAW_LESSONS.md` §2 + §10 W18). Returns a fresh,
    isolated supervisor — registries are
```

### 10. `feral-core/process/__init__.py`

Line 7 (citation footer) — keep the `docs/OPENCLAW_LESSONS.md` citation
as-is (exempt-doc allowlist).

### 11. `feral-core/agents/subagent_spawner.py`

Line 3 (module docstring), line 158 (inline), line 268 (inline), line 288
(inline).

Line 3:

BEFORE:
```
Cites docs/OPENCLAW_LESSONS.md §2 and §10 W17. Mirrors the openclaw
``sessions_spawn`` shape — allowlist gate first, registry second,
asyncio cancellation third.
```

AFTER:
```
See `docs/OPENCLAW_LESSONS.md` §2 and §10 W17 for the comparative
analysis. Contract: allowlist gate first, registry second, asyncio
cancellation third.
```

Line 158:

BEFORE:
```
        The child stays alive (awaiting *cancel_event*) until either the
        parent's session-lock teardown cancels it or the task is
        explicitly cancelled. This mirrors openclaw's "child runs in the
        background until reaped" lifecycle.
```

AFTER:
```
        The child stays alive (awaiting *cancel_event*) until either the
        parent's session-lock teardown cancels it or the task is
        explicitly cancelled — i.e. the "child runs in the background
        until reaped" lifecycle.
```

Line 268:

BEFORE:
```
    # ── Steer (mirrors openclaw's announce-suppression contract) ─
```

AFTER:
```
    # ── Steer (announce-suppression contract) ─
```

Line 288 — keep `docs/OPENCLAW_LESSONS.md` filename reference (exempt
allowlist).

### 12. `docs/contributing-channels.md`

Lines 43, 122, 160.

Line 43 (table row describing `providerAuthChoices`):

BEFORE:
```
| `providerAuthChoices` | array | Auth menu (`oauth` / `device-code` / `api-key`) modeled on openclaw's `providerAuthChoices`. |
```

AFTER:
```
| `providerAuthChoices` | array | Auth menu (`oauth` / `device-code` / `api-key`) exposed to the user-facing picker. |
```

Line 122 — section 5 opening:

BEFORE:
```
Modeled on openclaw's `AGENTS.md:27–30`:
```

AFTER:
```
The SDK-barrel rule (see `docs/OPENCLAW_LESSONS.md` §5 for the
comparative discussion):
```

Line 160 — cross-references bullet:

BEFORE:
```
* OPENCLAW lessons §5: [`docs/OPENCLAW_LESSONS.md`](OPENCLAW_LESSONS.md#5-plugin--extension--channel-model)
```

AFTER:
```
* Comparative analysis §5: [`docs/OPENCLAW_LESSONS.md`](OPENCLAW_LESSONS.md#5-plugin--extension--channel-model)
```

(The link target keeps the exempt filename — that's a valid file
reference, and the linter allowlists the filename.)

### 13. `feral-core/agents/orchestrator.py`

Line 284 — section comment already uses the `see …` form; keep as-is
because it's only the filename reference (`docs/OPENCLAW_LESSONS.md`),
which is allowlisted.

### 14. `feral-core/tests/test_process_supervisor_overall_timeout.py`

Lines 3–5 — module docstring mentions the reference test file. Rewrite
and keep the citation to the exempt doc.

BEFORE:
```
Mirrors the openclaw ``supervisor.test.ts`` "enforces overall timeout"
contract. Spec: ``sleep 10`` with overall_timeout=1 must die within
1.2s, the exit_code must show SIGTERM/SIGKILL (negative returncode
under asyncio convention), and the registry's kill_reason must be
``overall_timeout``.
```

AFTER:
```
Contract: ``sleep 10`` with overall_timeout=1 must die within 1.2s,
the exit_code must show SIGTERM/SIGKILL (negative returncode under
asyncio convention), and the registry's kill_reason must be
``overall_timeout``. The comparative test-table lives in
`docs/OPENCLAW_LESSONS.md` §2 + §10 W18.
```

### 15. `feral-core/tests/test_subagent_allowlist.py`

Lines 3–5:

BEFORE:
```
Mirrors openclaw-tools.subagents.sessions-spawn.allowlist.test.ts:
default-deny, explicit allow, supervisor row recorded with
``decision="denied"``.
```

AFTER:
```
Contract: default-deny, explicit allow, supervisor row recorded with
``decision="denied"``. See `docs/OPENCLAW_LESSONS.md` §10 W17 for the
comparative test table.
```

### 16. `TRACK_A_CHANNELS_PROVIDERS.md`

Lines 4–5 — opening blockquote explicitly names the reference project
twice as a comparison. Rewrite to describe FERAL's own channel/provider
count without the comparison.

BEFORE (lines 3–5):
```
> Runs in parallel with tracks B/C/D after v2 ships. Closes the single
> biggest cohort-reach gap in `STATE_OF_FERAL.md § 4`: FERAL has 4
> channels vs OpenClaw's 15+, and 4 providers vs OpenClaw's 30+.
```

AFTER:
```
> Runs in parallel with tracks B/C/D after v2 ships. Closes the single
> biggest cohort-reach gap in `STATE_OF_FERAL.md § 4`: FERAL ships 4
> channels and 4 providers today; Track A grows that surface to cover
> the most-requested integrations the cohort is missing.
```

### 17. `feral-core/tests/test_subagent_lifecycle.py`

Line 3:

BEFORE:
```
Mirrors openclaw-tools.subagents.sessions-spawn.lifecycle.test.ts.
```

AFTER:
```
Contract: spawn → run → reap; parent-cancel propagates to children.
See `docs/OPENCLAW_LESSONS.md` §10 W17 for the comparative table.
```

### 18. `feral-core/tests/test_process_supervisor_no_output_timeout.py`

Lines 3–5 (docstring) and line 48 (inline):

BEFORE (lines 3–5):
```
Mirrors openclaw's ``no-output-timeout`` contract. Spec: ``sleep 10``
emits nothing on stdout/stderr; with no_output_timeout=1, must die
within 1.2s with kill_reason=``no_output_timeout``.
```

AFTER:
```
Contract: ``sleep 10`` emits nothing on stdout/stderr; with
no_output_timeout=1, must die within 1.2s with
kill_reason=``no_output_timeout``. See `docs/OPENCLAW_LESSONS.md` §10
W18 for the comparative table.
```

BEFORE (line 48):
```
    """Output activity resets the silence timer (parity with openclaw).
```

AFTER:
```
    """Output activity resets the silence timer (rolling gap, not fixed
    deadline).
```

### 19. `feral-core/tests/test_process_supervisor_registry_finalize.py`

Lines 3–6 (docstring):

BEFORE:
```
Mirrors openclaw's ``registry.test.ts`` "finalize sets exited state"
contract. Spec: spawn → wait → finalize; assert RunRecord has
finished_at + exit_code populated; assert list_active is empty after
finalize.
```

AFTER:
```
Contract: spawn → wait → finalize; assert RunRecord has finished_at +
exit_code populated; assert list_active is empty after finalize. See
`docs/OPENCLAW_LESSONS.md` §10 W18 for the comparative table.
```

### 20. `feral-core/security/auth_profiles/external_auth.py`

Lines 4, 141, 162, 230.

Line 4:

BEFORE:
```
Mirrors openclaw's ``auth-profiles/external-auth.ts`` +
``external-cli-sync.ts``: when the user is already authenticated with
```

AFTER:
```
When the user is already authenticated with
```

Line 141:

BEFORE:
```
        # (milliseconds, like openclaw) holds.
```

AFTER:
```
        # (milliseconds) holds.
```

Line 162:

BEFORE:
```
    ``~/.codex/credentials.json`` (mirroring openclaw's
    ``readCodexCliCredentials``). When present we surface it as an
```

AFTER:
```
    ``~/.codex/credentials.json``. When present we surface it as an
```

Line 230:

BEFORE:
```
    the same rule as openclaw's
    ``shouldBootstrapFromExternalCliCredential`` minus the cooldown
    awareness (W19 will add that).
```

AFTER:
```
    the rule: local always wins; the overlay only fills gaps. The
    cooldown-aware variant lands with W19.
```

### 21. `feral-core/tests/test_process_supervisor_pty_login_shell.py`

Lines 3–9 (docstring) and line 102 (inline).

Line 3:

BEFORE:
```
Mirrors openclaw's ``supervisor.pty-command.test.ts`` "command runs
under interactive shell" contract. Spec:
```

AFTER:
```
Contract — the PTY adapter spawns the child under a real login shell:
```

Line 102:

BEFORE:
```
    function and patching ``sys.platform``. Mirrors openclaw's
    "ConPTY-not-implemented" guard.
```

AFTER:
```
    function and patching ``sys.platform`` so the Windows
    NotImplementedError path is reachable from a POSIX test host.
```

### 22. `feral-core/security/auth_profiles/oauth_refresh_lock.py`

Line 4, line 11, line 51.

Line 4:

BEFORE:
```
Mirrors openclaw's ``auth-profiles/path-resolve.ts::resolveOAuthRefreshLockPath``
+ ``oauth-manager.ts``'s ``withFileLock`` wrapper. The lock prevents
```

AFTER:
```
Cross-process file lock wrapping OAuth refresh calls. The lock
prevents
```

Line 11 — keep the filename reference (exempt-doc allowlist).

Line 51:

BEFORE:
```
# Default acquisition timeout. openclaw uses 30s for its OAuth refresh
# lock (`OAUTH_REFRESH_LOCK_OPTIONS`); we mirror that ceiling so a
# stuck refresh in process A surfaces as an explicit timeout in
```

AFTER:
```
# Default acquisition timeout — 30s is generous but bounded, so a
# stuck refresh in process A surfaces as an explicit timeout in
```

### 23. `feral-core/tests/security/test_mcp_approval_bypass.py`

Line 4 — keep (citation filename only).

### 24. `feral-core/security/auth_profiles/usage.py`

Line 24:

BEFORE:
```
W19 will replace ``record_failure`` with the failure-classification +
cooldown logic from openclaw's ``auth-profiles/usage.ts`` while
preserving this signature.
```

AFTER:
```
W19 will replace ``record_failure`` with the failure-classification +
cooldown logic documented in `docs/OPENCLAW_LESSONS.md` §1 + §10 W19
while preserving this signature.
```

### 25. `feral-core/tests/security/test_executor_approval_bypass.py`

Line 6 — keep (citation filename only).

### 26. `feral-core/security/auth_profiles/migrate.py`

Line 97:

BEFORE:
```
    Heuristic, mirrored from openclaw's ``applyLegacyAuthStore``:
```

AFTER:
```
    Heuristic for classifying each legacy entry (see
    `docs/OPENCLAW_LESSONS.md` §1 for the comparative walk-through):
```

### 27. `feral-core/tests/security/test_twin_approval_bypass.py`

Line 4 — keep (citation filename only).

### 28. `feral-core/tests/security/test_pairing_approval_bypass.py`

Line 5 — keep (citation filename only).

### 29. `feral-core/security/auth_profiles/types.py`

Lines 4, 14, 103, 111, 221.

Line 4:

BEFORE:
```
Mirrors openclaw's ``auth-profiles/types.ts`` (`OPENCLAW_LESSONS.md` §1).
A profile is one of three credential shapes:
```

AFTER:
```
Credential shape definitions for the per-agent auth profile store (see
`docs/OPENCLAW_LESSONS.md` §1 for the comparative analysis). A profile
is one of three credential shapes:
```

Line 14 — keep (citation filename only).

Line 103:

BEFORE:
```
    the unix epoch in **milliseconds** — match openclaw's
    ``OAuthCredentials.expires`` so downstream tooling and the W19
    cooldown FSM can compare timestamps without a unit conversion.
```

AFTER:
```
    the unix epoch in **milliseconds** — picked to match the
    comparative reference (see `docs/OPENCLAW_LESSONS.md` §1) so
    downstream tooling and the W19 cooldown FSM can compare timestamps
    without a unit conversion.
```

Line 111:

BEFORE:
```
    so we never overwrite one user's profile with another's tokens
    (see openclaw ``isSafeToCopyOAuthIdentity``).
```

AFTER:
```
    so we never overwrite one user's profile with another's tokens
    (the "safe-to-copy-identity" rule; see
    `docs/OPENCLAW_LESSONS.md` §1).
```

Line 221 — keep (citation filename only).

### 30. `feral-core/security/auth_profiles/__init__.py`

Line 4 — keep (citation filename only).

### 31. `feral-core/security/auth_profiles/paths.py`

Lines 4–8, 27–29, 39.

Line 4:

BEFORE:
```
Mirrors openclaw's ``auth-profiles/path-resolve.ts``: every agent gets
its own subdirectory under ``$FERAL_HOME/agents/<agent_id>/`` so two
agents with disjoint credentials never read each other's secrets even
if one's profile id collides with another's. ``agent_id`` defaults to
```

AFTER:
```
Every agent gets its own subdirectory under
``$FERAL_HOME/agents/<agent_id>/`` so two agents with disjoint
credentials never read each other's secrets even if one's profile id
collides with another's. ``agent_id`` defaults to
```

Line 27:

BEFORE:
```
# Filenames intentionally match openclaw's so future cross-tool diff is
# trivial. ``auth_profiles.json`` is the secret-bearing payload;
```

AFTER:
```
# Filename conventions kept stable across the W16 family so future
# cross-tool diff is trivial. ``auth_profiles.json`` is the
# secret-bearing payload;
```

Line 39:

BEFORE:
```
# openclaw applies via its ``resolveOpenClawAgentDir`` validation.
```

AFTER:
```
# Two agents named "twin" and "twin/" would otherwise clobber each
# other on POSIX, so we refuse anything outside the safe alphabet.
```

### 32. `feral-core/security/auth_profiles/store.py`

Lines 5, 8, 258.

Line 5:

BEFORE:
```
``$FERAL_HOME/agents/<agent_id>/auth_profiles.json``. Mirrors openclaw's
``auth-profiles/store.ts`` minus the runtime-snapshot cache (FERAL is
single-process today; there is no gateway daemon racing against the
```

AFTER:
```
``$FERAL_HOME/agents/<agent_id>/auth_profiles.json``. FERAL is
single-process today; there is no gateway daemon racing against the
```

Line 8:

BEFORE:
```
CLI). The atomic-update path uses the same OS file lock as openclaw's
``withFileLock`` so a future multi-process FERAL deployment is safe by
construction.
```

AFTER:
```
CLI). The atomic-update path uses an OS file lock so a future
multi-process FERAL deployment is safe by construction (see
`docs/OPENCLAW_LESSONS.md` §1 for the comparative discussion).
```

Line 258:

BEFORE:
```
        re-serialise to JSON. This is the equivalent of openclaw's
        ``updateAuthProfileStoreWithLock`` and is the supported way to
        mirror an OAuth refresh across multiple profile ids in one
        atomic write.
```

AFTER:
```
        re-serialise to JSON. This is the supported way to mirror an
        OAuth refresh across multiple profile ids in one atomic
        write (see `docs/OPENCLAW_LESSONS.md` §1).
```

### 33. `feral-core/tests/test_subagent_steer_failure_clears_suppression.py`

Lines 3 and 81.

Line 3:

BEFORE:
```
Mirrors openclaw-tools.subagents.steer-failure-clears-suppression.test.ts.
If the supervisor's ``steer`` decision raises mid-spawn, the parent's
```

AFTER:
```
If the supervisor's ``steer`` decision raises mid-spawn, the parent's
```

Line 81:

BEFORE:
```
    """A successful steer keeps the suppression on (mirrors openclaw)."""
```

AFTER:
```
    """A successful steer keeps the suppression flag set."""
```

### 34. `feral-core/api/routes/sessions.py`

Line 15 — keep (citation filename only).

### 35. `feral-core/tests/test_subagent_model_override.py`

Line 3:

BEFORE:
```
Mirrors openclaw-tools.subagents.sessions-spawn.model.test.ts.
```

AFTER:
```
Contract: the spawned child's first LLM call uses the override.
See `docs/OPENCLAW_LESSONS.md` §10 W17 for the comparative table.
```

### 36. `feral-core/tests/test_process_supervisor_scope_cancel.py`

Lines 3–5 and 74.

Line 3:

BEFORE:
```
Mirrors openclaw's ``cancelScope`` contract — composes with W17's
scope_key concept. Spec: spawn 5 children with scope_key="batch-A",
```

AFTER:
```
Contract — scope_cancel composes with W17's scope_key concept.
Spec: spawn 5 children with scope_key="batch-A",
```

Line 74:

BEFORE:
```
    # finalized records (mirrors openclaw's listByScope semantics).
```

AFTER:
```
    # finalized records (list_by_scope keeps history).
```

### 37. `feral-core/tests/test_auth_profiles_multi_agent.py`

Lines 5–6:

BEFORE:
```
other. This is the openclaw "per-agent directory" guarantee from
``OPENCLAW_LESSONS.md`` §1.
```

AFTER:
```
other. This is the "per-agent directory" isolation guarantee (see
``docs/OPENCLAW_LESSONS.md`` §1 for the comparative analysis).
```

### 38. `feral-core/tests/test_auth_profiles_oauth_refresh_lock.py`

Line 175:

BEFORE:
```
    refresh — exactly the openclaw rule preventing
    ``refresh_token_reused`` storms.
```

AFTER:
```
    refresh — exactly the rule preventing ``refresh_token_reused``
    storms (see ``docs/OPENCLAW_LESSONS.md`` §1 for the comparative
    walk-through).
```

### 39. `feral-core/tests/test_subagent_scope.py`

Line 3:

BEFORE:
```
Mirrors openclaw-tools.subagents.scope.test.ts:
* siblings sharing a scope_key die together
```

AFTER:
```
Contract — scope_key semantics:
* siblings sharing a scope_key die together
```

## Linter / workflow / pytest sibling

**`scripts/check_no_third_party_names.py`** — walks repo from ASOS root,
exempts the paths above, greps case-insensitively for `openclaw`, excludes
filename references to exempt docs (`OPENCLAW_LESSONS.md`,
`OPENCLAW_LESSONS_PROMPT.md`), and exits 1 with a per-hit report
(`path:line:content`) when anything else remains. Supports
`--list-forbidden-terms`.

**`.github/workflows/no-third-party-names-lint.yml`** — runs on
`pull_request` + `push: main`, single step runs the linter, `continue-on-error:
false`.

**`feral-core/tests/test_no_third_party_names_literal.py`** — reuses the
linter library function, asserts zero hits. Marked to skip if the linter
script is missing (so it's resilient to partial checkouts).

## Exit criteria

1. `python3 scripts/check_no_third_party_names.py` → exit 0 in the
   worktree.
2. `rg -il openclaw feral-core/ SECURITY.md docs/contributing-channels.md
   TRACK_A_CHANNELS_PROVIDERS.md` → no hits.
3. `pytest feral-core/tests/test_no_third_party_names_literal.py` → pass.
4. `pytest feral-core/tests/` full run → same pass-count trend as
   origin/main (renames touched docstrings only; no identifiers moved).
