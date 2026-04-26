# W24d — sync-in-async fix + W9 migration fallback + mDNS event-loop + mintlify nav

Pre-implementation proposal per the W24d charter. Written before any source edits.

## A9 — sync-in-async coroutine leak

**Location.** `feral-core/agents/identity_loader.py`, lines 355–385 (method
`_memory_section`).

**What the code does today.**
```python
async_builder = getattr(self.memory, "build_context_for_llm_async", None)
sync_builder = getattr(self.memory, "build_context_for_llm", None)
if async_builder is not None:
    try:
        return asyncio.run(
            async_builder(session_id, query=..., max_tokens_budget=800, memory_filter=...)
        )
    except RuntimeError:
        logger.debug("Event loop already running — using sync memory builder")
    except Exception as exc:
        logger.debug(...)
if sync_builder is not None:
    ...
```
When `_memory_section` is invoked from code that is already running inside an
event loop (e.g. an async request handler that synchronously calls into the
identity loader's memory assembly path), Python first evaluates the arguments
to `asyncio.run(...)`. That evaluation calls `async_builder(...)`, which
produces a *coroutine object*. Only then does `asyncio.run(...)` raise
`RuntimeError("asyncio.run() cannot be called from a running event loop")`.
The coroutine reference is dropped without ever being awaited, so Python
emits `RuntimeWarning: coroutine '…' was never awaited` when it is
garbage-collected.

**Fix (one paragraph).** Detect a running loop *before* creating the
coroutine. We use `asyncio.get_running_loop()` (raises `RuntimeError` when
there is no loop) to decide: if a loop is already running we skip the async
branch entirely and fall through to the existing sync builder. If no loop is
running we keep the `asyncio.run(...)` call for the KG-aware path. This
leaves the public `build_context_for_llm_async` signature untouched (per the
owned-paths contract) and avoids any change to `memory/store.py` — the sync
sibling `MemoryStore.build_context_for_llm` already exists and is what we
want the sync path to use.

**Test.** `feral-core/tests/test_identity_loader_no_coroutine_leak.py` —
creates a stub memory store that exposes both `build_context_for_llm_async`
and `build_context_for_llm`, runs the memory assembly in a context where
`asyncio.get_running_loop()` succeeds (inside an `async def` test), and
asserts via `warnings.catch_warnings(record=True)` that no
`RuntimeWarning` containing "coroutine" and "never awaited" is emitted.
Additional assertion: the async builder's coroutine factory is never
called when a loop is running (recorded via a call counter on the stub).

**Risk.** Small — we only change the decision tree inside `_memory_section`,
which already has a sync fallback. Worst case the async path is reached less
often (only outside a running loop); the log messages are retained at the
same verbosity.

---

## A10 — W9 device-pairing migration fallback (UNIQUE column DROP)

**Location.** `feral-core/security/device_pairing.py`, method
`_migrate_legacy_plaintext_rows` — specifically the `ALTER TABLE
paired_devices DROP COLUMN token` call on lines 358–373.

**What the code does today.** After logging every legacy row to
`needs_rotation_log`, the migration attempts `ALTER TABLE paired_devices
DROP COLUMN token`. On SQLite 3.35+ this usually works, *but* SQLite's DROP
COLUMN is documented to fail when the column has a UNIQUE constraint (or
participates in an index used by a constraint). Pre-W9 schemas commonly
declared `token TEXT UNIQUE NOT NULL`. On those DBs the DROP raises
`sqlite3.OperationalError` ("cannot drop UNIQUE column"); the current
handler swallows it with a WARNING and leaves the `token` column in place,
so legacy plaintext values remain on disk indefinitely (they are scrubbed
to empty strings, but the column survives).

**Fix (one paragraph).** When `ALTER TABLE ... DROP COLUMN token` fails, run
the standard SQLite table-rebuild pattern inside a single transaction:
introspect the current columns + indexes, `CREATE TABLE
paired_devices_new(...)` with every current column *except* `token`
(preserving types, defaults, and the `device_id` PRIMARY KEY), `INSERT INTO
paired_devices_new (...) SELECT (...) FROM paired_devices`, `DROP TABLE
paired_devices`, `ALTER TABLE paired_devices_new RENAME TO paired_devices`,
then recreate the `idx_pd_token_lookup` and `idx_pd_expires_at` indexes.
Log `device_pairing.migration.unique_rebuild_ok` at INFO on success and
keep the existing WARNING from the failed `DROP COLUMN` as a breadcrumb
*before* the rebuild runs. If the rebuild itself raises, fall back to the
current empty-string behaviour so legacy operators never lose the ability
to boot — only the cleanup is deferred.

**Test.** `feral-core/tests/test_device_pairing_migration_unique.py` —
seeds a pre-W9 DB with a `token TEXT NOT NULL UNIQUE` column and two
legacy rows, constructs a `DevicePairingStore`, asserts: (a) the rebuild
path ran (`store.migration_summary["dropped_token_column"] is True`),
(b) the final schema has no `token` column and does have `token_hash`,
(c) both legacy device_ids are present in `needs_rotation_log`,
(d) no plaintext leaked into any table (grep the DB dump), (e) a fresh
`pair_device(...) / verify_device(token)` round-trip works on the
rebuilt table.

**Risk.** Medium — we rewrite the paired_devices table. We mitigate by:
running the rebuild inside `BEGIN … COMMIT`, copying only the columns
`PRAGMA table_info` actually reports (so we can't drop operator-added
columns), preserving the `device_id` PRIMARY KEY, and recreating the two
indexes `_init_db` itself creates (`idx_pd_token_lookup`, `idx_pd_expires_at`).
Existing `test_pairing_migration.py` suite (which uses a *non*-UNIQUE
legacy schema) must continue to pass unchanged.

---

## A8 — mDNS event-loop blocked

**Location.** `feral-core/services/mdns.py`, function `advertise_brain`
(lines 18–56).

**What the code does today.** `advertise_brain(port, name)` instantiates
a synchronous `zeroconf.Zeroconf()` and calls `zc.register_service(info)`
directly. Both are blocking network/socket calls; when invoked from
anywhere near the event loop's startup (e.g. the FastAPI/uvicorn startup
hook) they can hold the loop long enough for watchdogs to fire the
`EventLoopBlocked` exception that shows up in the maintainer's log.

**Fix (one paragraph).** `zeroconf.asyncio.AsyncZeroconf` is already
available (we verified against the installed `zeroconf>=0.131.0` pin in
`feral-core/pyproject.toml`, and its asyncio module imports cleanly).
Preferred approach: keep the existing synchronous `advertise_brain()`
for legacy callers (non-async boot paths still need it), and add a new
`advertise_brain_async(...)` coroutine that uses
`AsyncZeroconf().async_register_service(AsyncServiceInfo(...))`. Inside
the sync function, if we detect a running event loop we instead schedule
the blocking registration on `loop.run_in_executor(None, ...)` so that we
never hold the loop thread while zeroconf negotiates the mDNS
advertisement. `stop_advertisement()` gains a symmetric async variant.
The fast-path (no running loop, e.g. a CLI tool) keeps the original
synchronous behaviour.

**Test.** `feral-core/tests/test_mdns_no_event_loop_blocked.py` —
uses monkeypatching to replace `zeroconf.Zeroconf` and
`zeroconf.asyncio.AsyncZeroconf` with stubs that sleep for ~400ms in
their `register_service` / `async_register_service` to simulate the
real blocking cost. The test runs under `asyncio.run()` with a
concurrently-scheduled "heartbeat" coroutine that samples
`loop.time()` every 10ms and records the largest gap between ticks.
Calls `advertise_brain_async(...)` (or the sync wrapper with a running
loop). Asserts: (a) the largest heartbeat gap stays below 500ms, and
(b) the returned registration handle is non-None.

**Risk.** Small — we add a code path rather than replace one. Existing
synchronous callers (CLI entrypoints) get the same behaviour as before.
We keep the fallback `except ImportError` branch for environments that
somehow lack `zeroconf.asyncio`.

---

## A4 — mintlify nav orphan pages

**Location.** `docs/mintlify/docs.json`, plus orphan mdx files under
`docs/mintlify/`.

**What the code does today.** `docs.json` contains eleven navigation
groups, but several mdx files created under W8/W9/W11/W12/W13 have no
entry in the `navigation.groups[].pages` arrays. Mintlify's PR-preview
build job marks every PR as 🟡 Building because the renderer can't
resolve the sitemap deterministically when orphans exist.

Current orphans discovered by inventory (`docs/mintlify/**/*.mdx` minus
entries already referenced in `docs.json`):

| Path | Workstream | Intended group |
| --- | --- | --- |
| `docs/mintlify/memory/chaos.mdx` | W11 | Memory (new) |
| `docs/mintlify/operations/soak.mdx` | W12 | Operations (expand existing) |
| `docs/mintlify/operations/metrics.mdx` | W13 | Operations (expand existing) |
| `docs/mintlify/genui/signing.mdx` | W8 | Security (new) |
| `docs/mintlify/genui/sandbox.mdx` | W8 | Security (new) |

The W9 `security/vault.mdx` and `security/pairing.mdx` pages named in
the charter have not been authored yet (there is no `docs/mintlify/security/`
directory on `origin/main` at the cutoff); the W8 security content was
authored under `docs/mintlify/genui/` rather than `docs/mintlify/security/`.
We keep the "Security" nav group but populate it with the existing
GenUI-security pages, and append a follow-up asking the W9 authors to
move/author the missing `security/vault.mdx` and `security/pairing.mdx`.

**Fix (one paragraph).** Edit `docs/mintlify/docs.json` to:
(1) add a new `Memory` group between "Marketplace" and "Hardware" with
`memory/chaos` as its single page; (2) expand the existing "Operations"
group to include `operations/soak` and `operations/metrics` alongside
`guides/observability` and `guides/federated-sync`; (3) add a new
"Security" group between "Connectivity" and "Native Apps" with
`genui/signing` and `genui/sandbox` (W8 GenUI-security pages).

**Test.** `scripts/check_mintlify_nav.py` — walks
`docs/mintlify/**/*.mdx` (excluding `snippets/` and `_*.mdx`), parses
`docs.json`, and asserts every mdx has a matching entry in
`navigation.groups[].pages`. Exits 1 with a `orphan: <path>` line per
missing entry. Run it locally after the `docs.json` edit.

**Risk.** Tiny. No code paths touch `docs.json`; the only breakage is a
malformed JSON (linter will catch) or a mistyped page slug (linter will
catch).

---

## Follow-ups (for `docs/AGENT_PROMPTS_FOLLOWUPS.md`)

1. W9 authors: `docs/mintlify/security/vault.mdx` and `security/pairing.mdx`
   are referenced by the charter but do not exist on `origin/main`. Create
   them (or move the appropriate content out of `docs/mintlify/genui/`).
   Once they land, update `docs.json` to point the Security group at
   them.
2. The "Operations" nav group used to be only `guides/*`; after W12/W13 it
   mixes `guides/*` with `operations/*`. If Mintlify supports nested groups
   in a future schema rev, consider splitting this into
   `Operations / Dashboards` + `Operations / Soak & Metrics`.
