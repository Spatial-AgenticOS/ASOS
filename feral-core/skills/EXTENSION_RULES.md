# FERAL Extension Boundary Rules

> Codifies the contract between **feral-core** (the kernel) and **skill
> extensions** (plugins).  Inspired by OpenClaw's AGENTS.md discipline — every
> contributor and CI check should enforce these invariants.

---

## 1. Core Must Not Reference Specific Skills

Modules inside the core packages (`agents/`, `api/`, `gateway/`, `memory/`,
`config/`, `hardware/`, `perception/`, `security/`, `models/`) **must never**
import, reference, or branch on a concrete skill implementation.

```
# FORBIDDEN inside core
from skills.impl.weather import WeatherSkill
if skill_id == "weather": …
```

The only legitimate core-to-skill coupling is through the **public SDK
surface**:

| Symbol | Package | Purpose |
|--------|---------|---------|
| `BaseSkill` | `skills.base` | Abstract interface for Python-backed skills |
| `SkillManifest` | `models.skill_manifest` | Declarative schema for any skill |
| `register_skill` / `register_instance` | `skills.impl` | Registration decorators |
| `SkillRegistry` | `skills.registry` | Dynamic discovery and lookup |
| `SkillExecutor` | `skills.executor` | Invocation via `(skill_id, endpoint_id)` |

Core code may call `SkillRegistry.get_skill(skill_id)` and receive a
`BaseSkill` — it must treat the result as opaque and never downcast.

---

## 2. Extensions Use Only the Public SDK

A skill extension (whether shipped in `skills/impl/`, installed from the
marketplace, or loaded from `~/.feral/skills/`) must limit its imports to:

- **Standard library** and declared third-party dependencies.
- **`skills.base.BaseSkill`** — subclass and implement `execute()`.
- **`skills.impl.register_skill`** — register the class at import time.
- **`models.skill_manifest.SkillManifest`** — only if the extension
  programmatically builds its own manifest.

Extensions **must not** import from:

- `memory.*` (use the `vault` dict passed to `execute()` for secrets)
- `agents.*` (orchestration is not the skill's concern)
- `api.*` / `gateway.*` (skills do not own transport)
- `config.loader` (skills receive config through their manifest or vault)
- `security.*` internals (the executor enforces fetch guards externally)

If a skill needs data that only core can provide, propose a new parameter on
`execute()` or a new SDK helper — do not reach around the boundary.

---

## 3. No Hardcoded Extension Lists in Core

The dynamic registry (`SkillRegistry`) discovers skills at runtime through:

1. JSON manifests in `skills/manifests/`.
2. Marketplace packages in `~/.feral/skills/<id>/manifest.json`.
3. Python implementations registered via `@register_skill`.

Core **must not** maintain a static list of known skill IDs, capability names,
or conditional branches per skill.  The `try: import skills.impl.X` block in
`skills/impl/__init__.py` is the **sole** exception — it bootstraps built-in
implementations and must remain guarded by `except ImportError: pass` so that
any subset (or none) can be absent.

Adding a new built-in skill should require **exactly two touches**:

1. Add the manifest JSON to `skills/manifests/`.
2. Add the `try/except` import line to `skills/impl/__init__.py`.

No changes to the orchestrator, API server, or gateway.

---

## 4. Extensions Must Declare All Dependencies

Every extension that requires third-party packages must declare them so the
runtime (or marketplace installer) can resolve them before loading:

- **Marketplace packages**: list dependencies in `manifest.json` under the
  `dependencies` field (validated by `SkillPackage`).
- **Built-in Python skills**: guard imports with `try/except ImportError` and
  degrade gracefully, or add the dependency to the appropriate
  `[project.optional-dependencies]` group in `pyproject.toml`.

An extension that crashes at import time due to a missing dependency is a
**bug in the extension**, not in core.

---

## 5. Extensions Must Pass Schema Validation

Every `manifest.json` must validate against `SkillManifest`
(`models.skill_manifest`) before the registry accepts it:

- Required fields: `skill_id`, `version`, `brand`, `description`, `endpoints`.
- Each endpoint must have `id`, `description`, and well-typed `params`.
- `trigger_phrases` and `categories` should be non-empty for discoverability.

The `SkillPackage.load()` and `SkillRegistry.load_from_file()` paths enforce
Pydantic validation.  CI should run `SkillManifest.model_validate(data)` on
every manifest in the tree.

---

## 6. Extensions Must Not Access Internals

Skills operate in a **sandboxed execution context**:

| Resource | Access | How |
|----------|--------|-----|
| API keys / secrets | Read-only | `vault` dict in `execute()` |
| HTTP | Allowed | Own `httpx`/`aiohttp` calls (subject to fetch guard) |
| File system | Scoped | `FERAL_HOME` or temp dirs only |
| Memory store | **Forbidden** | No direct `memory.store` access |
| Orchestrator state | **Forbidden** | No `agents.orchestrator` import |
| Database handles | **Forbidden** | No raw SQLite/DB connections from core |

If a skill needs to persist state across calls, it should write to its own
namespaced directory under `~/.feral/skills/<skill_id>/data/` or use the vault.

---

## Enforcement

- **Code review**: PRs that add cross-boundary imports must be flagged.
- **CI lint rule**: `ruff` or a custom check can grep for forbidden import
  patterns inside `skills/impl/` and core packages.
- **Runtime guardrail**: `SkillExecutor` already mediates all calls — future
  versions may run extensions in a subprocess or WASM sandbox.

---

## Rationale

Keeping extensions decoupled from core internals ensures:

1. **Stability** — core refactors don't break third-party skills.
2. **Security** — skills can't exfiltrate secrets or corrupt state.
3. **Portability** — skills work across FERAL deployments (desktop, server,
   embedded) without environment-specific hacks.
4. **Testability** — skills are unit-testable with a fake vault and no core
   dependencies.
