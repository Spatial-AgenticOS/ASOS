# THEORA Plugin & Skill SDK

This guide explains how **skills** plug into THEORA: declarative manifests, Python implementations, registration, security, testing, and publishing.

## Overview

A **skill** is a bundle of **endpoints** (capabilities) the agent can invoke via function-calling. The orchestrator selects tools from the skill registry, the **SkillExecutor** resolves credentials from the **vault** (never exposed to the LLM), runs HTTP templates or **Python** `execute()` handlers, and returns structured **data** for answers and **GenUI** (maps, charts, tables, graphs).

Use **Python skills** when you need retries, aggregation, non-REST protocols, or hardware daemons. Use **JSON manifests** for straightforward REST APIs with stable request shapes.

### How the agent uses skills

1. **Discovery**: Skills are registered at startup (`SkillRegistry.load_builtin_skills()`).
2. **Routing**: The orchestrator may filter tools by query (`find_skills_for_query`) or expose the full set.
3. **Call**: The model emits a function call; the runtime maps it to `(skill_id, endpoint_id)` and invokes `SkillExecutor.execute`.
4. **Result**: Sanitized JSON is returned to the model and may feed **GenUI** builders on the client.

Skills do not run arbitrary user code in the model—they are **curated tools** with schema-checked arguments.

## BaseSkill interface

Subclass `skills.base.BaseSkill` and implement:

| Concern | Purpose |
|--------|---------|
| `skill_id` | Passed to `super().__init__(skill_id=...)`; must match the manifest’s `skill_id` so the executor finds your class. |
| `name`, `description`, `safety_level` | Optional human metadata (strings). Align `safety_level` with org policy: `SAFE`, `WARN`, or `CRITICAL` (see Security). |
| Manifest alignment | Endpoints are defined on `SkillManifest` in code or JSON; each endpoint has an `id` the executor passes as `endpoint_id`. |
| `async execute(endpoint_id, args, vault) -> dict` | Return **`{"success": bool, "status_code": int, "data": ..., "error": ...}`** (or a dict that the executor normalizes). |

**`args`**: Parameters extracted from the model’s tool call (e.g. `q`, `units`).

**`vault`**: Map of `skill_id → API key` from `THEORA_KEY_<skill_id>` and related config. Use `get_api_key(vault, fallback_env="OPENAI_API_KEY")` for env fallbacks.

### Endpoints (conceptual)

Each endpoint should have:

- **`id`**: Stable string, e.g. `current`, `search`.
- **`description`**: Natural-language description (used in tool definitions for the LLM).
- **`params`**: List of `{ name, type, required, description, default?, enum? }` in manifests (`EndpointParam` in Python).

The registry builds OpenAI-style tools named `{skill_id}__{endpoint_id}`.

## When to use manifest-only vs Python

| Use manifest HTTP | Use Python `BaseSkill` |
|-------------------|-------------------------|
| Single REST call per endpoint | Multi-step orchestration or aggregation |
| Stable OpenAPI-like params | Custom auth refresh, pagination, GraphQL |
| No extra dependencies | Hardware / local IPC / `WS_EXECUTE` daemons |

You can ship **both**: a manifest documents the contract while Python provides the implementation for the same `skill_id`.

## Manifest format (HTTP / declarative)

Authoritative schema lives in `models/skill_manifest.py` (`SkillManifest`, `SkillEndpoint`, `BrandProfile`, `AuthConfig`). A minimal JSON-oriented example:

```json
{
  "skill_id": "weather",
  "version": "1.0.0",
  "author": "you",
  "brand": {
    "name": "Weather",
    "primary_color": "#4A90D9",
    "logo_url": "",
    "icon_set": "sf_symbols"
  },
  "description": "Get current weather",
  "auth": { "type": "api_key", "api_key_header": "appid" },
  "endpoints": [
    {
      "id": "current",
      "method": "GET",
      "url": "https://api.example.com/v1/current",
      "description": "Current conditions for a location.",
      "params": [
        { "name": "q", "type": "string", "required": true, "description": "City or lat,lon" }
      ],
      "returns_description": "temperature, conditions, lat, lon",
      "ui_hint": "map"
    }
  ],
  "categories": ["utility"],
  "trigger_phrases": ["weather"]
}
```

For thin HTTP wrappers, the executor injects auth and performs GET/POST. If a **Python** implementation is registered for the same `skill_id`, it runs **first** and can ignore the manifest URL.

`SkillManifest` also supports **flows** (`flows`), **crons** (`crons`), and **triggers** (`triggers`) for multi-step and scheduled automation—see `models/skill_manifest.py` for fields. Those features are interpreted by higher-level schedulers, not by `execute()` directly.

## Registration

1. **Python**: Decorate your class with `@register_skill` in `skills/impl/<module>.py` and import that module from `skills/impl/__init__.py` (or ensure it is imported at startup). The decorator registers the **instance** in `SKILL_IMPLEMENTATIONS`.
2. **JSON manifests**: Place `*.json` files under `skills/manifests/`. `SkillRegistry.load_builtin_skills()` loads them at startup.
3. **Marketplace**: Installed packages under `~/.theora/skills/<package>/` with a `manifest.json` are loaded by `SkillRegistry._load_marketplace_skills()` (see `skills/package.py`, `skills/marketplace.py`).

After adding a skill, restart the API or reload the registry so the identity workspace and tool lists stay in sync.

## Security

- **Vault**: Store secrets as `THEORA_KEY_<skill_id>` or via the BlindVault path used by the executor. The LLM never receives raw keys.
- **Safety levels**: Treat network, file, and execution tools as **WARN** or **CRITICAL**; require explicit approvals where your deployment uses `dangerous_tools` / execution tiers.
- **Fetch guard**: Outbound HTTP may be constrained by `security/fetch_guard.py` depending on deployment—keep base URLs allowlisted when required.

## Example: Weather skill (Python)

See `skills/impl/weather.py` and the built-in manifest `WEATHER_SKILL` in `models/skill_manifest.py`:

- Endpoints: `current`, `forecast`.
- Uses `OPENWEATHER_API_KEY` or `THEORA_KEY_weather_current` when set; otherwise falls back to **wttr.in** (no key).

Return payloads include **`lat` / `lon`** so clients can render **MapView** in GenUI.

## Testing with pytest

1. **Unit-test `execute()`** with a fake vault and `httpx.MockTransport` or `respx` to stub HTTP.
2. **Registry**: Instantiate `SkillRegistry`, `register()` a manifest, and assert `get_tools_for_skills` contains `weather_current__current`.
3. **Integration**: Run the API with a test client (`TestClient`) and invoke internal routes if you expose them.

Example:

```python
import pytest
from skills.impl.weather import WeatherSkill

@pytest.mark.asyncio
async def test_weather_current_requires_location():
    s = WeatherSkill()
    out = await s.execute("current", {}, {})
    assert out["success"] is False
```

## Publishing to the marketplace

1. **Package**: Create a directory with `manifest.json` (valid `SkillManifest`), optional WASM/assets, and optional Python wheel if you distribute code separately.
2. **Validate**: Check schema with Pydantic (`SkillManifest.model_validate`).
3. **Submit**: Use `MarketplaceClient` (`skills/marketplace.py`) per your environment’s registry URL and auth.
4. **Install**: Target `~/.theora/skills/<id>/` so the registry picks up `manifest.json` on the next load.

For internal teams, vendoring manifests under `skills/manifests/` or importing a private Python module is often simpler than a full marketplace publish.

## Execution order (SkillExecutor)

When the model calls `weather_current__current`, the executor:

1. Loads `SkillManifest` for `weather_current` and the endpoint `current`.
2. If `get_implementation("weather_current")` returns a `BaseSkill`, calls `execute("current", args, vault)` — **HTTP is skipped**.
3. Otherwise performs the HTTP request described by `method` + `url`, injecting auth from the vault when `auth` is configured.

Therefore Python skills **override** declarative HTTP for the same `skill_id`.

## Tool naming

- Public name: `{skill_id}__{endpoint_id}` (two underscores).
- `_theora_meta` on each tool carries `skill_id`, `endpoint_id`, `ui_hint`, and brand for clients.

## Versioning & compatibility

- Bump `version` on `SkillManifest` when you change params or semantics.
- Prefer additive endpoint IDs (`v2_search`) over breaking renames if external agents depend on old tool names.

## Troubleshooting

| Symptom | Check |
|--------|--------|
| Tool not in LLM list | Registry loaded? `state.skill_registry.skills` / restart API. |
| `execute` never runs | `skill_id` mismatch between manifest and `super().__init__(skill_id=...)`. |
| 401 from HTTP skill | `THEORA_KEY_<skill_id>` or manifest `auth` headers. |
| Python skill not found | Import module under `skills/impl/` so `@register_skill` runs. |

## GenUI hints

`ui_hint` on endpoints (`map`, `list`, `metric`, …) guides SDUI generation on the client. Return **JSON-serializable** `data` with stable keys (e.g. `lat`, `lon`, `days`) so renderers like `MapView` and `ChartView` can bind predictably.

---

## Environment variables (common)

| Variable | Role |
|----------|------|
| `THEORA_KEY_<skill_id>` | API key stored for declarative or Python skills |
| `OPENAI_API_KEY`, `GROQ_API_KEY`, … | LLM providers (separate from skills) |
| `THEORA_HOME` | Config directory (`~/.theora` default); marketplace skills live under `skills/` there |

Use env vars for local dev; production should prefer the credential store / BlindVault where configured.

---

**References**: `skills/base.py`, `skills/executor.py`, `skills/registry.py`, `models/skill_manifest.py`, `skills/impl/__init__.py`, `security/fetch_guard.py`.
