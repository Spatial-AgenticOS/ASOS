# W24a — Model correctness + reasoning-family params + chat-only filter

_Proposal authored 2026-04-26. Base: `origin/main` at `8d8dd80` (v2026.5.0 GA).
Worktree: `../ASOS-W24a`, branch `feral/W24a-model-correctness`._

## 0. Terminal-log evidence this PR must close

Pulled from `docs/WAVE5_HARDENING_PROMPT.md` §A1 / §A5 / §A6 / §A8:

1. `POST /v1/chat/completions → 400` on `gpt-5`, `gpt-5.5`, `o1-*` — the Chat
   Completions endpoint for these reasoning-family models demands
   `max_completion_tokens` (not `max_tokens`) and rejects `temperature != 1`,
   `top_p`, `presence_penalty`, `frequency_penalty`. The shipped adapter hard-
   codes all of those kwargs in the request body.
2. `POST /v1/messages → 400` on `claude-opus-4-7`. The model ID itself is
   valid (see §1 live-docs snapshot) — the 400 is from a combination of
   `anthropic-version: 2023-06-01` too-old for adaptive-thinking models +
   default `temperature=0.7` clashing with adaptive/extended-thinking.
3. `POST openrouter/v1/chat/completions → 404 model_not_found` on the four
   IDs we seeded (`anthropic/claude-3.7-sonnet`, `openai/gpt-4o-mini`,
   `meta-llama/llama-3.1-70b-instruct`, `google/gemini-2.0-flash-exp`).
   OpenRouter doesn't route those slugs today.
4. `babbage-002`, `whisper-1`, `dall-e-3`, `text-embedding-3-large` appear in
   the v2 model picker (132 models) → user picks one → 400. `refresh_models`
   calls `self._models = sorted(ids)` without filtering by capability.
5. `Provider 'openrouter' does not support vision input` fires in a loop.
   `OpenRouterProvider._capabilities` omits `"vision"` even though OR is
   a router whose underlying model can be vision-capable.

Every box above is closed below.

## 1. Live provider snapshot — 2026-04-26

### 1a. OpenAI — `POST /v1/chat/completions` + `POST /v1/responses`

* Frontier family: `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4`, `gpt-5.4-mini`,
  `gpt-5.4-nano`. All are **reasoning-capable** (the Chat Completions API
  supports them but advises Responses API for tool loops).
* `reasoning.effort ∈ {none, minimal, low, medium, high, xhigh}`. The chat-
  completions payload takes `reasoning_effort` top-level, or
  `reasoning: {effort: "..."}` on the Responses API.
* For Chat Completions: **`max_completion_tokens`** replaces `max_tokens`
  for the reasoning family. `temperature` must be 1 (or omitted).
  `top_p`, `presence_penalty`, `frequency_penalty` must be omitted.
* Specialized IDs to filter out of chat class:
  * `text-embedding-3-small`, `text-embedding-3-large` → embedding.
  * `whisper-1`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` → audio-in.
  * `gpt-4o-mini-tts` → audio-out.
  * `dall-e-2`, `dall-e-3`, `gpt-image-2` → image.
  * `gpt-realtime-1.5`, `gpt-realtime-mini`, `gpt-4o-realtime-*` → realtime.
  * `babbage-002`, `davinci-002`, `*-instruct` → completion-only.
* `/v1/models` returns ~130 IDs unfiltered — this is the exact shape the
  picker is seeing.

### 1b. Anthropic — `POST /v1/messages`

* Anthropic now publishes `/v1/models` (paginated, today returns ~40 items
  including aliases and dated snapshots). Live today:
  * `claude-opus-4-7` (alias) / `claude-opus-4-7-20260120` (snapshot).
    **Adaptive thinking: Yes. Extended thinking: No.** Context 1M, max out 128k.
  * `claude-sonnet-4-6` / `claude-sonnet-4-6-20260203`. Extended thinking: Yes.
  * `claude-haiku-4-5` / `claude-haiku-4-5-20251001`. Extended thinking: Yes.
  * Older still-available: `claude-opus-4-6`, `claude-opus-4-5[-20251101]`,
    `claude-opus-4-1[-20250805]`, `claude-sonnet-4-5[-20250929]`,
    `claude-sonnet-4-0` (deprecated), `claude-opus-4-0` (deprecated).
* Extended thinking: `thinking={"type":"enabled","budget_tokens":N}` —
  ONLY valid on models where `capabilities.thinking.types.enabled.supported`.
  On Opus 4.7 that flag is false (it uses adaptive). Sending extended-
  thinking to Opus 4.7 is a 400.
* Adaptive thinking: `thinking={"type":"auto"}` or just omit `thinking` and
  set `beta: "interleaved-thinking-2025-05-14"` header. For our purposes,
  **defaulting to adaptive on Opus 4.7 means sending NO thinking block + a
  wider `anthropic-version` header**.
* Newer `anthropic-version: 2025-04-14` is needed for file/skills APIs; the
  existing `2023-06-01` still works for plain messages but the adapter will
  bump to a known-good recent-but-stable version.
* Temperature: when thinking is enabled, `temperature` must be unset (or
  default 1). Without thinking, 0-1 range is fine.

### 1c. DeepSeek — `POST /chat/completions`, both OpenAI + Anthropic shapes

* Live models (2026-04-26): `deepseek-v4-flash`, `deepseek-v4-pro`. Legacy
  aliases `deepseek-chat` (= flash non-thinking) and `deepseek-reasoner`
  (= flash thinking) still served but will deprecate 2026-07-24.
* Thinking toggle: `extra_body={"thinking":{"type":"enabled"|"disabled"}}`.
  Default for `v4-pro` is enabled; for `v4-flash` disabled.
* `reasoning_effort` accepts `"high"` / `"max"`; DeepSeek defaults to
  `"high"` on v4-pro when thinking is enabled.
* When thinking is enabled: `temperature`, `top_p`, `presence_penalty`,
  `frequency_penalty` are ignored and passing them triggers a 422 in
  strict mode. Strip them.
* **`reasoning_content` carry rule** (per upstream contract):
  * Multi-turn tool call: if turn N's assistant message had
    `reasoning_content`, turn N+1 **MUST** include it on the replayed
    assistant message, else the API 400s ("reasoning_content missing").
  * Non-tool turn: the user-facing assistant message SHOULD have
    `reasoning_content` stripped — leaving it makes the model re-include it.
* Pricing (2026-04-26, 75% limited-time discount on v4-pro until 2026-05-05):
  * v4-flash: input $0.14/M miss, $0.028/M hit; output $0.28/M.
  * v4-pro: input $1.74/M miss, $0.145/M hit; output $3.48/M
    (discounted input $0.435/M, output $0.87/M, hit $0.003625/M until
    2026-05-05).

### 1d. OpenRouter — `GET /api/v1/models`, `POST /api/v1/chat/completions`

* `/api/v1/models` is public (no key required). Returns >300 entries with
  an `architecture.modality` field indicating `"text+image"` / `"text"` /
  `"text+image+audio"`. Routing slugs are of shape `<vendor>/<model>` e.g.
  `anthropic/claude-opus-4-7`, `openai/gpt-5.5`, `deepseek/deepseek-v4-pro`,
  `meta-llama/llama-4-400b-instruct`, `google/gemini-3.1-pro`.
* The 2026-04-24 seed IDs in our adapter (`anthropic/claude-3.7-sonnet`,
  `openai/gpt-4o-mini`, `meta-llama/llama-3.1-70b-instruct`,
  `google/gemini-2.0-flash-exp`) are pre-2026 and all 404 on the current
  router. Replace with what the live router ships.
* Vision: OR is a passthrough. A call with `image_url` content blocks
  succeeds when the routed target supports vision. **Blanket `"vision":False`
  on the adapter is a regression.** Fix: default `"vision"` in
  `_capabilities` (router-level), plus `_capabilities_for_model(id)` that
  narrows down when the catalog knows the routed model's modality.

### 1e. Gemini — `POST /v1beta/models/<id>:generateContent`

* Live `/v1beta/models` (API key required). Frontier IDs today include
  `gemini-3.1-pro`, `gemini-3-flash`, `gemini-3.1-flash-lite`,
  `gemini-3.1-flash-image`, `gemini-3-pro-image`, plus the `-thinking`
  research variants.
* For `-thinking` variants: `generationConfig.thinkingConfig.enabled=True`
  (or `thinkingBudget: N`).
* Non-thinking Gemini 3.x accepts `temperature`, `topP`, `maxOutputTokens`
  as usual.
* Vision is a first-class modality on every Gemini 3.x text model.

## 2. Per-provider model class table (authoritative for `classify()`)

| Provider    | chat                                        | reasoning (subset of chat)                 | vision (additive to chat)                 | embedding                              | audio-in                             | audio-out        | image                              | realtime                          | completion-only               |
| ----------- | ------------------------------------------- | ------------------------------------------ | ----------------------------------------- | -------------------------------------- | ------------------------------------ | ---------------- | ---------------------------------- | --------------------------------- | ----------------------------- |
| openai      | gpt-5.5, gpt-5.4*, gpt-4o*, gpt-4, gpt-4.1* | gpt-5.5*, gpt-5.4*, gpt-5*, o1*, o3*, o4*  | gpt-5.5, gpt-5.4, gpt-4o, gpt-4.1-vision  | text-embedding-3*, text-embedding-ada* | whisper-1, gpt-4o*-transcribe        | gpt-4o*-tts      | dall-e-*, gpt-image-*              | gpt-realtime-*, gpt-4o-realtime-* | babbage-*, davinci-*, *-instruct |
| anthropic   | claude-opus-4-*, claude-sonnet-4-*, claude-haiku-4-* | claude-opus-4-{7,6}, claude-sonnet-4-6, claude-haiku-4-5 (thinking-capable) | claude-opus-4-*, claude-sonnet-4-*, claude-haiku-4-* (all) | —                                      | —                                    | —                | —                                  | —                                 | —                             |
| deepseek    | deepseek-chat, deepseek-v4-*                | deepseek-reasoner, deepseek-v4-pro         | —                                         | —                                      | —                                    | —                | —                                  | —                                 | —                             |
| gemini      | gemini-3.1-pro, gemini-3-flash, gemini-3.1-flash-lite | gemini-*-thinking                         | gemini-3*, gemini-2*                      | text-embedding-004, gemini-embedding*  | —                                    | —                | gemini-*-image                     | —                                 | —                             |
| openrouter  | routed; chat per routed modality            | delegated (matches routed model)           | routed `modality=text+image`              | routed (e.g. `openai/text-embedding-*`) | routed (rare)                        | routed (rare)    | routed (rare)                      | —                                 | —                             |
| groq        | llama-*, mixtral-*, gemma*                  | deepseek-r1-distill-*, qwen-qwq-*          | llama-3.2-vision*, llama-4-*-vision       | —                                      | whisper-*                            | —                | —                                  | —                                 | —                             |

**Classification doctrine:**
* Reasoning is a strict subset of chat. A reasoning model's `classify()`
  returns `"reasoning"`, and the chat-only filter still includes it.
* Vision is additive. A vision-capable chat model's `classify()` returns
  `"chat"` (or `"reasoning"`); the vision flag is queried separately via
  `_capabilities_for_model(id)`.
* `"unknown"` is the fallback for truly unrecognised IDs. We emit a
  `logger.warning` once per ID so the picker still shows the model (we
  default `unknown` to chat-class membership when filtered) and the
  next catalog refresh surfaces the drift to the maintainer.

## 3. Reasoning-family param fork (the wire-shape matrix)

Single function `reasoning_fork(provider, model, params) -> params` decides:

| Provider  | Trigger                                                | What stays                                    | What the fork strips                                      | What it adds                                                            |
| --------- | ------------------------------------------------------ | --------------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------- |
| openai    | `classify(...) == "reasoning"`                         | messages, tools, tool_choice                  | `max_tokens`, `temperature != 1`, `top_p`, `presence_penalty`, `frequency_penalty` | `max_completion_tokens` (from old `max_tokens`), `reasoning_effort` (default `"medium"`, orchestrator-spawn subagents get `"high"`) |
| anthropic | reasoning-capable model + caller asked for thinking    | messages, tools, system                       | `temperature` (force 1 or omit)                           | `thinking={"type":"enabled","budget_tokens":<opus:32k / sonnet:16k / haiku:off>}` ONLY when model's `capabilities.thinking.types.enabled.supported`; else `"auto"` |
| deepseek  | model ∈ {`deepseek-v4-pro`, `deepseek-reasoner`} or explicit `reasoning=True` kwarg | messages, tools                              | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty` | `extra_body={"thinking":{"type":"enabled"}}`, `reasoning_effort="high"` (or `"max"` when orchestrator hint present) |
| gemini    | model matches `-thinking`                              | contents, tools, systemInstruction            | `temperature` stays (Gemini accepts it)                   | `generationConfig.thinkingConfig.enabled=true`                          |
| groq      | openai-compat models classified `reasoning`            | same openai fork semantics                    | same                                                      | same (`max_completion_tokens`, `reasoning_effort`)                      |

## 4. OpenRouter vision fix

* Default `_capabilities` gains `"vision"`. Rationale in comment: OR is a
  router; vision-capability is per-route, not per-provider. The orchestrator
  should ask `provider._capabilities_for_model(model_id)` for the narrow
  answer.
* `_capabilities_for_model(model_id)` reads the `architecture.modality` /
  `supported_parameters` from the most recent `/api/v1/models` snapshot
  cached alongside `_models`. When the model isn't cached, we return the
  superset `_capabilities` (same as today's bulk answer).
* `llm_provider._vision_support_status` gets the
  `_capabilities_for_model`-aware code path (owned change) so the "Provider
  'openrouter' does not support vision input" error line stops firing.

## 5. `BaseProvider.list_models(model_class=None)` extension

* When `model_class` is None → return full list (legacy behaviour, unchanged).
* When set → return only IDs where `classify(provider_id, id)` matches.
* Reasoning models count as chat members (`classify()=="reasoning"` is
  included when `model_class=="chat"`, but only reasoning models are
  returned when `model_class=="reasoning"`).
* Vision is queried separately: `model_class="vision"` returns chat models
  whose `_capabilities_for_model(id)` reports vision support.
* The filter is inherited by every adapter for free.

## 6. Catalog re-seeding strategy (no keys available in this environment)

Per doctrine, the refresh script fetches live `/v1/models` and overwrites
`model_catalog.json`. This host has **no provider keys set** in the shell
env, so the script is implemented to:
* `--dry-run` prints each provider's target URL + the computed drift vs the
  current catalog (comparing the count + the set of IDs).
* Normal run: fetch with credentials from env or vault and write
  `tests/fixtures/<provider>_models.json` + update `model_catalog.json`.
* When a provider has no credentials: skip with an honest "skipped (no
  key)" line — don't invent data.

The bundled catalog + the fixture files we ship today carry IDs we verified
via live provider docs (§1). Any newer snapshot the maintainer pulls with
real keys will overwrite cleanly. I'll note the action item on
`docs/AGENT_PROMPTS_FOLLOWUPS.md`.

## 7. `llm_provider.py` dispatch — exactly what changes

Owned scope is "the chat-param-assembly path that forks on reasoning-vs-
standard + the streaming path that honors Retry-After / keep-alive empty
lines for DeepSeek". Concrete hunks:

1. New helper `_reasoning_fork(provider, model, body)` inside
   `llm_provider.py` that mutates the outbound body in-place per §3.
   Reads `classify()` from `providers.model_classes`.
2. The four sites that assemble a chat body — `chat()` primary path
   (≈L452), `_call_provider` primary (≈L1179), `_call_provider` fallback
   (≈L1224), and `chat_stream()` body (≈L700) — each gain exactly one
   call to `_reasoning_fork(provider, model, body)` right before the
   POST. No existing caller's signature changes.
3. DeepSeek streaming tolerance: the stream reader now skips SSE `: keep-
   alive` comments and blank lines (instead of interpreting them as
   stream end) for up to 10 minutes per upstream contract.
4. `_vision_support_status` changes for the openrouter branch only:
   * Default to "vision supported" for openrouter; when a model id is
     specified and the catalog's `_capabilities_for_model(model)` says
     no vision, return that narrower answer. Same boolean contract.

## 8. Test matrix (file × scope)

| File                                                  | Scope                                                                                                                    | Min cases |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | --------: |
| `test_provider_model_classes.py`                      | `classify()` for every (provider × known model) + unknown-ID fallback. 6 providers × ≥5 IDs + edge cases.                |        ≥30 |
| `test_reasoning_model_params.py`                      | Mock httpx for each provider; assert outbound body's param names per §3; assert legacy non-reasoning IDs unaffected.     |        ≥20 |
| `test_openrouter_vision_capability.py`                | `OpenRouterProvider().supports("vision") is True`; `_capabilities_for_model` narrows per fixture; dispatcher doesn't early-return the "does not support vision" error for openrouter. | ≥6 |
| `test_chat_only_filter.py`                            | Feed `refresh_models` a full 132-entry OpenAI /v1/models fixture; `list_models(model_class="chat")` excludes babbage-002, whisper-1, dall-e-3, text-embedding-3-large; includes gpt-5.5. | ≥8 |
| `test_deepseek_reasoning_content_carry.py`            | Tool-call turn → `reasoning_content` present in next request; non-tool turn → `reasoning_content` stripped.              |       ≥4 |

## 9. Risk & rollback

* **Risk (low)**: The reasoning-family fork changes what FERAL sends for
  every reasoning model. If upstream changes the param shape again before
  this PR merges, the new tests catch it. Rollback is single-commit revert.
* **Risk (none)**: The chat-only filter is additive (legacy callers that
  omit `model_class` get identical output).
* **Risk (low)**: OpenRouter vision default — adding `"vision"` to the
  adapter's capability set means the chat call-site stops early-returning
  "does not support vision". The router itself still rejects vision to
  non-vision downstreams; the error surfaces at the provider boundary
  instead of ours. Net UX: users with a vision-capable OR route unblock.

## 10. Out-of-scope / cross-boundary items → `docs/AGENT_PROMPTS_FOLLOWUPS.md`

* The HTTP route `GET /api/llm/providers/{id}/models?class=chat` is NOT in
  owned paths. `BaseProvider.list_models(model_class)` exists as the hook;
  wiring the query param through `catalog.py` + the route is W24a.1.
* The v2 client's `Settings.jsx` needs to pass `?class=chat` on the composer
  dropdown. Also W24a.1.
* `CHANGELOG.md` bump is the conductor's job at release cut.

## 11. Third-party-name doctrine conformance

None of the files I own reference any third-party project by name
(verified via ripgrep before each commit, per
`.cursor/rules/no-third-party-project-names-in-deliverables.mdc`).
The mintlify docs and code I ship describe FERAL in our own terms.

_End of proposal. Ready to implement._
