# Wave 5 — HARDENING (self-prompt for the conductor)

**Status:** drafted 2026-04-25, awaiting maintainer GO.
**Doctrine update:** every workstream below MUST follow `.cursor/rules/no-third-party-project-names-in-deliverables.mdc`. The reference architecture is named in `docs/OPENCLAW_LESSONS.md`; nowhere else.

## Operating principle change vs. Waves 1–4

Waves 1–4 optimised for **disjoint parallelism**: each agent owned a scoped slice and shipped fast. That worked for the breadth-first build-out. Wave 5 optimises for **technical depth**: every workstream below begins with a mandatory "investigate the live state of the world FIRST, propose, THEN implement" phase. No more "minimal fix that ships green CI"; explicitly: hardening means we go A→Z on each surface.

Per workstream, the agent must:

1. **Read the upstream provider's current docs** (the actual web page, not memory) before writing a single line.
2. **Run the live API** against the provider/dep with the user's real key (or a test key) to verify the current shape.
3. **Read the FERAL code that touches the surface** end-to-end — including every test, every adapter, every UI binding.
4. **Write a 1-page proposal** in the worktree as `_PROPOSAL.md` — what changes, why, what's deferred, what could break.
5. **Ship the work** in the proposal-validated scope. No silent scope creep.

## Phase A — Immediate hot-fixes (today, fan out as parallel subagents)

### A0. SHIPPED CRASH: `switch_provider()` TypeError on `base_url` kwarg (P0, conductor fixes directly in <10 min)

**Evidence (from the live v2026.5.0 log):**
```
File ".../api/routes/config.py", line 103, in update_config
    state.orchestrator.llm.switch_provider(new_provider, model=new_model, base_url=new_base, api_key=new_key)
TypeError: LLMProvider.switch_provider() got an unexpected keyword argument 'base_url'
```

Every "Save & switch" on the v2 Settings page 500s in v2026.5.0. W1 refactored `_PROVIDER_REGISTRY` to `(base_url, env_var)` 2-tuples but never updated `LLMProvider.switch_provider(self, provider, model="", api_key="")` at `feral-core/agents/llm_provider.py:892` to accept the `base_url` override that `api/routes/config.py:103` now passes.

**Fix (2 lines + a test):** add an optional `base_url: str = ""` kwarg to `switch_provider`; when non-empty, override `PROVIDER_BASES[provider][0]`. Ships as `v2026.5.1` patch release.

### A1. Provider model classification + chat-only filter (URGENT)

**Bug:** `feral-core/providers/openai_provider.py:114-117` and `deepseek_provider.py:79-81` execute `self._models = sorted(ids)` from the `/v1/models` API response. OpenAI returns 132 models including `babbage-002` (completions-only), `text-embedding-3-large`, `whisper-1`, `dall-e-3`, `tts-1`, `gpt-4o-realtime-preview`, etc. The v2 picker shows all 132 → user picks `babbage-002` → POST `/v1/chat/completions` with `model=babbage-002` → **400 Bad Request** (the user's reported error). Same shape on every adapter that wraps an OpenAI-compatible `/models` endpoint.

**Fix:**
- New `feral-core/providers/model_classes.py` exposing `ModelClass = Literal["chat","vision","reasoning","embedding","audio","image","video","completion-only","realtime","unknown"]` and `classify(provider_id, model_id) -> ModelClass`. Classification is deterministic from the model_id string (regex + per-provider rules — `babbage*` / `*-instruct` / `gpt-3.5-*` / `text-davinci-*` → `completion-only`; `text-embedding-*` → `embedding`; `whisper-*` → `audio`; `dall-e-*` → `image`; `gpt-*-realtime-*` → `realtime`; `gpt-5*` / `gpt-4*` / `claude-*` / `gemini-*-pro` / `deepseek-v4-*` → `chat`; `o1-*` / `*-thinking` / `gemini-*-thinking` / `deepseek-reasoner` / `deepseek-v4-pro` (when `thinking` enabled) → `reasoning`).
- `BaseProvider.list_models(model_class: ModelClass | None = None)` — when set, the catalog filters; when omitted (legacy callers), returns the full set.
- `feral-core/providers/catalog.py::ProviderCatalog.list_models()` propagates the filter and stores the classifier output beside the cached IDs.
- `feral-client-v2/src/pages/Settings.jsx` calls the API with `?class=chat` for the dropdown next to the chat composer; future per-skill pickers can request `class=vision` etc.
- Acceptance: `pytest tests/test_provider_model_classes.py` (new, ≥30 cases — at least 3 per provider × 10 model patterns), assert `babbage-002` and `text-embedding-3-large` and `whisper-1` are NEVER in the chat-class result; assert `gpt-5.5` IS; live smoke against `OPENAI_API_KEY` if available, otherwise mocked `/v1/models` response fixtures captured today.
- Mintlify doc: `docs/mintlify/providers/model-classes.mdx`.

### A2. Vault key + provider selection persistence audit (URGENT)

**Bug:** user pastes API key in Settings → picks model → "Save & switch" → leaves Settings → returns → key field is blank, model dropdown empty. Either: (a) v2 client reads from a different namespace than W9 vault writes to; (b) W9 vault namespace API write→read round-trip is broken when `FERAL_HOME` is unset and the OS keychain master can't be located; (c) the v2 picker reads from a stale `cached.last_refresh` instead of re-querying the vault on mount.

**Fix:**
- Add `feral-core/tests/test_vault_provider_persistence.py` (new) — end-to-end: hit `POST /api/providers/{id}/credentials` with a key + `POST /api/providers/{id}/select-model`; restart the brain in the same `FERAL_HOME`; hit `GET /api/providers/{id}` and assert the key + model survive.
- Trace every read site for `OPENAI_API_KEY`-shaped credentials post-W9 (W16 added per-agent paths; v2 client may still hit the legacy `~/.feral/credentials.json` shape via an old route).
- If the bug is in the API: fix the route. If in the v2 client: fix `Settings.jsx` to refetch on mount, not rely on the in-memory module cache.
- Acceptance: the new test plus a manual smoke (paste key → restart → key persists → model dropdown still populated).

### A3. Scrub openclaw mentions from shipped artifacts (sweep)

`grep -ril openclaw` across our repo (excluding `openclaw-main 2/`, `docs/OPENCLAW_LESSONS*.md`, `docs/AGENT_PROMPTS*.md`, `docs/critique.md`, and historical CHANGELOG entries) returned 30+ files: `SECURITY.md`, `feral-core/security/auth_profiles/**`, `feral-core/process/supervisor/**`, `feral-core/agents/{orchestrator,subagent_spawner}.py`, `feral-core/api/routes/sessions.py`, `feral-core/channels/manifest.py`, `feral-core/channels/manifest_schema.json`, `feral-core/tests/test_subagent_*.py`, `feral-core/tests/security/test_*_approval_bypass.py`, `feral-core/tests/test_process_supervisor_*.py`, `feral-core/tests/test_auth_profiles_*.py`, `docs/contributing-channels.md`, `TRACK_A_CHANNELS_PROVIDERS.md`.

**Fix:** mechanical replacement per `.cursor/rules/no-third-party-project-names-in-deliverables.mdc` "Replacement vocabulary" table. Each occurrence becomes either (a) a description of what FERAL does, in our own terms, or (b) a citation `(see docs/OPENCLAW_LESSONS.md §N)` if a citation is genuinely needed. CHANGELOG entries for 2026-04-25 and earlier stay untouched (honest history); the 2026.5.0 entry is the cutoff — any post-2026-04-25 wording follows the rule.

### A4. Mintlify nav consolidation + green build verified

**Bug:** W8 / W9 / W11 / W12 / W13 / W22 each landed mdx files under `docs/mintlify/{security,memory,operations}/*.mdx` but none are wired into `docs/mintlify/docs.json` nav. PR #31 Mintlify build stuck 🟡 Building.

**Fix:** add three groups to `docs/mintlify/docs.json` nav — Memory, Operations, Security — with the right page entries; rewrite any cross-links that point at internal `docs/OPENCLAW_LESSONS*.md` (they 404 on the docs site); verify the Mintlify build goes 🟢 on the PR before merging.

### A5. Reasoning-model parameter correctness (OpenAI gpt-5 + Anthropic claude-opus-4-7 + DeepSeek v4-pro)

**Evidence:** `gpt-5.5` returns 400 on every call. Root cause: we send `max_tokens` / arbitrary `temperature` but GPT-5 / o-series reasoning family requires `max_completion_tokens` and only allows `temperature=1` (or omit). Same class of bug on Anthropic extended thinking and DeepSeek v4-pro thinking mode.

**Fix:** per-provider "reasoning family" switch in each adapter. If the selected model is a reasoning variant:
- OpenAI: send `max_completion_tokens` not `max_tokens`; drop or force `temperature=1`; drop `top_p`, `presence_penalty`, `frequency_penalty`.
- Anthropic: include `thinking={"type":"enabled","budget_tokens":N}`; respect that `temperature` is bounded when thinking is on.
- DeepSeek: when `v4-pro` or explicit thinking enabled, send `extra_body={"thinking":{"type":"enabled"}}` and `reasoning_effort="high"` (or `"max"` for agent workloads); drop `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`.
- Gemini: for `-thinking` variants, set `generationConfig.thinkingConfig.enabled=True`.

**Acceptance:** live smoke against each provider's reasoning model lands 200 OK; legacy non-reasoning models keep working; a new test matrix `tests/test_reasoning_model_params.py` pins the fork per provider.

### A6. Live-validated model lists (kill the invented IDs from W1)

**Evidence:** `claude-opus-4-7` → 400 on `api.anthropic.com/v1/messages`. OpenRouter returns 404 for the IDs we hardcoded. W1 shipped "verified frontier IDs" that are NOT what the providers actually expose on 2026-04-25.

**Fix:** every provider adapter's bundled `_models` list gets re-seeded from a **live fetch** run against today's API (cached in `feral-core/providers/model_catalog.json` with `last_fetched` set to the actual fetch timestamp). The fetch is done by a script `scripts/refresh_provider_catalog.py` (new) that the conductor can re-run on demand; CI cron stays as W1 configured. Plus: every provider test fixture ships a snapshot of the real `/v1/models` response as `tests/fixtures/<provider>_models.json` so the filter logic in A1 is tested against reality, not invention.

### A7. Legacy `credentials.json` plaintext writer (P0 SECURITY REGRESSION)

**Evidence (from your v2026.5.0 log):**
```
2026-04-25 20:24:45,277 [INFO] [feral.vault] Credential stored: credentials.OPENAI_API_KEY
2026-04-25 20:24:45,278 [INFO] [feral.config] Credentials saved to /Users/mahmoudomar/.feral/credentials.json
```

W9 shipped encrypted-at-rest vault. But the LEGACY plaintext writer `feral.config` is **still firing after every key save** — writing the same key in cleartext to `~/.feral/credentials.json`. This is a P0: we advertised encryption-at-rest in v2026.5.0, we're still leaking. The fix may be as simple as finding the `config.save_credentials(...)` caller and routing it exclusively through the W9 vault.

**Fix:** find the legacy write site in `feral-core/config/*.py` (or `feral-core/cli/*.py`). Replace with a vault.set_credential call. Add a regression test that asserts `~/.feral/credentials.json` is NEVER written after the first boot. Add a one-shot boot migration that deletes any existing plaintext `credentials.json` (after confirming the vault has the same keys) — the W9 migration already moves it to `.bak.legacy`, so if the new regression is just re-creating it, that's the bug we're hunting.

### A8. OpenRouter vision capability flag fixed

**Evidence:** `Provider 'openrouter' does not support vision input` repeated 10+ times in the log. OpenRouter supports vision on most routed models; the flag is wrong in our adapter.

**Fix:** `OpenRouterProvider._capabilities` should include `"vision"` (openrouter is a proxy — vision is supported when the underlying model supports it; the adapter should pass vision content through and let the route decide). A smarter fix: the capability flag becomes model-dependent, resolved via the catalog.

### A9. `MemoryStore.build_context_for_llm_async` never awaited

**Evidence:** `/agents/identity_loader.py:370: RuntimeWarning: coroutine 'MemoryStore.build_context_for_llm_async' was never awaited`.

**Fix:** `identity_loader.py` sync path calls the async method without `await`. Either make the caller async OR expose a sync sibling `build_context_for_llm_sync()` on `MemoryStore`. The sync-fallback path already says "Event loop already running — using sync memory builder" so the sync sibling is the right move.

### A10. Device-pairing drop-column failure (W9 follow-up)

**Evidence:** `device_pairing.drop_column_unsupported: cannot drop UNIQUE column: "token" — leaving the legacy 'token' column in place`.

**Fix:** W9's migration used `ALTER TABLE ... DROP COLUMN`, which on SQLite < 3.35 + UNIQUE columns fails. Replace with the SQLite rebuild pattern (create new table without the plaintext column, copy rows, drop old, rename). Also log "migration successful" when the rebuild succeeds.

---

## Phase A dispatch plan (parallel subagents)

| Agent | Scope | Owned paths | Rough effort |
|---|---|---|---|
| **Conductor** | A0 (crash) + A4 (mintlify nav) | `feral-core/agents/llm_provider.py`, `docs/mintlify/docs.json`, new `test_switch_provider_base_url.py` | 20 min |
| **Subagent 1 — Models correctness (W24a)** | A1 + A5 + A6 + A8 | `feral-core/providers/**` (new `model_classes.py`, all adapters' `_models` + `refresh_models` + reasoning-fork), `feral-core/tests/test_provider_*`, `scripts/refresh_provider_catalog.py`, `tests/fixtures/<provider>_models.json` | XL, 1-2h |
| **Subagent 2 — Vault plaintext leak (W24b)** | A2 + A7 | `feral-core/security/vault.py` (read side), `feral-core/config/**` (find + kill the legacy `save_credentials` writer), `feral-core/cli/**` (same), `feral-core/tests/test_no_plaintext_credentials_json.py` (new) | M, 45 min |
| **Subagent 3 — openclaw scrub (W24c)** | A3 | Every file in the rg list: `SECURITY.md`, `feral-core/security/auth_profiles/**`, `feral-core/process/supervisor/**`, `feral-core/agents/{orchestrator,subagent_spawner}.py`, `feral-core/api/routes/sessions.py`, `feral-core/channels/{manifest,manifest_schema}.{py,json}`, `feral-core/tests/test_subagent_*.py`, `feral-core/tests/security/test_*_approval_bypass.py`, `feral-core/tests/test_process_supervisor_*.py`, `feral-core/tests/test_auth_profiles_*.py`, `docs/contributing-channels.md`, `TRACK_A_CHANNELS_PROVIDERS.md` | M, 45 min |
| **Subagent 4 — Async + migration bugs (W24d)** | A9 + A10 | `feral-core/agents/identity_loader.py`, `feral-core/memory/store.py` (additive sync sibling), `feral-core/security/device_pairing.py` (SQLite rebuild for UNIQUE drop), tests for each | M, 45 min |

All 4 subagents + conductor in parallel. When all lands on `main`, cut `v2026.5.1` and push to PyPI.

**Subagent doctrine (baked into every prompt below):**
- FIRST: visit the upstream provider docs (where applicable), hit the live API, read FERAL code end-to-end, write `_PROPOSAL.md` in your worktree before touching any source.
- Owned paths only. Cross-boundary edits append one-line followup to `docs/AGENT_PROMPTS_FOLLOWUPS.md`.
- **Never name openclaw or any third-party reference project in shipped artifacts.** See `.cursor/rules/no-third-party-project-names-in-deliverables.mdc`. Exempt: `docs/OPENCLAW_LESSONS*.md`, `docs/AGENT_PROMPTS*.md`.
- No CHANGELOG edits. No README test-count marker bumps (auto-maintained).
- Apply labels via REST API.

**Bug:** W8 / W9 / W11 / W12 / W13 / W22 each landed mdx files (security/genui.mdx, security/vault.mdx, security/pairing.mdx, memory/chaos.mdx, operations/soak.mdx, operations/metrics.mdx, security related). None are wired into `docs/mintlify/docs.json` nav. Mintlify build status on PR #31 was 🟡 Building, then never went green because the new pages exist but the nav doesn't reference them, AND any cross-link in those pages to `_OPENCLAW_LESSONS.md` 404s on the published docs site.

**Fix:** add three groups to `docs/mintlify/docs.json` — Memory, Operations, Security — with the right page entries; remove or rewrite any cross-links that point at non-published `docs/*.md` files; verify the Mintlify build goes 🟢 on the PR before merging. Acceptance: visit the Mintlify preview URL the bot posts on the PR and click into each new page; no 404, nav highlights correctly.

---

## Phase B — Deep model integrations (this week, parallel subagents)

Each "deep" workstream lands a complete adapter with all the provider's first-class features wired, not "minimal POST `/chat/completions`". The acceptance bar per provider is the table at the bottom of this doc.

### B1. DeepSeek V4 Pro/Flash deep integration (W25)

**Worth:** the user is paying for DeepSeek and the current adapter only ships `deepseek-chat` + `deepseek-reasoner` (both deprecating 2026-07-24 per upstream).

**Owned paths:**
- `feral-core/providers/deepseek_provider.py` (rewrite)
- `feral-core/providers/model_catalog.json` (deepseek section)
- `feral-core/agents/llm_provider.py` (registry entry shape)
- `feral-core/tests/test_deepseek_*.py` (new, ≥7 files — see acceptance)
- `docs/mintlify/providers/deepseek.mdx` (new)

**Read-only context:**
- The DeepSeek docs the user pasted in this conversation (the canonical reference; mirror it locally as `docs/providers/deepseek-api-spec.md` so future agents don't re-fetch from the web).
- `feral-core/providers/openai_provider.py` and `anthropic_provider.py` (your adapter inherits the OpenAI-compatible JSON envelope, plus the optional anthropic-compat base_url alternative).

**Deliverables (the deep set, not the minimal one):**

1. **Two base_url modes:** `https://api.deepseek.com` (OpenAI-compat) AND `https://api.deepseek.com/anthropic` (Anthropic-compat). Adapter exposes a `protocol: Literal["openai","anthropic"]` constructor arg.
2. **Two model identifiers:** `deepseek-v4-pro` and `deepseek-v4-flash`. Legacy `deepseek-chat` / `deepseek-reasoner` are aliased with a deprecation warning that fires once per process lifetime, removed from the picker after 2026-07-24.
3. **Thinking mode toggle** (`extra_body={"thinking": {"type": "enabled"|"disabled"}}`) wired through `BaseProvider.chat()`'s kwargs; default per-model: `enabled` for `v4-pro`, `disabled` for `v4-flash`. Reasoning effort selector (`reasoning_effort: "high"|"max"`) with FERAL's tiering: `high` for normal, `max` for orchestrator-spawned subagents (W17 hook).
4. **`reasoning_content` carry-over** in multi-turn: when a tool-call cycle is in flight, the adapter preserves `reasoning_content` between sub-requests; when a tool cycle completes, the adapter strips `reasoning_content` from the assistant message before the next user turn (per the upstream contract: omitting it = ignored, including it on a non-tool turn = ignored, including it on a tool turn after the model produced one = REQUIRED to avoid 400).
5. **Tool calls in thinking mode** with `strict: true` (Beta) wired through the existing FERAL tool schema — the adapter validates the tool JSON Schema against the supported subset (object/string/number/integer/boolean/array/enum/anyOf, $ref / $def, no `minLength` / `maxLength` / `minItems` / `maxItems`) and raises `UnsupportedToolSchema` with a clear message if a registered tool exceeds it. (Today FERAL's tools are simple enough; this is forward-looking guard.)
6. **JSON Output mode** (`response_format={'type':'json_object'}` + system-prompt convention "include the word 'json'") exposed via `chat(json_mode=True)`.
7. **Prefix completion** (Beta `base_url=https://api.deepseek.com/beta` + last message `prefix=True`) as a new `chat_with_prefix(prefix_text, stop_tokens)` method.
8. **FIM completion** (Beta `/completions` with `prompt` + `suffix`) as a new `complete_fim(prefix, suffix, max_tokens)` method.
9. **Context caching observation** — the adapter records `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` from `usage` and exposes them through the existing FERAL `LLMUsage` shape. Wire into the W13 observability metric `feral_llm_prompt_cache_{hit,miss}_total{provider="deepseek",model=...}`.
10. **Error code map** per upstream (400 invalid format, 401 auth, 402 insufficient balance, 422 invalid params, 429 rate limit, 500 server error, 503 overloaded). Each maps to a FERAL exception with a user-readable hint; 402 is special — it surfaces a "Top up at $URL" message in the v2 picker.
11. **Rate-limit backpressure** — DeepSeek's docs say "during keep-alive the connection stays open returning empty lines / SSE comments". The adapter must not interpret these as terminations; the streaming path tolerates `: keep-alive` SSE comments and empty lines for up to 10 minutes before timing out.
12. **Pricing in `_pricing`** — per the current pricing page (the agent must visit and fetch; do not invent numbers).
13. **CLI integration helpers (W7-style env block)** — emit a snippet for users who want to point Claude Code / OpenCode / FERAL CLI itself at DeepSeek's anthropic-compat endpoint. Document in `docs/mintlify/providers/deepseek.mdx` under "Use FERAL via DeepSeek" (also: "Use Claude Code via DeepSeek" is a customer-discovery story we want to advertise). **Do not name openclaw in this doc** per A3.

**Acceptance:**
- 7 new test files, all green: `test_deepseek_chat_basic.py`, `test_deepseek_thinking_mode.py`, `test_deepseek_tool_calls_in_thinking.py`, `test_deepseek_prefix_completion.py`, `test_deepseek_fim.py`, `test_deepseek_json_mode.py`, `test_deepseek_context_cache_metrics.py`.
- One live smoke (env-gated `FERAL_DEEPSEEK_API_KEY`) that hits the real API for each of the 7 features and asserts the expected response shape.
- `docs/mintlify/providers/deepseek.mdx` reachable + linted in the Mintlify build.

### B2. OpenAI deep audit (W26)

Today's adapter (`feral-core/providers/openai_provider.py`) does basic `/v1/chat/completions` and the broken `refresh_models()` from A1. Missing: structured outputs, prompt caching (cache_control), responses API, function strict mode, parallel tool calls, vision, audio, image generation, web search tool, file search tool, computer use, batch API, distillation, fine-tuning hooks. Most users don't need all of these but the chat-quality features matter NOW: **prompt caching** (50% off cached tokens), **structured outputs** (`response_format={"type":"json_schema"}`), **parallel tool calls** (default on, controllable), **vision input** (any chat call with `image_url`), and **the responses API** (`/v1/responses` is the modern surface for agentic loops).

**Owned paths:** `feral-core/providers/openai_provider.py`, `feral-core/providers/model_catalog.json`, new tests `feral-core/tests/test_openai_*.py`, `docs/mintlify/providers/openai.mdx`.

**Deliverables (the deep set):**
1. Verify the live model list against the OpenAI dashboard today; remove any deprecated/preview-graduated IDs from the bundled list.
2. Wire `prompt caching` — `/v1/chat/completions` automatically caches; surface `usage.cached_tokens` through FERAL's `LLMUsage`. Wire into W13 metrics.
3. Wire `structured outputs` (`response_format={"type":"json_schema","json_schema":{...}}`) as a new `chat(json_schema=…)` argument; validate the schema is a subset of OpenAI's strict-mode constraints before sending.
4. Wire `parallel tool calls` (default on; expose `parallel_tool_calls=False` for serialized chains).
5. Wire `vision` — `messages[i].content` becomes a list of `{type:"text",…}` / `{type:"image_url",…}` blocks; FERAL's `ChatMessage` gains a `parts: list[ContentPart] | None` optional field.
6. Wire the `responses API` (`POST /v1/responses`) as an alternative path the orchestrator can opt into for agentic loops — it has built-in tool-result handling and reduces our roundtrip count.
7. Map the error codes (insufficient_quota, model_not_found, context_length_exceeded — the last one triggers FERAL's W19 cooldown to mark the call as "context-bound" not "rate-bound").
8. Pricing freshness — fetched from current docs.
9. Tests (≥6 files): basic, structured outputs, parallel tool calls, vision input, responses API, prompt cache metrics observed.

### B3. Anthropic deep audit (W27)

Today: basic `/v1/messages`. Missing: extended thinking (`thinking={"type":"enabled","budget_tokens":N}`), prompt caching (`cache_control: {"type":"ephemeral"}` on system/messages), vision, computer use, message batching API, code execution tool, web search tool.

**Owned paths:** `feral-core/providers/anthropic_provider.py`, model_catalog, new tests, mintlify doc.

**Deliverables:**
1. Verify the live Claude model list (claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5 + any newer). Remove deprecated.
2. Wire **extended thinking** with budget_tokens; default per-model: opus → 32k, sonnet → 16k, haiku → off.
3. Wire **prompt caching** with `cache_control: {"type":"ephemeral"}` on the system block + the most recent N user messages. Surface `usage.cache_creation_input_tokens` / `cache_read_input_tokens` through FERAL's `LLMUsage`.
4. Wire **vision** — same `parts` contract as B2 #5.
5. Wire the **batch API** (`/v1/messages/batches`) for non-interactive workloads — the orchestrator W17 subagent path can opt into batching when a parent dispatches >= 10 children with the same kind.
6. Tests (≥6 files): basic, extended thinking, prompt cache, vision, batch dispatch, error codes.

### B4. Gemini deep audit (W28)

Today: basic generateContent. Missing: Live API (real-time multimodal), code execution tool, grounding (Google Search), structured output (`response_schema`), system instructions, function calling, file API for large attachments, thinking variants (gemini-2.0-flash-thinking-exp / gemini-3-thinking).

**Owned paths:** `feral-core/providers/gemini_provider.py`, model_catalog, new tests, mintlify doc.

**Deliverables:**
1. Verify live Gemini model list. Add the thinking variants.
2. Wire **system_instructions** as a first-class arg.
3. Wire **structured output** (`responseSchema` + `responseMimeType:"application/json"`).
4. Wire **function calling** — Gemini's tool schema differs from OpenAI's; map FERAL's tool descriptors via a small adapter layer.
5. Wire **code execution tool** as a new tool that the brain auto-registers when Gemini is selected.
6. Wire **grounding** (Google Search) as an opt-in switch; surface citation URLs in the chat response.
7. Wire **file API** for `>20MB` attachments; tie into FERAL's existing media pipeline.
8. Bridge to W12's voice soak harness for the **Live API** (real-time multimodal) under a separate W23 follow-up — out of scope for this PR.
9. Tests (≥6 files): basic, thinking, structured output, function calling, code execution, grounding, file upload.

### B5. Provider parity matrix (W29)

After B1-B4, author `docs/mintlify/providers/_parity-matrix.mdx` (and a Python `feral-core/providers/parity.py` source-of-truth that backs it). Columns: chat, vision, audio-in, audio-out, tools, parallel-tools, JSON mode, structured outputs, thinking/reasoning, prompt caching, batch API, web search, code execution, file upload, realtime, fine-tune. Rows: every adapter we ship. The matrix MUST be generated from `parity.py` (single source) so the docs can never drift.

---

## Phase C — Long-running agent efficiency (next week, sequenced)

Today, a long-running orchestrator session burns tokens uncontrollably: full context every turn, every tool exposed every call, no compaction, no caching. **Wave 5C** addresses this so the brain can run for hours without a disaster.

### C1. Token budget tracker + per-key spend cap (W30)

**Owned paths:** `feral-core/agents/budget_tracker.py` (new), `feral-core/security/auth_profiles/usage.py` (extend the W16 placeholder), HTTP `/api/budget`, `feral-client-v2` Settings → Budget tab, tests.

**Deliverables:** per-provider per-key `daily_usd_cap` (default $10/day, configurable); track via `usage.tokens_input * pricing.input + usage.tokens_output * pricing.output`; on overage, fail closed with a clear error AND emit a W13 metric `feral_budget_exceeded_total`. The v2 client surfaces the live cumulative spend per provider with a progress bar.

### C2. Context compaction (W31)

**Owned paths:** `feral-core/agents/context_compactor.py` (new), orchestrator wiring (additive method only).

**Deliverables:** sliding-window plus on-trigger summarization. The orchestrator inspects token count after each turn; when above threshold (60% of model context), it invokes a smaller LLM to summarize the oldest N turns into a compact assistant-ish system message and replaces those turns. Idempotent — a session can compact multiple times. The summary is persistent in memory for the session; on restart it's loaded as the bootstrap context.

### C3. Selective tool exposure (W32)

**Owned paths:** `feral-core/agents/tool_router.py` (new), orchestrator wiring.

**Deliverables:** the orchestrator's per-turn tool list is currently "all registered tools". Wire a small classifier (heuristic + optional small LLM) that reads the user's last turn and exposes only the relevant N tools. Falls back to "all" when uncertain. Cuts per-turn input tokens 30-60% in benchmarks documented in the PR.

### C4. Multi-tier model routing (W33)

**Owned paths:** `feral-core/agents/router.py` (the W15 placeholder — supersede), `feral-core/agents/llm_provider.py` (one new dispatch path).

**Deliverables:** small/cheap LLM (gpt-5.4-nano, claude-haiku-4-5, gemini-3-flash, deepseek-v4-flash) for tool dispatch + tool-result synthesis turns; large/expensive LLM (gpt-5.5-pro, claude-opus-4-7, gemini-3-pro, deepseek-v4-pro with thinking) for reasoning turns. Cost: each turn's "kind" classified by the orchestrator; routing table is user-configurable with sane defaults.

### C5. Memory tiering (W34)

**Owned paths:** `feral-core/memory/tiering.py` (new), memory manager wiring.

**Deliverables:** hot tier (last 4k tokens, full text), warm tier (summarised 16k window, last 24h), cold tier (semantic-search archive, all history). Per-call memory budget gives the orchestrator a tunable knob. Wire into W11's existing memory store — no schema break.

---

## Phase D — Hardening discipline (process change, applies to all future waves)

### D1. Mandatory "investigate first" preamble in every workstream prompt

Every Wave-5+ prompt MUST instruct the agent to:

```
BEFORE writing any code, do the following and write a 1-page _PROPOSAL.md in your worktree:
  (a) Visit the upstream provider's current documentation page (note today's date).
  (b) Verify the live API shape with a real or mocked request.
  (c) Read every FERAL file that touches the surface end-to-end (use ripgrep to find them).
  (d) Confirm the proposed scope does not regress any feature listed in feral-core/providers/parity.py (when it exists).
  (e) Stop and ask the conductor if anything in (a)-(d) contradicts the prompt.

ONLY after _PROPOSAL.md is written, begin implementation.
```

### D2. "Deep, not minimal" acceptance bar

For any new model integration, the bar is:

| Feature | Required? |
|---|---|
| Chat (non-streaming + streaming) | ✅ |
| Streaming with backpressure / keep-alive tolerance | ✅ |
| Tool calling | ✅ |
| Tool calling in thinking/reasoning mode | ✅ if provider supports |
| Vision (image input) | ✅ if provider supports |
| Structured output / JSON mode | ✅ if provider supports |
| Prompt caching observation | ✅ if provider supports |
| Error code map → FERAL exception types | ✅ |
| Rate-limit backpressure | ✅ |
| Live model list filtered to chat class | ✅ (this is the A1 contract) |
| Pricing entry up-to-date | ✅ |
| Live smoke test (env-gated) | ✅ |
| Mintlify doc | ✅ |
| W13 observability metrics wired | ✅ if W13.1 has shipped, else flagged as follow-up |

If a deliverable lands without a row above, the PR is rejected.

### D3. No third-party project names rule

`.cursor/rules/no-third-party-project-names-in-deliverables.mdc` is now active. Subagent prompts must include the verbatim line "Do not name openclaw or any third-party reference project in the artifact you are about to write." and the sweep must be re-run before every release cut.

### D4. CI gate for forbidden literals (W35)

Small linter under `scripts/check_no_third_party_names.py` + a CI step that fails if `openclaw` (case-insensitive) appears in any path NOT listed in the rule's exempt list. Acceptance: PR that adds a forbidden mention fails CI; PR that touches an exempt path passes.

---

## Sequence + dispatch plan

**Today (conductor):** A1 + A2 + A3 + A4 in a single PR, branch `feral/W24-hardening-hotfix`. Title: `W24: hardening hotfix — chat-only model filter, vault round-trip, openclaw scrub, mintlify nav`. Estimated ~3-4 hours of conductor + targeted subagent work.

**Tomorrow morning (Wave 5B fan-out):** B1 (DeepSeek deep) + B2 (OpenAI deep) + B3 (Anthropic deep) + B4 (Gemini deep) as 4 parallel subagents — fully disjoint owned paths. After they land, B5 (parity matrix) is a small follow-up I do directly.

**This week:** C1-C5 sequential (each builds on the previous; C5 depends on C2). Each gets its own subagent.

**Continuously:** D1 + D2 + D3 are doctrine updates that affect every prompt I write going forward; D4 is a small CI PR.

## Open questions for the user before I dispatch

1. **DeepSeek API key:** do you have one available locally for the live smoke test in B1, or should B1 ship with mocked fixtures only and we add the live smoke after you generate a key?
2. **Daily $ budget defaults:** $10/day per key reasonable, or different number?
3. **Long-running session token compaction:** at what % of model context do you want compaction to trigger — 60% (my default), or lower / higher?
4. **A4 mintlify nav:** should I propose nav entries you can review, or just ship them in the hotfix PR?
5. **C4 model routing defaults:** should the small-LLM tier prefer cost (cheapest available across all configured providers) or local-first (lmstudio / ollama if running, then cheapest cloud)?
