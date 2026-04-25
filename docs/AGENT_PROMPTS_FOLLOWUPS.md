# Agent Workstream Follow-ups

One-line follow-ups filed by worker agents per `docs/AGENT_PROMPTS.md`
§G. Each entry: `YYYY-MM-DD | WID | path:line | impact | proposed
workstream`.

## 2026-04-24

- 2026-04-24 | W1 | `feral-core/api/server.py:438-460` | W1 wired
  `ProviderCatalog.refresh_async()` into the Brain `startup()`
  background-task list (per §D.W1 step 3). `api/server.py` is an
  orange-zone file under §C.2; this single additive task should be
  re-reviewed by the Conductor and W3/W13 to confirm it does not
  conflict with their MCP-routes and `/metrics` blocks. No existing
  lines were modified.
- 2026-04-24 | W1 | `feral-core/providers/anthropic_provider.py:103-106` |
  `refresh_models()` is hardcoded to return the bundled `_models`
  list because Anthropic publishes no `/v1/models` endpoint. When that
  changes, swap to a live HTTPS fetch. Tracked separately so the
  research script (`scripts/research_providers.py`) can keep
  hand-curating in the meantime.
- 2026-04-24 | W1 | `feral-core/providers/model_catalog.json` |
  `xai`, `together`, `openrouter`, `groq`, `deepseek`, `moonshot`
  entries were not refreshed by W1 (out of scope — only the OpenAI /
  Anthropic / Gemini lists were prescribed). When provider
  research.yml runs the next time, those entries will roll forward
  automatically; track if any are still stale a week after merge.
