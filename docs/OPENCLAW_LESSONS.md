# openclaw → FERAL: lessons audit (2026-04-25)

> **Read-only comparative architecture study.** No source files in either tree were modified. The only artifact this audit produces is this document.
>
> **Audience.** FERAL core team. Internal. Brutally honest by design.

## 0. Method + verification evidence

**Repos compared.**

| Tag | Path | Stack | Role here |
|---|---|---|---|
| openclaw | `/Users/mahmoudomar/Desktop/thoera-mac/openclaw-main 2/` | TypeScript/Node 22 (ESM), Vitest, pnpm | Mature reference, ~5,000 src files, ships under `OpenClaw` brand on GitHub |
| FERAL    | `/Users/mahmoudomar/Desktop/thoera-mac/ASOS/`               | Python 3.11 (FastAPI) + React/Vite + Swift + Rust/Tauri | Target of the audit, current `main` plus 4 in-flight wave‑1 PRs (#19/#20/#22/#23) |

**File-count signal (per cluster):**

```
secrets:                    112  .ts files (openclaw)
agents/auth-profiles:        59
process/supervisor:          14
sessions:                    18
model-catalog:                7
plugins/runtime:             39
plugin-sdk:                 449
security:                    78
realtime-voice:              11
realtime-transcription:       4
mcp:                         12
gateway/protocol:            32
channels:                   279
```

That `plugin-sdk: 449` and `channels: 279` already tells the headline story: openclaw's gravity is in its plugin/channel platform, not in any one provider integration.

**Threat model alignment.** openclaw's `SECURITY.md:50–66` explicitly puts the product on the same single-trusted-operator threat model as FERAL — they reject reports that "assume per-user multi-tenant authorization on a shared gateway host/config" and treat operator-intended local features (TUI shell, `canvas.eval`, `node.invoke`) as trusted-operator capabilities, not bugs. **The patterns below transfer; they are not solving a different problem.**

**FERAL baseline assumed throughout.** `feral-core/security/vault.py` (plaintext JSON + chmod 600), `feral-core/agents/llm_provider.py` (linear retry + flat cooldown map), `feral-core/agents/orchestrator.py:148/760` (per-session asyncio lock + asyncio.Semaphore parallel-tools), `feral-core/agents/supervisor.py:1–80` (audit/kill switch wrapping orchestrator entry points), `feral-core/providers/catalog.py` and `feral-core/providers/model_catalog.json` (pre and post W1), `feral-core/security/device_pairing.py:25–60` (plaintext token rows in SQLite), `feral-core/voice/{openai_realtime,gemini_live}.py`, `feral-core/mcp/server.py` (post W3 fix), `feral-core/channels/*` (handwritten per-channel adapters).

**Wave 1 in flight (assumed not yet on `main`).** W1 (PR #23: catalog freshness + verified frontier IDs), W2 (PR #19: Twin theatre), W3 (PR #20: MCP routes), W7 (PR #22: version single-source + CI gate). W10 was cancelled.

**Anti-rabbit-hole compliance.** I sampled 1–3 source files per cluster; no full directory walks of `secrets/`, `channels/`, or `extensions/`; no `pnpm test` runs (read-only mode). Every section below cites the exact file:line read.

---

## 1. Provider auth + credential storage

### 1.1 What openclaw does

**Two distinct stores, one per concern.** From `openclaw-main 2/AGENTS.md:138`:

> Secrets: channel/provider creds in `~/.openclaw/credentials/`; **model auth profiles in `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`**.

This is the single most important architectural divergence from FERAL. Channel/provider creds (Slack tokens, Telegram bot tokens, etc.) are kept separate from model-vendor auth (OpenAI, Anthropic, Codex). Model auth is **per-agent**, indexed by `agentId`, written under that agent's directory.

**Auth profile shape.** From `openclaw-main 2/src/agents/auth-profiles.ts:39–49`:

```ts
export type {
  ApiKeyCredential,
  AuthProfileCredential,
  AuthProfileFailureReason,
  AuthProfileIdRepairResult,
  AuthProfileState,
  AuthProfileStore,
  OAuthCredential,
  ProfileUsageStats,
  TokenCredential,
} from "./auth-profiles/types.js";
```

A profile is one of three credential shapes (`ApiKeyCredential`, `OAuthCredential`, `TokenCredential`). The store keeps `ProfileUsageStats` per profile ID — error counts, cooldown timers, disabled windows, last-used time, failure-reason histogram.

**Cross-process OAuth refresh lock.** From `openclaw-main 2/src/agents/auth-profiles/path-resolve.ts:37–61`:

```ts
/**
 * Resolve the path of the cross-agent, per-profile OAuth refresh coordination
 * lock. … This lock is the serialization point that prevents the
 * `refresh_token_reused` storm when N agents share one OAuth profile (see
 * issue #26322): every agent that attempts a refresh acquires this same file
 * lock, so only one HTTP refresh is in-flight at a time and peers can adopt
 * the resulting fresh credentials instead of racing against a single-use
 * refresh token.
 */
export function resolveOAuthRefreshLockPath(provider: string, profileId: string): string {
  const hash = createHash("sha256");
  hash.update(provider, "utf8");
  hash.update("\u0000", "utf8"); // NUL separator: unambiguous boundary.
  hash.update(profileId, "utf8");
  const safeId = `sha256-${hash.digest("hex")}`;
  return path.join(resolveStateDir(), "locks", "oauth-refresh", safeId);
}
```

This is exactly the kind of detail that signals "we already had this fail in production." The hash with a NUL separator is to prevent string-concatenation collisions across providers that happen to share a profile id.

**Per-surface secret target registry.** From `openclaw-main 2/src/secrets/target-registry-types.ts:6–22`:

```ts
export type SecretTargetRegistryEntry = {
  id: string;
  targetType: string;
  targetTypeAliases?: string[];
  configFile: SecretTargetConfigFile;
  pathPattern: string;
  refPathPattern?: string;
  secretShape: SecretTargetShape;
  expectedResolvedValue: SecretTargetExpected;
  includeInPlan: boolean;
  includeInConfigure: boolean;
  includeInAudit: boolean;
  providerIdPathSegmentIndex?: number;
  accountIdPathSegmentIndex?: number;
  authProfileType?: AuthProfileType;
  trackProviderShadowing?: boolean;
};
```

Every place a secret can live in config (or in the auth-profile file) is described declaratively — a `pathPattern` like `channels.telegram.*.botToken`, with wildcard / array tokens (see `target-registry-pattern.ts:4–15`). `includeInPlan` / `includeInConfigure` / `includeInAudit` are three independent booleans, so a single registry serves the setup wizard, the audit tool, and the config doctor without each subsystem hardcoding its own list.

### 1.2 What FERAL does today

`ASOS/feral-core/security/vault.py` is the entire FERAL credential story. Quoting `vault.py:38–76`:

```python
class BlindVault:
    def __init__(self, vault_path: Optional[str] = None):
        home = feral_home()
        self._vault_path = Path(vault_path) if vault_path else home / "credentials.json"
        ...
    def _load(self):
        ...
        with open(self._vault_path) as f:
            parsed = json.load(f)
        ...
    def _persist(self):
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._vault_path, "w") as f:
            json.dump(self._cache, f, indent=2)
        try:
            os.chmod(self._vault_path, 0o600)
        except OSError:
            pass
```

That's the whole storage layer. Plaintext JSON, single dict keyed by name, chmod 600 best-effort. The audit log at `vault.py:116–128` is good — every read/write/remove is journaled to `~/.feral/audit.log`. The fingerprinting helper at `vault.py:109–114` (sha256 truncated) is a nice touch. But:

- One blob, not per-agent.
- One credential type — implicitly `string`, no API-key vs OAuth vs token discrimination.
- No usage stats, no cooldown state, no failure-reason histogram.
- No cross-process lock; on a multi-process FERAL deploy, two writers race.

W9 is queued to add OS-keychain encryption + pairing-token hashing, and that's necessary, but it's the floor, not the ceiling.

### 1.3 Honest delta

**openclaw is materially ahead** on:

1. **Per-agent auth scoping.** A single FERAL Brain serves one user; openclaw's `agents/<agentId>/agent/auth-profiles.json` lets a single host run multiple identities with isolated model credentials. FERAL doesn't need this *yet*, but it lacks the seam to grow into it.
2. **Multiple credential types in one store.** OAuth (with refresh tokens) + API key + bearer token coexist in `AuthProfileStore.profiles`. FERAL stores everything as a string and the calling code has to know what it is.
3. **Cross-process refresh locking** (`path-resolve.ts:54`). FERAL has one Brain process today; the moment we run a second worker (HUP daemon, voice service, channel daemon) they share `~/.feral/credentials.json` with no coordinated refresh.
4. **Declarative secret target registry.** FERAL setup, FERAL audit, FERAL doctor (if any) each independently know about every credential field. openclaw's registry collapses these into one source.

**FERAL is not behind on:**

- The "LLM never sees raw credentials" stance (`vault.py:7–13`) is sound and stronger than openclaw's posture, which trusts the operator runtime to pass keys through.
- Per-skill audit log at the vault layer (`vault.py:116`) is more granular than openclaw's general logger.

### 1.4 FERAL adoption proposal — W16 (per-agent + multi-shape auth profiles, W9 prerequisite)

| Field | Value |
|---|---|
| Mission | Replace FERAL's single `~/.feral/credentials.json` blob with a per-agent `~/.feral/agents/<agent_id>/auth_profiles.json` store that holds `api_key`, `oauth`, `token` shapes, with cross-process refresh locks and usage stats. |
| Owned paths | `feral-core/security/auth_profiles.py` (new), `feral-core/security/auth_profiles/{types,store,paths,oauth_refresh_lock,usage,external_auth}.py` (new module), `feral-core/security/vault.py` (migration shim that delegates to AuthProfileStore for new code, keeps the legacy interface for callers we haven't migrated yet), `feral-core/cli/key_commands.py` (extend `feral key list/rotate/migrate`), `feral-core/tests/test_auth_profiles_*.py` (new). |
| Read-only context | `feral-core/api/routes/security_and_hardware.py`, `feral-core/api/routes/llm.py`, `feral-core/integrations/oauth/*`. |
| Depends on | W9 (vault encryption-at-rest must land first; W16 layers per-agent profiles on top of W9's encrypted storage). |
| Acceptance | `tests/test_auth_profiles_oauth_refresh_lock.py` (two simulated agents share a profile, only one HTTP refresh fires), `tests/test_auth_profiles_migration.py` (existing `credentials.json` is read once, split across `oauth`/`api_key` based on shape, written into `agents/default/auth_profiles.json`, original backed up `.bak.legacy`), `tests/test_auth_profiles_multi_agent.py` (two agent ids hold disjoint OAuth tokens; deleting one does not affect the other). |
| Effort | **L** — touches every code path that reads from the vault. |

### 1.5 Do NOT copy

- **`AGENTS.md` style of writing every cred path under `~/.openclaw/credentials/`.** openclaw's `credentials/` directory uses *per-channel* file naming. FERAL already has W9 to land OS-keychain encryption; layering openclaw's flat-file convention on top would undo that. Stay with one encrypted blob per shape.
- **WHAM probe.** openclaw's `auth-profiles/usage.ts:145–231` reaches out to `https://chatgpt.com/backend-api/wham/usage` to read OpenAI Codex live rate-limit windows. That endpoint is undocumented and openclaw maintains it for ChatGPT/Codex OAuth specifically. FERAL does not have a Codex backend; copying this path adds an unstable dependency on an unsupported API for zero current benefit.

---

## 2. Subagent / supervisor / session lifecycle

### 2.1 What openclaw does

**Process Supervisor: real subprocess management.** From `openclaw-main 2/src/process/supervisor/supervisor.ts:41–73`:

```ts
export function createProcessSupervisor(): ProcessSupervisor {
  const registry = createRunRegistry();
  const active = new Map<string, ActiveRun>();

  const cancel = (runId: string, reason: TerminationReason = "manual-cancel") => {
    const current = active.get(runId);
    if (!current) return;
    registry.updateState(runId, "exiting", { terminationReason: reason });
    current.run.cancel(reason);
  };

  const cancelScope = (scopeKey: string, reason: TerminationReason = "manual-cancel") => {
    if (!scopeKey.trim()) return;
    for (const [runId, run] of active.entries()) {
      if (run.scopeKey !== scopeKey) continue;
      cancel(runId, reason);
    }
  };
```

Then `supervisor.ts:96–183`:

```ts
const overallTimeoutMs = clampTimeout(input.timeoutMs);
const noOutputTimeoutMs = clampTimeout(input.noOutputTimeoutMs);
...
const touchOutput = () => {
  registry.touchOutput(runId);
  if (!noOutputTimeoutMs || settled) return;
  if (noOutputTimer) clearTimeout(noOutputTimer);
  noOutputTimer = setTimeout(() => {
    requestCancel("no-output-timeout");
  }, noOutputTimeoutMs);
};
...
if (overallTimeoutMs) {
  timeoutTimer = setTimeout(() => requestCancel("overall-timeout"), overallTimeoutMs);
}
```

Two timeouts: overall (hard wall) and no-output (silent-hang detector). `scopeKey` lets you cancel an entire family of subprocesses with one call — when a session dies, all of its subagents/PTY children die with it. The supervisor explicitly notes (`supervisor.ts:285–288`):

```ts
reconcileOrphans: async () => {
  // Deliberate no-op: this supervisor uses in-memory ownership only.
  // Active runs are not recovered after process restart in the current model.
},
```

So they made the same design choice FERAL did (no orphan recovery), but for a fundamentally different runtime — managing real OS processes (PTY + child-spawn adapters), not just async tasks.

**Subagent spawn family.** Sample from the test surface (`Glob` count = 14 files):

```
src/agents/openclaw-tools.subagents.sessions-spawn.allowlist.test.ts
src/agents/openclaw-tools.subagents.sessions-spawn.cron-note.test.ts
src/agents/openclaw-tools.subagents.sessions-spawn.lifecycle.test.ts
src/agents/openclaw-tools.subagents.sessions-spawn.model.test.ts
src/agents/openclaw-tools.subagents.sessions-spawn-applies-thinking-default.test.ts
src/agents/openclaw-tools.subagents.scope.test.ts
src/agents/openclaw-tools.subagents.sessions-spawn.test-harness.ts
src/agents/openclaw-tools.subagents.steer-failure-clears-suppression.test.ts
```

Each test name is its own contract: subagents have an *allowlist*, can be spawned from a *cron* note, have a *lifecycle*, have *model overrides*, default to a *thinking* profile when not specified, are *scoped* (cancellation cascades), and a steer failure clears suppression. That's the production-tested version of "main agent fires worker agents."

**Session lifecycle events.** `openclaw-main 2/src/sessions/session-lifecycle-events.ts:1` (small file, contract-only) plus the broader `src/sessions/{session-id-resolution,send-policy,model-overrides,session-chat-type}.ts` family. Send policy decides which channel/peer can speak when; model overrides let a session pin a specific model; level overrides let a session change verbosity.

### 2.2 What FERAL does today

`ASOS/feral-core/agents/orchestrator.py:148`:
```python
self._session_locks: dict[str, asyncio.Lock] = {}
```
Plus the parallel-tools dispatch at `:760–761`:
```python
parallel_cap = max(1, int(os.environ.get("FERAL_MAX_PARALLEL_TOOLS", "6")))
sem = asyncio.Semaphore(parallel_cap)
```

That's the entire concurrency primitive: per-session asyncio.Lock + global Semaphore for tool-call fanout. Cleanup at `:1166-1181` drops the lock on session disconnect / eviction.

`ASOS/feral-core/agents/supervisor.py:8–25`:
> [Supervisor] sits in front of `Orchestrator.handle_command`, `handle_command_stream`, and `handle_ui_event`. It records every call as a row in `supervisor_events` (SQLite) — source, kind, session_id, actor, payload hash, decision, latency. Broadcasts a `supervisor_event` WS frame so the v2 /oversight page can render a live event river. Exposes a kill-switch ... Designed to be thin: it WRAPS the orchestrator, it does not replace it.

So FERAL's "supervisor" is an audit + kill switch wrapper for the LLM orchestrator. There is no equivalent of openclaw's `process/supervisor/` for managing real OS subprocesses. The "main agent fires other agents" pattern in FERAL today is: the orchestrator calls `tool_runner` calls back into more LLM calls. There are no OS-level subprocesses, no PTY, no allowlist, no scope-cancel of a family.

### 2.3 Honest delta

**openclaw is materially ahead** on:

1. **OS process supervision** (overall + no-output timeout, scope-cancel, PTY + child adapter abstraction). FERAL has nothing here; the equivalent is "asyncio task that hopes nothing hangs."
2. **Subagent allowlist + spawn lifecycle** as a tested contract surface. FERAL's `Orchestrator.handle_command_stream` is the closest analog — it can be called by anything; there's no policy that decides which callers may spawn child sessions.
3. **Per-session model/policy overrides** (`sessions/model-overrides.ts`, `sessions/send-policy.ts`). FERAL has session-keyed conversation history and locks but no "this session pinned model X / level Y / send policy Z" abstraction.

**FERAL is not behind on:**

- The audit-log + kill-switch in `agents/supervisor.py` is genuinely a clean thin wrapper, exactly the discipline AGENTS.md preaches ("WRAPS the orchestrator, it does not replace it").
- The asyncio.Semaphore parallel-tools dispatch is sufficient for FERAL's single-host concurrency model. openclaw does heavier per-process orchestration because it spawns external CLI backends (claude-cli, codex-cli) — FERAL doesn't.

### 2.4 FERAL adoption proposal — W17 (subagent spawn contract + scope cancel)

| Field | Value |
|---|---|
| Mission | Add a `SubagentSpawner` to FERAL's orchestrator that mirrors openclaw's allowlist + scope + lifecycle contract: a parent session can spawn a child orchestrator session with a `scope_key`; cancelling the scope cancels every child; spawn requires the parent's session policy to allowlist the requested child kind. |
| Owned paths | `feral-core/agents/subagent_spawner.py` (new), `feral-core/agents/subagent_policy.py` (new), `feral-core/agents/orchestrator.py` (additive — new method `spawn_subsession(parent_id, kind, *, scope_key, model_override)`), `feral-core/api/routes/sessions.py` (POST `/api/sessions/{id}/spawn`), `feral-core/tests/test_subagent_*.py` (new, mirror openclaw's test names: allowlist, lifecycle, scope, model-override, steer-failure-clears-suppression). |
| Read-only context | `feral-core/agents/supervisor.py`, `feral-core/agents/orchestrator.py` parallel-tools block. |
| Depends on | W2 (supervisor must already gate orchestrator entry points; landed). Independent of W9/W16. |
| Acceptance | All five test names above present and green; cancelling parent kills children within 200ms; spawning a kind not in the parent's allowlist returns a clear error and is logged to the supervisor as `decision="denied"`. |
| Effort | **M** — additive, no rewrite. |

### 2.5 FERAL adoption proposal — W18 (process supervisor for external CLI backends)

| Field | Value |
|---|---|
| Mission | Bring openclaw-style `process/supervisor` to FERAL so future external CLI integrations (Codex CLI, Claude Code CLI, Ollama serve, ffmpeg pipelines, daemon restarts) get overall + no-output timeouts, scope cancel, PTY + child adapter, and a `RunRegistry`. |
| Owned paths | `feral-core/process/supervisor/{__init__,types,registry,supervisor,adapters/child,adapters/pty}.py` (new), `feral-core/tests/test_process_supervisor_*.py` (new). |
| Read-only context | `feral-core/services/*` (some daemons can later migrate to it). |
| Depends on | W17 (the `scope_key` concept is shared between subagent spawning and process spawning). |
| Acceptance | `test_overall_timeout_kills`, `test_no_output_timeout_kills`, `test_scope_cancel_kills_all_children`, `test_registry_finalize_on_exit`, `test_pty_adapter_uses_login_shell`. |
| Effort | **L** — new subsystem, no callers yet, but the abstraction has to be right the first time. |

### 2.6 Do NOT copy

- **The "ACP silent approval" model** (`SECURITY.md:65`) is intentionally narrow in openclaw and tied to their gateway protocol. FERAL's autonomy modes (Draft/Auto/Off in W2's Twin section) are its own policy axis; do not import openclaw's vocabulary.

---

## 3. Async + parallel + rate-limit + cost

### 3.1 What openclaw does

**Cooldown is a state machine, not a flat map.** From `openclaw-main 2/src/agents/auth-profiles/usage.ts:39–63`:

```ts
const FAILURE_REASON_PRIORITY: AuthProfileFailureReason[] = [
  "auth_permanent",
  "auth",
  "billing",
  "format",
  "model_not_found",
  "overloaded",
  "timeout",
  "rate_limit",
  "unknown",
];
...
const WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage";
const WHAM_TIMEOUT_MS = 3_000;
const WHAM_BURST_COOLDOWN_MS = 15_000;
const WHAM_PROBE_FAILURE_COOLDOWN_MS = 30_000;
const WHAM_HTTP_ERROR_COOLDOWN_MS = 5 * 60 * 1000;
const WHAM_TOKEN_EXPIRED_COOLDOWN_MS = 12 * 60 * 60 * 1000;
const WHAM_DEAD_ACCOUNT_COOLDOWN_MS = 24 * 60 * 60 * 1000;
```

The two-lane design (`usage.ts:374–386`):

```ts
const DISABLED_FAILURE_BACKOFF_POLICIES = {
  billing: {
    baseMs: (cfg) => cfg.billingBackoffMs,
    maxMs: (cfg) => cfg.billingMaxMs,
  },
  auth_permanent: {
    // Keep high-confidence permanent-auth failures in the disabled lane, but
    // recover much sooner than billing because some providers surface
    // auth-looking payloads transiently during incidents.
    baseMs: (cfg) => cfg.authPermanentBackoffMs,
    maxMs: (cfg) => cfg.authPermanentMaxMs,
  },
} as const satisfies Record<DisabledFailureReason, DisabledFailureBackoffPolicy>;
```

`billing` and `auth_permanent` go into the **disabled lane** (5h–24h, exponential `base * 2^(errorCount-1)` capped). Everything else stays in the **cooldown lane** (`usage.ts:348–357`):

```ts
export function calculateAuthProfileCooldownMs(errorCount: number): number {
  const normalized = Math.max(1, errorCount);
  if (normalized <= 1) return 30_000;     // 30 seconds
  if (normalized <= 2) return 60_000;     // 1 minute
  return 5 * 60_000;                      // 5 minutes max
}
```

**Active-window immutability** (`usage.ts:513–522`):

```ts
function keepActiveWindowOrRecompute(params: {
  existingUntil: number | undefined;
  now: number;
  recomputedUntil: number;
}): number {
  const hasActiveWindow =
    typeof existingUntil === "number" && Number.isFinite(existingUntil) && existingUntil > now;
  return hasActiveWindow ? existingUntil : recomputedUntil;
}
```

Retries within an active cooldown **do not** extend the recovery time. Without this, hammering a rate-limited provider would push the recovery window further out forever.

**Per-model cooldown scope** (`usage.ts:586–623`): a `rate_limit` failure may be model-scoped (a different model on the same profile is still allowed); any other failure (auth, billing) is profile-wide and clears `cooldownModel`.

**Per-key API rotation** (`openclaw-main 2/src/agents/api-key-rotation.ts:40–72`):

```ts
export async function executeWithApiKeyRotation<T>(
  params: ExecuteWithApiKeyRotationOptions<T>,
): Promise<T> {
  const keys = dedupeApiKeys(params.apiKeys);
  ...
  for (let attempt = 0; attempt < keys.length; attempt += 1) {
    const apiKey = keys[attempt];
    try {
      return await params.execute(apiKey);
    } catch (error) {
      const message = formatErrorMessage(error);
      const retryable = params.shouldRetry
        ? params.shouldRetry({ apiKey, error, attempt, message })
        : isApiKeyRateLimitError(message);
      if (!retryable || attempt + 1 >= keys.length) break;
      params.onRetry?.({ apiKey, error, attempt, message });
    }
  }
  throw lastError;
}
```

A user can configure multiple OpenAI keys; openclaw rotates through them on rate-limit. Combined with the cooldown lane above, this means **N parallel agents hammering one key get round-robined across all of the user's keys for that provider, each key earns its own cooldown, and the disabled lane keeps a permanently-broken key out for 24h.**

**Lock-coordinated store updates** (`usage.ts:316–346`):

```ts
const updated = await authProfileUsageDeps.updateAuthProfileStoreWithLock({
  agentDir,
  updater: (freshStore) => {
    if (!freshStore.profiles[profileId]) return false;
    updateUsageStatsEntry(freshStore, profileId, (existing) =>
      resetUsageStats(existing, { lastUsed: Date.now() }),
    );
    return true;
  },
});
```

Concurrent agents writing usage updates go through `updateAuthProfileStoreWithLock` — a file-lock-coordinated atomic update. No lost writes.

### 3.2 What FERAL does today

`ASOS/feral-core/agents/llm_provider.py:29–46`:
```python
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # seconds
_RETRIABLE_CODES = ("429", "500", "502", "503", "504", "timeout", "connection")

async def _retry_llm_call(coro_factory):
    for attempt in range(MAX_RETRIES):
        try:
            return await coro_factory()
        except Exception as e:
            err_str = str(e).lower()
            retriable = any(code in err_str for code in _RETRIABLE_CODES)
            if not retriable or attempt == MAX_RETRIES - 1:
                raise
            ...
            await asyncio.sleep(RETRY_DELAYS[attempt])
```

Linear backoff. Substring-match on error string. No `Retry-After` honor. No per-key rotation. No cooldown.

`llm_provider.py:130–164` adds `ProviderCooldownTracker` with a flat map:
```python
_COOLDOWN_MAP: dict[FailoverReason, int] = {
    FailoverReason.RATE_LIMIT: 60,
    FailoverReason.AUTH: 300,
    FailoverReason.AUTH_PERMANENT: 86400,
    FailoverReason.BILLING: 3600,
    FailoverReason.OVERLOADED: 30,
    FailoverReason.TIMEOUT: 15,
}
_PROBE_INTERVAL = 30.0
```

This is the entire cooldown surface. No exponential backoff, no two-lane design, no per-key rotation, no failure-window reset, no per-model scoping, no active-window immutability, no cross-process lock. The `is_available(provider)` check (`:151`) makes the binary decision: cooled down or not.

### 3.3 Honest delta

This is the cluster where openclaw is **most ahead** in technical depth. The FERAL implementation is a working v1; openclaw is a working v5 with the field scars to prove every refinement.

Concrete answers to the prompt's "5 agents in parallel hammer one provider; one starts 429-ing — how does the system rebalance?" question:

| Question | openclaw answer | FERAL today |
|---|---|---|
| Does retry honor `Retry-After`? | WHAM probe + computed reset window for OAuth (`usage.ts:96–115`); generic providers via classification, not header. | **No** — substring match only. |
| Can a single provider have multiple keys? | Yes (`api-key-rotation.ts:18–30`). | **No** — one env var per provider. |
| When all keys for one provider exhaust, what happens? | Failover via `chat_with_failover` (the FERAL helper exists too, but enters the cooldown map). | Failover via `chat_with_failover`. *Parity here.* |
| Do parallel agents share the cooldown state? | Yes, file-locked usage.ts updates (`usage.ts:316–346`). | **No** — `ProviderCooldownTracker` is per-process; each FERAL worker has its own cooldown view. |
| If one agent hits 429 and recovers, do other agents see the new error count? | Yes, the on-disk `failureCounts` map is read on next call. | **No.** |
| Can a model-scoped rate limit allow a *different model* on the same key to keep working? | Yes (`usage.ts:586–623`). | **No** — provider-level only. |
| Does retrying within an active cooldown extend the cooldown? | **No** (`keepActiveWindowOrRecompute`, `usage.ts:513–522`). | **Yes**, implicitly — every failure pushes a new `_cooldowns[provider]` value. |
| Does the failure window reset error counters? | Yes, 24h default (`usage.ts:393`). | **No** — counters monotonically grow. |

### 3.4 FERAL adoption proposal — W19 (cooldown state machine + per-key rotation + Retry-After)

| Field | Value |
|---|---|
| Mission | Replace `_retry_llm_call` linear backoff and `ProviderCooldownTracker` flat map with: (a) a two-lane state machine (cooldown vs disabled) with exponential backoff and active-window immutability; (b) per-key API rotation; (c) `Retry-After` header honoring; (d) per-model cooldown scope for `rate_limit`; (e) failure-window-based counter reset. Cross-process coordination uses the file lock landed by W16. |
| Owned paths | `feral-core/agents/llm_failover.py` (new — extract from llm_provider.py), `feral-core/agents/llm_cooldown.py` (new — the state machine), `feral-core/agents/llm_provider.py` (refactor `chat_with_failover` to call the new modules), `feral-core/tests/test_llm_cooldown_state.py`, `feral-core/tests/test_llm_per_key_rotation.py`, `feral-core/tests/test_llm_retry_after.py`, `feral-core/tests/test_llm_active_window_immutable.py`, `feral-core/tests/test_llm_failure_window_reset.py`, `feral-core/tests/test_llm_per_model_scope.py`. |
| Read-only context | `feral-core/agents/orchestrator.py` parallel-tools block, openclaw `auth-profiles/usage.ts` for reference. |
| Depends on | W15 (router/budget) for the higher-level routing; W19 is the lower mechanism W15 sits on. If W15 hasn't shipped, W19 ships first and W15 builds on top. |
| Acceptance | All 6 test files green; the existing `test_llm_failover.py` and `test_provider_cooldown_tracker*` tests pass without weakening; with two simulated workers hitting one OpenAI key, the second worker observes the cooldown state from the first within 5 seconds of the first failure. |
| Effort | **L** — touching the hottest path in the system; needs to be backward-compatible during rollout. |

### 3.5 Do NOT copy

- **WHAM probe** (`usage.ts:145–231`) is OAuth-Codex specific and reaches an undocumented ChatGPT endpoint. FERAL must not adopt it without an OAuth-Codex backend, and even then it's a hostile-API risk. Use generic `Retry-After` parsing instead.

---

## 4. Model catalog + freshness + routing

### 4.1 What openclaw does

**Catalog data shape.** `openclaw-main 2/src/model-catalog/types.ts:4–11`:

```ts
export type ModelCatalogInput = "text" | "image" | "document";
export type ModelCatalogDiscovery = "static" | "refreshable" | "runtime";
export type ModelCatalogStatus = "available" | "preview" | "deprecated" | "disabled";
export type ModelCatalogSource =
  | "manifest"
  | "provider-index"
  | "cache"
  | "config"
  | "runtime-refresh";
```

Then `types.ts:29–47`:

```ts
export type ModelCatalogModel = {
  id: string;
  name?: string;
  api?: ModelApi;
  baseUrl?: string;
  headers?: Record<string, string>;
  input?: ModelCatalogInput[];
  reasoning?: boolean;
  contextWindow?: number;
  contextTokens?: number;
  maxTokens?: number;
  cost?: ModelCatalogCost;
  compat?: ModelCompatConfig;
  status?: ModelCatalogStatus;
  statusReason?: string;
  replaces?: string[];
  replacedBy?: string;
  tags?: string[];
};
```

That `replaces` / `replacedBy` chain is the feature FERAL is missing. When `gpt-5.4` ships, openclaw can mark `gpt-4o` as `status: "deprecated"`, `replacedBy: "gpt-5.4"`, and the picker can render the chain. FERAL's W1 went straight from listing `gpt-4o` to dropping it.

**Plugin manifest declares its own catalog.** `openclaw-main 2/extensions/openai/openclaw.plugin.json` ships defaults right in the manifest:

```json
"mediaUnderstandingProviderMetadata": {
  "openai": {
    "capabilities": ["image", "audio"],
    "defaultModels": {
      "image": "gpt-5.4-mini",
      "audio": "gpt-4o-transcribe"
    },
    "autoPriority": { "image": 10, "audio": 10 }
  },
  "openai-codex": {
    "capabilities": ["image"],
    "defaultModels": { "image": "gpt-5.5" }
  }
}
```

Note: openclaw already has `gpt-5.5` and `gpt-5.4-mini` baked into a shipped plugin manifest. The release was 2026-04-23 and openclaw was current within a day.

**Catalog discovery modes.** `discovery: "static" | "refreshable" | "runtime"` — a provider that exposes `/v1/models` is `refreshable`; one that doesn't (Anthropic) is `static`; one that streams its catalog at runtime (Ollama) is `runtime`. FERAL's `provider-research.yml` cron and `ProviderCatalog.refresh_async` (W1) are both implementations of `refreshable`, but the type system never names the distinction.

**Manifest planner.** `openclaw-main 2/src/model-catalog/manifest-planner.ts` (not quoted; export shape from `index.ts:11`):

```ts
export { planManifestModelCatalogRows } from "./manifest-planner.js";
```

Plugins contribute catalog rows, the planner merges them with a `mergeKey`, conflicts are surfaced (`ManifestModelCatalogConflict`), and the picker sees one normalized row set.

### 4.2 What FERAL does today

Pre-W1: `feral-core/providers/model_catalog.json` was a flat JSON keyed by provider with `models: string[]` and `pricing: {model: {input, output}}`. No status, no reasoning flag, no replaces/replacedBy, no per-model context window, no capability tags. `feral-core/providers/catalog.py:127` defaulted OpenAI to `gpt-4o-mini`.

Post-W1 (PR #23): the model list now includes `gpt-5.5`, `claude-opus-4-7`, `gemini-3.1-pro-preview`. The hardcoded defaults at `catalog.py:127` and `agents/llm_provider.py:167–176` are gone. `provider-research.yml` cron is back on. A `ProviderCatalog.refresh_async()` runs every 6 hours in-Brain. The Settings dropdown gets a Live/Cached/Stale badge. **Net: FERAL is now current as of 2026-04-24, but the data shape is still flat strings; no deprecation chains, no input/reasoning/context flags.**

### 4.3 Honest delta

**openclaw is materially ahead** on:

1. **Per-model metadata richness** (`ModelCatalogModel`). FERAL today knows that `gpt-5.5` exists; openclaw knows `{ id: "gpt-5.5", contextWindow: 1_000_000, reasoning: true, input: ["text", "image"], cost: {...}, status: "available", replaces: ["gpt-5.4"], tags: [...] }`.
2. **Discovery mode taxonomy** — making `static`/`refreshable`/`runtime` first-class so the UI can show "this provider auto-refreshes / requires manual edit / is detected at runtime" instead of FERAL's silent "Anthropic just sits on a curated list."
3. **Manifest-contributed catalog** — plugins extend the catalog declaratively. FERAL's catalog is monolithic in-tree.

**FERAL is not behind on:**

- Cron-based catalog refresh (`provider-research.yml`) is now active post-W1; openclaw has analogous tooling but it's plugin-side rather than centralized.
- The Live/Cached/Stale badge in Settings (W1 deliverable) is good UX that openclaw doesn't surface as crisply.

### 4.4 FERAL adoption proposal — W20 (catalog metadata enrichment + deprecation chains)

| Field | Value |
|---|---|
| Mission | Extend `feral-core/providers/model_catalog.json` and `ProviderCatalog` to carry per-model `contextWindow`, `inputs: ["text"\|"image"\|"document"]`, `reasoning: bool`, `status: "available"\|"preview"\|"deprecated"`, `replaces: [string]`, `replacedBy: string`, `tags: [string]`. Surface deprecation chains in the v2 Settings dropdown ("gpt-4o → gpt-5.4 → gpt-5.5"). |
| Owned paths | `feral-core/providers/{catalog_types,catalog,model_catalog.json}.py`, `feral-core/providers/manifest_planner.py` (new — plugin contribution), `feral-client-v2/src/components/ProviderModelPicker.jsx` (new), `feral-client-v2/src/pages/Settings.jsx` (provider section only — coordinate with W1 owner range). |
| Read-only context | `feral-core/agents/llm_provider.py`, `feral-core/cli/setup_wizard.py`. |
| Depends on | W1 (must be merged so the catalog is fresh before we add metadata). Independent of W19. |
| Acceptance | `tests/test_provider_catalog_metadata.py` (new model rows have all metadata fields), `tests/test_provider_catalog_deprecation_chain.py` (replacedBy chain renders correctly), `tests/test_v2_provider_picker_chain.test.jsx` (deprecation chain shows in dropdown). |
| Effort | **M**. |

### 4.5 Do NOT copy

- **One-manifest-per-extension.** openclaw's `extensions/*/openclaw.plugin.json` is appropriate for their plugin platform (W21 below). FERAL's catalog should *consume* manifests but not *be one*. Centralized canonical catalog with manifest contributions is the right shape.

---

## 5. Plugin / extension / channel model

### 5.1 What openclaw does

This is the cluster where openclaw is most architecturally ahead. The numbers tell the story: 449 `.ts` files in `plugin-sdk/`, 279 in `channels/`, ~140 extensions in `extensions/`. Each extension is a directory with a single `openclaw.plugin.json` manifest plus runtime code under its own `src/`. Sample extensions seen in the listing:

```
extensions/{anthropic, anthropic-vertex, openai, gemini, groq, deepseek, xai, fireworks,
            together, openrouter, vercel-ai-gateway, bedrock, codex,
            telegram, slack, discord, whatsapp, matrix, signal, zalo, voice-call,
            twitch, x, feishu, googlechat, google-meet, bluebubbles, github-copilot,
            elevenlabs, deepgram, fal, comfy, exa, brave, duckduckgo, firecrawl,
            web-readability, document-extract, webhooks, ...}
```

Compare that catalog to FERAL's `feral-core/channels/` (Telegram, Discord, Slack, WhatsApp first-class; Matrix/Signal/Feishu/Zalo/voice_call as TODO stubs per the roadmap).

**Manifest schema (sample, `extensions/openai/openclaw.plugin.json`).** Beyond the `providerAuthChoices` and `contracts:` blocks already quoted in §1 and §4, the same manifest also declares:

```json
{
  "id": "openai",
  "enabledByDefault": true,
  "providers": ["openai", "openai-codex"],
  "modelSupport": { "modelPrefixes": ["gpt-", "o1", "o3", "o4"] },
  "cliBackends": ["codex-cli"],
  "providerAuthEnvVars": { "openai": ["OPENAI_API_KEY"] },
  "providerAuthChoices": [
    { "provider": "openai-codex", "method": "oauth",
      "choiceId": "openai-codex", "deprecatedChoiceIds": ["codex-cli", "openai-codex-import"],
      "choiceLabel": "OpenAI Codex Browser Login", ...
      "assistantPriority": -30, "groupId": "openai-codex" },
    { "provider": "openai-codex", "method": "device-code",
      "choiceId": "openai-codex-device-code", ...
      "assistantPriority": -10 },
    { "provider": "openai", "method": "api-key",
      "choiceId": "openai-api-key",
      "optionKey": "openaiApiKey",
      "cliFlag": "--openai-api-key",
      "cliOption": "--openai-api-key <key>",
      "cliDescription": "OpenAI API Key", ... }
  ],
  "contracts": {
    "speechProviders": ["openai"],
    "realtimeTranscriptionProviders": ["openai"],
    "realtimeVoiceProviders": ["openai"],
    "memoryEmbeddingProviders": ["openai"],
    "mediaUnderstandingProviders": ["openai", "openai-codex"],
    "imageGenerationProviders": ["openai"],
    "videoGenerationProviders": ["openai"]
  }
}
```

Single declarative file declares: provider IDs, env var names, multiple auth methods (OAuth / device-code / API key), CLI flag mapping, capability contracts (this plugin implements speech / realtime-voice / image / video / etc.), legacy choice ID migration, model prefix matching for catalog hints, and config schema.

**SDK boundary (`AGENTS.md:27–30`):**

> Extensions cross into core only via `openclaw/plugin-sdk/*`, manifest metadata, injected runtime helpers, documented barrels (`api.ts`, `runtime-api.ts`).
> Extension prod code: no core `src/**`, `src/plugin-sdk-internal/**`, other extension `src/**`, or relative outside package.
> Core/tests: no deep plugin internals (`extensions/*/src/**`, `onboard.js`). Use `api.ts`, SDK facade, generic contracts.

This is the architectural rule that makes 140+ extensions sustainable. Core does not reach into extensions; extensions reach into core only via the SDK barrel. Test surfaces go through generic contracts (`provider-runtime.contract.test.ts`, `provider-catalog.contract.test.ts`, `provider-auth.contract.test.ts`, all inside `extensions/openai/`).

### 5.2 What FERAL does today

`ASOS/feral-core/channels/base.py` is a 965-line abstract base with concrete handlers for Telegram, Slack, Discord, WhatsApp built into adjacent files. There is no manifest. New channels are written as Python modules; capability declarations live implicitly in the class hierarchy.

`feral-core/integrations/*` follows a similar pattern — a Python module per integration (Calendar, Email, M365, Google, Notion, Spotify, OAuth, Webhooks, Home Assistant, MQTT). No manifest.

`feral-core/genui/*` is the closest thing FERAL has to a plugin model — third-party "apps" register a `AppManifest` (Pydantic), surfaces / actions / data schemas. W8 (queued) will add manifest signing + sandboxing. **It is the seed of an extension model.**

### 5.3 Honest delta

**openclaw is dramatically ahead.** The feature counts (140 extensions vs ~10 first-class channels + stubs) and the architectural rules (`AGENTS.md:27–30`) are not just about scale; they're about a *seam* that makes contributors possible. FERAL ships every channel as in-tree Python; openclaw ships every channel as a self-contained extension with a manifest.

**FERAL is not behind on:**

- The W8-introduced `AppManifest` is the right shape for FERAL's GenUI app model (third-party apps inside FERAL's UI). Migrating CHANNELS into the same manifest model is the bigger play.
- The threat-model match (`SECURITY.md:50–66`) means we don't have to rebuild trust scaffolding from scratch — the operator-trusted model openclaw uses is the same one FERAL uses.

### 5.4 FERAL adoption proposal — W21 (channel manifest + extension SDK)

| Field | Value |
|---|---|
| Mission | Define a `channel.manifest.json` schema modeled on `openclaw.plugin.json` — capability contracts, providerAuthEnvVars, providerAuthChoices, modelSupport. Migrate the four shipping channels (Telegram, Slack, Discord, WhatsApp) to the new manifest model. Ship a `feral-channel-sdk` Python package that mirrors the openclaw `plugin-sdk` SDK boundary rule. |
| Owned paths | `feral-core/channels/manifest.py` (new — schema), `feral-core/channels/{telegram,slack,discord,whatsapp}/feral.channel.json` (new), `feral-core/channels/loader.py` (new — manifest discovery + capability registry), `feral-core/channels/sdk/__init__.py` (new), `docs/contributing-channels.md` (new), `feral-core/tests/test_channel_manifest_*.py`. |
| Read-only context | `feral-core/channels/base.py`, `feral-core/api/routes/channels.py`. |
| Depends on | W8 (manifest signing pattern; W21 reuses the same Ed25519 envelope). Independent of W17/W18/W19. |
| Acceptance | All four channel manifests present and load through `loader.py`; capability registry returns the right `messagingProviders`/`voiceProviders`/etc. lists; the four existing channel tests pass unchanged; one new contract test (`test_channel_contract_send_receive`) runs against any registered channel manifest. |
| Effort | **XL** — the largest single change in the wave; touches the channel architecture. Should be split into 3 PRs (schema + loader, channel migration, SDK + docs). |

### 5.5 Do NOT copy

- **`extensions/`-as-published-packages on npm.** openclaw publishes extensions; FERAL's distribution model is one Python wheel + one Tauri binary. The manifest model is portable; the package layout is not. Keep FERAL channel manifests in-tree under `feral-core/channels/<name>/` rather than separate published packages.
- **`pnpm`-tier monorepo tooling.** openclaw's "smart gate" / `pnpm check:changed` (`AGENTS.md:46`) is fantastic but specific to their TypeScript monorepo. FERAL stays with its mixed Python+JS+Swift+Rust toolchain; do not retrofit a pnpm workspace.

---

## 6. Sandboxing + security

### 6.1 What openclaw does

openclaw ships **dedicated sandbox Dockerfiles**:
- `Dockerfile.sandbox` (general)
- `Dockerfile.sandbox-browser`
- `Dockerfile.sandbox-common`

Plus systemd integration: `scripts/systemd/openclaw-auth-monitor.{service,timer}`. The runtime side is `src/security/` (78 files; not enumerated here).

**`SECURITY.md` is unusually specific about what is in/out of trust scope** (`SECURITY.md:50–77`):

- "Operator-intended local features (TUI local `!` shell) presented as remote injection" — out of scope.
- "Reports that treat explicit operator-control surfaces (for example `canvas.eval`, browser evaluate/script execution, or direct `node.invoke` execution primitives) as vulnerabilities without demonstrating an auth/policy/sandbox boundary bypass" — out of scope.
- "Reports that only show a malicious plugin executing privileged actions after a trusted operator installs/enables it" — out of scope.

This is the "what FERAL is not" ADR the FERAL roadmap §3.7 P1 asks for, written for openclaw. It is itself a transferable artifact.

**Approval-bypass-as-tested-contract.** Sample test names (from the channels surface read in §0): `server-channels.approval-bootstrap.test.ts`, `server.node-invoke-approval-bypass.test.ts`, `server.device-pair-approve-authz.test.ts`, `server.node-pairing-authz.test.ts`. Approval boundaries have explicit tests for **bypass** as a property, not just for happy-path approval.

### 6.2 What FERAL does today

`feral-core/security/` has: `vault.py`, `device_pairing.py`, `docker_sandbox.py`, `wasm_sandbox.py`, `wasm_host.py`, `tool_genesis.py`, `fetch_guard.py`, `content_defense.py`, `session_auth.py`, `sandbox_policy.py`, `exec_approvals.py`. The roadmap (§2.16, §3.3) flags that the WASM sandbox is in development, signed-marketplace trust path is open (`genui/a2ui_protocol.py:121`), and that no dedicated tests for `fetch_guard.py` / `content_defense.py` / `dangerous_tools` exist yet.

FERAL has no `Dockerfile.sandbox`, no systemd timer/service for credential rotation/monitoring, no `SECURITY.md` of comparable specificity.

### 6.3 Honest delta

**openclaw is materially ahead** on:

1. **Documented threat model** (`SECURITY.md`) at the level of "here are 25 false-positive patterns we close as no-action." This is the artifact FERAL needs.
2. **Sandbox Dockerfiles** for browser-execution and code-execution surfaces.
3. **Approval-bypass tests as a tested property.** The W3 fix (`test_get_http_routes_exposes_mcp_endpoints`) is the right shape; openclaw has dozens of these covering channels, node-invoke, device pairing.

**FERAL is not behind on:**

- The execution-tier model (`vault.py:141–166` — PASSIVE / ACTIVE / PRIVILEGED / DANGEROUS) is a reasonable native taxonomy.
- W8 (signed manifest + AppSurface sandbox) and W9 (vault encryption + token hashing) are the right next steps.

### 6.4 FERAL adoption proposal — W22 (`SECURITY.md` + sandbox Dockerfiles + approval-bypass tests)

| Field | Value |
|---|---|
| Mission | Author `ASOS/SECURITY.md` modeled on openclaw's, including in-scope/out-of-scope bullets, fast-path triage gate, false-positive patterns, and the OPS-trusted operator boundary. Add `Dockerfile.sandbox` + `Dockerfile.sandbox-browser` for tool-genesis-generated code and AppSurface iframe rendering. Add a `tests/security/test_*_approval_bypass.py` family covering pairing, twin, executor, MCP. |
| Owned paths | `ASOS/SECURITY.md` (new), `ASOS/Dockerfile.sandbox` (new), `ASOS/Dockerfile.sandbox-browser` (new), `feral-core/security/sandbox_image.py` (new — image build helper), `feral-core/tests/security/test_pairing_approval_bypass.py`, `feral-core/tests/security/test_twin_approval_bypass.py`, `feral-core/tests/security/test_executor_approval_bypass.py`, `feral-core/tests/security/test_mcp_approval_bypass.py`. |
| Read-only context | `feral-core/security/{exec_approvals,sandbox_policy,docker_sandbox,wasm_sandbox}.py`, `feral-core/agents/twin_policy.py`. |
| Depends on | W8 (manifest signing); W9 (vault + token hashing). |
| Acceptance | `SECURITY.md` published with sections matching openclaw's structure and FERAL-specific in-scope/out-of-scope items; both Dockerfiles build cleanly in CI; the four approval-bypass tests pass. |
| Effort | **L**. |

### 6.5 Do NOT copy

- **The HackerOne / GHSA process** (`SECURITY.md:79–90`). FERAL does not have a security team yet. Adopting that workflow without staff is a footgun. Use the in-scope/out-of-scope structure; postpone the formal bounty program.

---

## 7. Realtime voice + audio surfaces

### 7.1 What openclaw does

`openclaw-main 2/src/realtime-voice/` is small (11 files) but the contract is sharp. From `session-runtime.ts:18`:

```ts
export type RealtimeVoiceMarkStrategy = "transport" | "ack-immediately" | "ignore";
```

And the bridge interface (`session-runtime.ts:20–46`):

```ts
export type RealtimeVoiceBridgeSession = {
  bridge: RealtimeVoiceBridge;
  acknowledgeMark(): void;
  close(): void;
  connect(): Promise<void>;
  sendAudio(audio: Buffer): void;
  sendUserMessage(text: string): void;
  setMediaTimestamp(ts: number): void;
  submitToolResult(callId: string, result: unknown): void;
  triggerGreeting(instructions?: string): void;
};

export type RealtimeVoiceBridgeSessionParams = {
  provider: RealtimeVoiceProviderPlugin;
  providerConfig: RealtimeVoiceProviderConfig;
  audioSink: RealtimeVoiceAudioSink;
  instructions?: string;
  initialGreetingInstructions?: string;
  markStrategy?: RealtimeVoiceMarkStrategy;
  triggerGreetingOnReady?: boolean;
  tools?: RealtimeVoiceTool[];
  onTranscript?: (role: RealtimeVoiceRole, text: string, isFinal: boolean) => void;
  onToolCall?: (event: RealtimeVoiceToolCallEvent, session: RealtimeVoiceBridgeSession) => void;
  onReady?: (session: RealtimeVoiceBridgeSession) => void;
  onError?: (error: Error) => void;
  onClose?: (reason: RealtimeVoiceCloseReason) => void;
};
```

Two key abstractions:

- **`RealtimeVoiceBridge`** is the per-provider plugin (each realtime-voice provider implements `createBridge()`).
- **`RealtimeVoiceAudioSink`** is the *consumer* of synthesized audio (the device speaker, the WebRTC peer, the ffmpeg pipe). It's intentionally separate from the bridge so a single bridge can be reused with different sinks (preview the call locally, then send to the device).

The mark strategy controls who acks transport timing checkpoints — `transport` means the sink relays, `ack-immediately` means the bridge acks itself, `ignore` means no acks. This is the precise lever for half-open WebSocket recovery and audio-frame backpressure.

`sendAudio` returns void (not a promise) — backpressure must happen *inside* the bridge, not via the caller awaiting. `audioSink.isOpen?.()` is the gate (`session-runtime.ts:71`).

### 7.2 What FERAL does today

`feral-core/voice/openai_realtime.py`, `feral-core/voice/gemini_live.py`, `feral-core/voice/realtime_proxy.py`, `feral-core/voice/wakeword.py`, `feral-core/voice/voice_router.py`. Each provider is a Python module with its own concrete WebSocket loop. There is no shared `Bridge` interface; the router calls into provider-specific helpers.

The FERAL roadmap §2.9 grades voice realtime as Beta with concerns about WS reconnect, half-open sockets, mid-utterance failover, and audio-frame backpressure not having soak tests (W12 queued).

### 7.3 Honest delta

**openclaw is ahead on the abstraction**, not necessarily on the implementation. Their bridge contract is what makes provider-swap during a session theoretically possible (replace the bridge, keep the sink); FERAL today routes a session at start time and stays put.

**FERAL is not behind on:**

- The provider-specific Python implementations are in production for some users.
- Wake-word detection is a FERAL-native concern openclaw doesn't ship.

### 7.4 FERAL adoption proposal — W23 (RealtimeVoiceBridge contract + AudioSink decoupling)

| Field | Value |
|---|---|
| Mission | Refactor `feral-core/voice/` to expose a `RealtimeVoiceBridge` contract (mirroring `session-runtime.ts:20–46`) and an `AudioSink` abstraction. Migrate `openai_realtime.py` and `gemini_live.py` to implement the bridge contract. Add a `mark_strategy` lever for backpressure. |
| Owned paths | `feral-core/voice/bridge.py` (new — Protocol type), `feral-core/voice/audio_sink.py` (new), `feral-core/voice/openai_realtime.py` (refactor), `feral-core/voice/gemini_live.py` (refactor), `feral-core/voice/router.py` (use the new contract), `feral-core/tests/test_voice_bridge_contract.py`. |
| Read-only context | `feral-core/voice/wakeword.py`, openclaw `realtime-voice/*` for reference. |
| Depends on | W12 (soak harness). W12 lands first so we can prove the refactor doesn't regress. |
| Acceptance | Both providers implement the same `RealtimeVoiceBridge` Protocol; `test_voice_bridge_contract.py` runs the same suite against both; soak metrics from W12 do not regress. |
| Effort | **L**. |

### 7.5 Do NOT copy

- **No-op** on this cluster. The openclaw bridge model is sound and FERAL-applicable.

---

## 8. MCP + gateway protocol + tool registration

### 8.1 What openclaw does

**MCP is a thin stdio bootstrap.** From `openclaw-main 2/src/mcp/openclaw-tools-serve.ts:14–37`:

```ts
export function resolveOpenClawToolsForMcp(): AnyAgentTool[] {
  return [createCronTool()];
}

export function createOpenClawToolsMcpServer(
  params: { tools?: AnyAgentTool[] } = {},
): Server {
  const tools = params.tools ?? resolveOpenClawToolsForMcp();
  return createToolsMcpServer({ name: "openclaw-tools", tools });
}

export async function serveOpenClawToolsMcp(): Promise<void> {
  const server = createOpenClawToolsMcpServer();
  await connectToolsMcpServerToStdio(server);
}
```

The MCP serve binary is intentionally minimal — `createCronTool()` plus whatever the caller passes. The actual tool registration is in `openclaw-main 2/src/agents/openclaw-tools.ts` and the surrounding 30+ `openclaw-tools.*.ts` files (see the file listing in §0). Tools are registered on a runtime via `openclaw-tools.registration.ts` and made available to the MCP server via the `AnyAgentTool` interface.

**Gateway protocol is its own subsystem.** `openclaw-main 2/src/gateway/protocol/` has 32 .ts files. The gateway serves an HTTP-compatible OpenAI Responses + Chat Completions API plus `POST /tools/invoke` plus an MCP HTTP surface (`gateway/mcp-http.*.ts` — 11 files). From `SECURITY.md:61–63`:

> Reports that treat the Gateway HTTP compatibility endpoints (`POST /v1/chat/completions`, `POST /v1/responses`) as if they implemented scoped operator auth (`operator.write` vs `operator.admin`). These endpoints authenticate the shared Gateway bearer secret/password and are documented full operator-access surfaces, not per-user/per-scope boundaries.

The protocol versioning is documented; `x-openclaw-scopes` headers exist but the trust contract is explicit (shared-secret bearer = full operator).

### 8.2 What FERAL does today

`ASOS/feral-core/mcp/server.py` (post W3): the route fix landed; routes are exposed on `/mcp*` via FastAPI with a JSON-RPC envelope. `feral-core/api/routes/mcp.py:12` is the HTTP wrapper.

There is no equivalent of openclaw's gateway protocol — FERAL's HTTP API is the gateway, but it doesn't impersonate OpenAI's Chat Completions / Responses surface. Tool registration flows through `feral-core/agents/orchestrator.py` and `feral-core/skills/registry.py`.

### 8.3 Honest delta

**openclaw is materially ahead** on:

1. **OpenAI-compatible HTTP gateway** (`gateway/protocol/*`). External clients (Cursor, an IDE plugin, a CI bot) can point at openclaw's gateway as a drop-in OpenAI base URL. FERAL has no such surface; clients have to use FERAL's bespoke API.
2. **MCP-over-HTTP** (`gateway/mcp-http.*.ts`, 11 files). FERAL's MCP is stdio + HTTP via FastAPI, but doesn't expose the same scoped MCP surface to remote callers.

**FERAL is not behind on:**

- The W3 fix lands the HTTP MCP shape correctly for FERAL's local-loopback model.
- Tool registration in FERAL is simpler (Python decorators in `skills/`) and fits the in-process model.

### 8.4 FERAL adoption proposal — W24 (OpenAI-compatible gateway endpoint)

| Field | Value |
|---|---|
| Mission | Add `/v1/chat/completions` + `/v1/responses` shims to FERAL's API server that route into the orchestrator under the existing API-key middleware. This makes Cursor, ides, scripts, etc. able to use FERAL as an OpenAI-API-compatible gateway. Honor the "shared-secret = full operator" contract documented in W22's SECURITY.md. |
| Owned paths | `feral-core/api/routes/openai_compat.py` (new), `feral-core/agents/openai_request_translator.py` (new), `feral-core/tests/test_openai_compat_*.py`. |
| Read-only context | `feral-core/api/server.py` middleware order, `feral-core/agents/orchestrator.py`. |
| Depends on | W22 (SECURITY.md must document the trust boundary first). Independent of W19/W21. |
| Acceptance | `tests/test_openai_compat_chat_completions.py` (curl with `Authorization: Bearer $FERAL_API_KEY` to `/v1/chat/completions` returns valid OpenAI-shaped response that delegates into the orchestrator), `tests/test_openai_compat_responses.py` (same for the Responses API), `tests/test_openai_compat_scope_contract.py` (asserts no scope reduction is honored on shared-secret bearer auth). |
| Effort | **M**. |

### 8.5 Do NOT copy

- **`x-openclaw-scopes` semantics on shared-secret auth.** openclaw's contract is "shared-secret = full operator regardless of declared scopes." FERAL should adopt the *same* contract and document it the same way; do not invent a new scope-on-shared-secret model.

---

## 9. Synthesis: top patterns to adopt + anti-patterns to avoid

### 9.1 Ranked patterns (highest value first)

| Rank | Pattern | Where it lives in openclaw | Why FERAL needs it | Effort | Becomes |
|---|---|---|---|---|---|
| 1 | **Two-lane cooldown state machine** with active-window immutability + per-model scope | `agents/auth-profiles/usage.ts:374–627` | FERAL's flat cooldown map regrows the cooldown on every retry and is not shared across processes. P0 the moment we run more than one Brain process. | L | **W19** |
| 2 | **Per-key API rotation** | `agents/api-key-rotation.ts:40–72` | Lets a power user attach two OpenAI keys; rotation absorbs single-key 429s without provider failover. | S (inside W19) | W19 |
| 3 | **Channel manifest + extension SDK boundary** | `extensions/*/openclaw.plugin.json` + `AGENTS.md:27–30` | The biggest unlock for community contributions. Today every new channel is in-tree Python. | XL | **W21** |
| 4 | **Per-agent auth profiles + cross-process refresh lock** | `agents/auth-profiles/path-resolve.ts:54` + `auth-profiles.ts:39–49` | Prevents `refresh_token_reused` storms when multiple FERAL processes share an OAuth profile; gives growth path to multi-identity. | L | **W16** |
| 5 | **Catalog metadata richness + deprecation chains** | `model-catalog/types.ts:29–47` | Lets the v2 picker show "gpt-4o → gpt-5.4 → gpt-5.5" instead of silently dropping deprecated rows. | M | **W20** |
| 6 | **Subagent allowlist + scope-cancel** | `agents/openclaw-tools.subagents.*.test.ts` | Production-tested version of FERAL's "main agent fires worker agents" mandate. | M | **W17** |
| 7 | **Process supervisor for external CLI** | `process/supervisor/supervisor.ts:41–291` | Future-proofs FERAL for external CLI integrations (Codex, Claude Code, ffmpeg pipelines, daemon restarts). | L | **W18** |
| 8 | **`SECURITY.md` + sandbox Dockerfiles** | `SECURITY.md:50–77`, `Dockerfile.sandbox*` | Closes the roadmap §3.7 P1 "what FERAL is not" ADR gap and gives the W22-class approval-bypass tests a published trust model. | L | **W22** |
| 9 | **OpenAI-compatible gateway endpoint** | `gateway/protocol/*` | Drop-in OpenAI base URL for IDEs/scripts; expands FERAL's reach without a new client. | M | **W24** |
| 10 | **RealtimeVoiceBridge contract + AudioSink decoupling** | `realtime-voice/session-runtime.ts:18–46` | Lets a session swap providers mid-call, lets a single bridge feed multiple sinks. | L | **W23** |

### 9.2 Anti-patterns explicitly NOT to copy

| Anti-pattern | Where it lives in openclaw | Why FERAL must not copy it |
|---|---|---|
| **WHAM probe to `https://chatgpt.com/backend-api/wham/usage`** | `auth-profiles/usage.ts:55,145–231` | Undocumented, ChatGPT-Codex-only endpoint; hostile-API risk; FERAL has no Codex backend. |
| **`pnpm`-tier monorepo tooling** | `AGENTS.md:46–53` | FERAL is mixed Python+JS+Swift+Rust. Retrofitting pnpm workspaces buys nothing and breaks everything. |
| **HackerOne / GHSA-style formal bounty program** | `SECURITY.md:79–90` | Adopt the in-scope/out-of-scope STRUCTURE; postpone the program until staff exist. |
| **`extensions/`-as-published-npm-packages** | `extensions/*/package.json` | FERAL distributes one wheel + one Tauri binary. Channel manifests stay in-tree. |
| **Per-channel `~/.openclaw/credentials/` flat files** | `AGENTS.md:138` | W9 is landing OS-keychain encryption; flat per-file plaintext would undo it. Stay with one encrypted blob per shape. |
| **`x-openclaw-scopes` reduces shared-secret auth** | `SECURITY.md:62` | Don't invent a new scope-on-shared-secret model in FERAL either; document the same trust contract. |

---

## 10. Proposed new workstreams (W16…)

These extend `ASOS/docs/AGENT_PROMPTS.md` §D. Each follows the existing W## block format. Dependencies on W1–W15 are noted; there are no circular dependencies among W16–W24.

---

### W16. Per-agent auth profiles + multi-shape credential store (P0; depends on W9)

```
You are working on FERAL-AI. Workstream W16. Your owned paths and the operating doctrine
are in docs/AGENT_PROMPTS.md (when it exists on origin/main).

CONTEXT
Today every credential lives in `~/.feral/credentials.json` — a single dict keyed by name.
The vault has no notion of "OAuth credential" vs "API key" vs "bearer token", no usage
stats, no cooldown state, no cross-process refresh lock.

openclaw splits these concerns:
  - Channel/provider creds in `~/.openclaw/credentials/`
  - Model auth profiles per-agent in `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`
  - AuthProfileStore holds three shapes: ApiKeyCredential, OAuthCredential, TokenCredential
    (`openclaw-main 2/src/agents/auth-profiles.ts:39–49`).
  - A cross-process file lock at `<state-dir>/locks/oauth-refresh/sha256-<hash>` prevents
    two agents racing a single-use refresh token
    (`openclaw-main 2/src/agents/auth-profiles/path-resolve.ts:37–61`).

DELIVERABLES
1. New module `feral-core/security/auth_profiles/` with submodules: types.py (ApiKey,
   OAuth, Token credential shapes + AuthProfileStore + ProfileUsageStats), store.py
   (load + save + with-lock atomic update), paths.py (per-agent path resolution),
   oauth_refresh_lock.py (cross-process file lock keyed by sha256(provider \0 profile_id)),
   usage.py (port the W19 cooldown state machine — coordinate with W19), external_auth.py
   (overlay external CLI credentials).
2. Migration in `vault.py`: on first read, detect a flat `credentials.json`, classify each
   value (OAuth shape if it has "refresh_token", API key otherwise), write to
   `~/.feral/agents/default/auth_profiles.json`, back up the original to `.bak.legacy`.
3. CLI: `feral key list --agent`, `feral key migrate`, `feral key rotate --provider`.
4. Tests: test_auth_profiles_oauth_refresh_lock.py (two simulated agents, only one HTTP
   refresh fires); test_auth_profiles_migration.py (round-trip from flat blob);
   test_auth_profiles_multi_agent.py (two agent ids hold disjoint OAuth tokens).

ACCEPTANCE
- All 3 test files pass.
- Manually: create `~/.feral/credentials.json` with one OAuth blob, start the brain, see
  the migration log line and the new file at the per-agent path.

PUSH PROTOCOL: see docs/AGENT_PROMPTS.md §E. Branch: feral/W16-per-agent-auth-profiles.
```

---

### W17. Subagent spawn contract + scope cancel (P0; independent)

```
You are working on FERAL-AI. Workstream W17.

CONTEXT
The user wants a "main agent fires worker agents" pattern. FERAL's orchestrator can call
its own tool_runner which can call back into orchestrator, but there is no allowlist of
which child kinds may be spawned, no scope_key-based cancel, no lifecycle-tested contract.

openclaw has the production-tested version of this pattern. Sample test names:
  src/agents/openclaw-tools.subagents.sessions-spawn.allowlist.test.ts
  src/agents/openclaw-tools.subagents.sessions-spawn.cron-note.test.ts
  src/agents/openclaw-tools.subagents.sessions-spawn.lifecycle.test.ts
  src/agents/openclaw-tools.subagents.sessions-spawn.model.test.ts
  src/agents/openclaw-tools.subagents.scope.test.ts

DELIVERABLES
1. `feral-core/agents/subagent_spawner.py`: spawn_subsession(parent_id, kind, *,
   scope_key, model_override) returns a child session id.
2. `feral-core/agents/subagent_policy.py`: per-parent allowlist of child kinds; default
   deny.
3. Wire-up: `feral-core/agents/orchestrator.py.spawn_subsession()` (additive method);
   when a parent's session lock is dropped, all children with matching scope_key are
   cancelled.
4. HTTP: POST `/api/sessions/{id}/spawn` (gated by Supervisor).
5. Tests mirror openclaw's names: test_subagent_allowlist.py, test_subagent_lifecycle.py,
   test_subagent_scope.py, test_subagent_model_override.py,
   test_subagent_steer_failure_clears_suppression.py.

ACCEPTANCE
- 5 new test files pass.
- Cancelling parent kills children within 200ms.
- Spawning a kind not in the parent's allowlist returns a clear error and is logged to
  the supervisor as decision="denied".

PUSH PROTOCOL: see §E. Branch: feral/W17-subagent-spawn.
```

---

### W18. Process supervisor for external CLI backends (P1; depends on W17)

```
You are working on FERAL-AI. Workstream W18.

CONTEXT
openclaw's `process/supervisor/supervisor.ts:41–291` manages real OS subprocesses with
overall + no-output timeouts, scope-cancel, PTY + child-spawn adapters, and an in-memory
RunRegistry. FERAL has no equivalent today; future external CLI integrations (Codex CLI,
Claude Code CLI, ffmpeg pipelines) need it.

DELIVERABLES
1. `feral-core/process/supervisor/__init__.py` exposing create_process_supervisor().
2. `process/supervisor/supervisor.py` mirroring openclaw's two timeout types (overall +
   no-output) and scope-cancel semantics.
3. `process/supervisor/registry.py` (RunRecord + RunRegistry).
4. `process/supervisor/adapters/{child,pty}.py`.
5. Tests: test_overall_timeout_kills, test_no_output_timeout_kills,
   test_scope_cancel_kills_all_children, test_registry_finalize_on_exit,
   test_pty_adapter_uses_login_shell.

ACCEPTANCE
- 5 tests green.
- No callers in this PR; the abstraction is shipped ready for W23 (voice) and any future
  integration.

PUSH PROTOCOL: see §E. Branch: feral/W18-process-supervisor.
```

---

### W19. Cooldown state machine + per-key rotation + Retry-After (P0; supersedes W15 lower-mechanism)

```
You are working on FERAL-AI. Workstream W19.

CONTEXT
`feral-core/agents/llm_provider.py:29–46` is linear retry on substring match. `:130–164`
is a flat cooldown map. Today: every retry within an active cooldown extends the recovery
window; counters never reset; cooldown state isn't shared across processes; no per-key
rotation; no Retry-After honor; no per-model scope.

openclaw's `auth-profiles/usage.ts` is the reference. Key design points:
  - Two lanes: cooldown (transient) vs disabled (billing/auth_permanent), with exponential
    base * 2^(errorCount-1) capped (`usage.ts:447–458`).
  - `keepActiveWindowOrRecompute` (`usage.ts:513–522`): retries within an active cooldown
    DO NOT extend the recovery time.
  - Per-model cooldown scope: rate_limit may be model-scoped; non-rate_limit failures
    are profile-wide and clear cooldownModel.
  - Failure window (24h): failures outside the window reset counters.
  - Cross-process file-lock store updates (`usage.ts:316–346`).
  - Per-key rotation (`api-key-rotation.ts:40–72`).

DELIVERABLES
1. Extract failover from llm_provider.py into feral-core/agents/llm_failover.py.
2. New feral-core/agents/llm_cooldown.py implementing the two-lane state machine.
3. Honor `Retry-After` header in HTTP errors.
4. Per-key rotation: a provider can have N keys (read from vault via W16); rotation
   absorbs single-key 429s before failover.
5. Cross-process coordination via the file lock from W16.
6. Refactor chat_with_failover to call the new modules.
7. Tests: test_llm_cooldown_state.py (two-lane behavior), test_llm_per_key_rotation.py,
   test_llm_retry_after.py, test_llm_active_window_immutable.py,
   test_llm_failure_window_reset.py, test_llm_per_model_scope.py.

ACCEPTANCE
- 6 new tests + the existing test_llm_failover.py and test_provider_cooldown_tracker*
  tests pass.
- Two simulated workers hitting one OpenAI key share cooldown state within 5s of the
  first failure (proving the cross-process lock works).

PUSH PROTOCOL: see §E. Branch: feral/W19-cooldown-state-machine.
```

---

### W20. Catalog metadata enrichment + deprecation chains (P1; depends on W1)

```
You are working on FERAL-AI. Workstream W20.

CONTEXT
W1 (PR #23) refreshed model_catalog.json to current frontier IDs (gpt-5.5, claude-opus-4-7,
gemini-3.1-pro-preview) but the row shape is still flat strings. openclaw's
`model-catalog/types.ts:29–47` shows the right shape: contextWindow, inputs (text/image/
document), reasoning, status (available/preview/deprecated/disabled), replaces[],
replacedBy, tags[].

DELIVERABLES
1. Extend feral-core/providers/model_catalog.json schema: each model becomes an object,
   not a string. Required fields: id, status. Optional: contextWindow, inputs[],
   reasoning, replaces[], replacedBy, tags[], cost{input,output,cacheRead,cacheWrite}.
2. Update feral-core/providers/catalog.py to load the new shape; back-compat read for
   legacy string entries during one release cycle.
3. New feral-core/providers/manifest_planner.py: plugins (W21) contribute catalog rows
   that the planner merges with mergeKey resolution.
4. v2 client: feral-client-v2/src/components/ProviderModelPicker.jsx renders the
   deprecation chain (gpt-4o → gpt-5.4 → gpt-5.5 with strikethrough on deprecated rows
   and an "upgrade to" affordance).
5. Tests: test_provider_catalog_metadata.py, test_provider_catalog_deprecation_chain.py,
   ProviderModelPicker.test.jsx.

ACCEPTANCE
- All 3 test files pass.
- Manually open the v2 picker; deprecated models render with the chain link.
- Running W1's existing tests still passes.

PUSH PROTOCOL: see §E. Branch: feral/W20-catalog-metadata.
```

---

### W21. Channel manifest + extension SDK (P0; depends on W8)

```
You are working on FERAL-AI. Workstream W21.

CONTEXT
FERAL today writes every channel as in-tree Python. openclaw treats every channel as a
manifest-driven extension (~140 extensions in extensions/*/openclaw.plugin.json). The
manifest declares: id, providers, providerAuthEnvVars, providerAuthChoices (oauth /
device-code / api-key, with priorities and CLI flags), capability contracts (speech,
realtime-voice, embeddings, etc.), and modelSupport hints.

The architectural rule (`openclaw-main 2/AGENTS.md:27–30`) is what makes 140 extensions
sustainable: extensions reach into core ONLY via the SDK barrel. We need the same rule
for FERAL.

DELIVERABLES
1. Define `feral-channel.manifest.json` schema. Required fields: id, providers,
   providerAuthEnvVars, capabilities (messagingProvider, voiceProvider, etc.).
   Optional: providerAuthChoices, modelSupport, contracts.
2. Create the loader feral-core/channels/loader.py that discovers manifests in the
   bundled directories and (later) third-party paths.
3. Create the SDK package feral-core/channels/sdk/__init__.py exposing the helpers
   channel code is allowed to call. Document the boundary in
   docs/contributing-channels.md.
4. Migrate the four shipping channels (Telegram, Slack, Discord, WhatsApp) to manifest
   form. Their Python implementations stay; the manifest captures the metadata.
5. Add a generic contract test test_channel_manifest_contract.py that runs the same
   send/receive smoke against any registered channel manifest.
6. Wire signed manifests through W8's verifier (any unsigned channel manifest requires
   `--allow-unsigned`).

ACCEPTANCE
- The four channel manifests load through loader.py.
- Capability registry returns the right messagingProviders/voiceProviders lists.
- Existing channel tests pass unchanged.
- New contract test runs against all four channels.

NOTE: This is XL effort. Should be split into 3 PRs: schema+loader, channel migration,
SDK+docs.

PUSH PROTOCOL: see §E. Branch: feral/W21-channel-manifest (or split per above).
```

---

### W22. SECURITY.md + sandbox Dockerfiles + approval-bypass tests (P0; depends on W8 + W9)

```
You are working on FERAL-AI. Workstream W22.

CONTEXT
The roadmap §3.7 P1 calls for a "what FERAL is not" ADR plus per-feature runbooks.
openclaw's SECURITY.md (`openclaw-main 2/SECURITY.md:50–77`) is the model: in-scope /
out-of-scope structure, fast-path triage gate, false-positive patterns, trusted-operator
boundary documented in plain English.

openclaw also ships dedicated sandbox Dockerfiles (Dockerfile.sandbox, Dockerfile.sandbox-
browser, Dockerfile.sandbox-common). FERAL has docker_sandbox.py and wasm_sandbox.py but
no shipped sandbox image.

DELIVERABLES
1. Author ASOS/SECURITY.md modeled on openclaw's structure. Include FERAL-specific
   in-scope/out-of-scope items. Reuse the shared single-trusted-operator threat model
   language.
2. ASOS/Dockerfile.sandbox: minimal image for tool-genesis-generated code execution.
3. ASOS/Dockerfile.sandbox-browser: Chromium-based image for AppSurface iframe rendering
   (W8's GenUI sandbox).
4. feral-core/security/sandbox_image.py: build helper + version pinning.
5. Approval-bypass tests under feral-core/tests/security/:
     - test_pairing_approval_bypass.py
     - test_twin_approval_bypass.py
     - test_executor_approval_bypass.py
     - test_mcp_approval_bypass.py
   Each demonstrates the boundary holds against an attempted bypass.

ACCEPTANCE
- SECURITY.md published with the openclaw-shaped sections.
- Both Dockerfiles build cleanly in CI.
- 4 approval-bypass tests pass.

PUSH PROTOCOL: see §E. Branch: feral/W22-security-and-sandbox.
```

---

### W23. RealtimeVoiceBridge contract + AudioSink decoupling (P1; depends on W12)

```
You are working on FERAL-AI. Workstream W23.

CONTEXT
openclaw's `realtime-voice/session-runtime.ts:18–46` defines a `RealtimeVoiceBridge`
contract and a separate `RealtimeVoiceAudioSink`. The bridge talks to the provider; the
sink consumes synthesized audio (device speaker, WebRTC peer, ffmpeg pipe). They're
decoupled so a single bridge can feed multiple sinks, and a session can swap bridges.

The mark strategy lever (`session-runtime.ts:18`):
  type RealtimeVoiceMarkStrategy = "transport" | "ack-immediately" | "ignore";
controls audio-frame backpressure / WS half-open recovery.

FERAL's voice path is per-provider Python with no shared bridge contract.

DELIVERABLES
1. feral-core/voice/bridge.py: Protocol class RealtimeVoiceBridge with the methods
   from openclaw (acknowledgeMark, close, connect, send_audio, send_user_message,
   set_media_timestamp, submit_tool_result, trigger_greeting).
2. feral-core/voice/audio_sink.py: Protocol class AudioSink (is_open, send_audio,
   clear_audio, send_mark).
3. Refactor openai_realtime.py and gemini_live.py to implement the bridge contract.
4. Update voice_router.py to construct (bridge, sink) pairs.
5. Add mark_strategy parameter for backpressure.
6. test_voice_bridge_contract.py: same suite runs against both providers.

ACCEPTANCE
- Both providers implement the same Protocol.
- W12's soak metrics do not regress on this branch.
- 1 new contract test passes.

PUSH PROTOCOL: see §E. Branch: feral/W23-voice-bridge.
```

---

### W24. OpenAI-compatible gateway endpoint (P1; depends on W22)

```
You are working on FERAL-AI. Workstream W24.

CONTEXT
External clients (Cursor, IDE plugins, scripts) often want a drop-in OpenAI base URL.
openclaw's `gateway/protocol/*` ships `POST /v1/chat/completions` and `POST /v1/responses`
backed by their orchestrator and gated by shared-secret bearer auth. The trust contract
is documented in `SECURITY.md:61–63`: shared-secret bearer = full operator access, no
scope reduction via custom headers.

DELIVERABLES
1. feral-core/api/routes/openai_compat.py: POST /v1/chat/completions and POST /v1/responses
   shims that route into the orchestrator under existing API-key middleware.
2. feral-core/agents/openai_request_translator.py: translate between OpenAI request shape
   and orchestrator's internal command shape.
3. tests/test_openai_compat_chat_completions.py: curl with Bearer $FERAL_API_KEY returns
   valid OpenAI-shaped response.
4. tests/test_openai_compat_responses.py: same for Responses API.
5. tests/test_openai_compat_scope_contract.py: assert no narrower scope via custom headers
   is honored on shared-secret bearer auth (matches W22's documented trust model).

ACCEPTANCE
- 3 tests pass.
- Manual: `curl -H "Authorization: Bearer $FERAL_API_KEY" http://localhost:9090/v1/chat/completions
  -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"ping"}]}'` returns a
  valid OpenAI shape.

PUSH PROTOCOL: see §E. Branch: feral/W24-openai-compat-gateway.
```

---

## Dependency graph (W1–W24)

```
                            W1 (catalog freshness, in flight) ─┐
                                                                │
                           W7 (version single-source, in flight)│
W2 (twin theatre, in flight) ─┐                                 │
W3 (mcp routes, in flight) ───┘                                 │
                                                                ▼
                                                              MAIN GREEN
                                                                │
W8 (GenUI signing) ─────────────► W21 (channel manifest)        │
W9 (vault encryption) ──┬────────► W16 (per-agent profiles) ────┤
                        └────────► W22 (SECURITY + sandbox)     │
                                                                │
W17 (subagent spawn) ───────────► W18 (process supervisor)      │
                                                                │
W12 (voice soak) ───────────────► W23 (voice bridge)            │
                                                                │
                                                                W19 (cooldown SM) ─► (W15 router builds on)
                                                                W20 (catalog meta) (after W1)
                                                                W22 ─► W24 (openai-compat)
```

Suggested dispatch order (after wave 1 lands):

1. **Wave 2 (cosmetic + foundation):** W4, W5, W6, W8, W9.
2. **Wave 3 (cooldown + auth + spawn):** W19, W16, W17.
3. **Wave 4 (security + catalog):** W22, W20.
4. **Wave 5 (extension + voice + gateway):** W21 (split into 3 PRs), W18, W23, W24.

W15 (router/budget) is not duplicated by W19; W15 is the high-level router, W19 is the low-level state machine W15 sits on. Land W19 first if both are in flight.

---

*This audit is a living artifact. Update it whenever openclaw ships a substantial change to one of the eight clusters or whenever a FERAL workstream lands that closes (or widens) one of the gaps. Section 9's ranked table is the source of truth for "what would buy the most production-readiness per unit of engineering effort"; if a workstream lands and its gap closes, strike it through here in the same PR.*
