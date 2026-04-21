# Track C — First-Party Personas + Workflow Packs (Week 4)

> Runs alongside Tracks A + B, gates Track D's Pillar E (security-analyst
> and home-ops specialist personas). Before this track the 10 persona
> JSONs + 10 workflow JSONs were registry-seed-only; nothing in the Brain
> runtime or the v2 UI consumed them.

## Why Track C exists

The 2026.4.17 release shipped ten persona manifests under
[`feral-core/agents/personas/`](feral-core/agents/personas/) and ten
workflow-pack manifests under [`feral-core/workflows/`](feral-core/workflows/).
The registry seed script
[`feral-registry/scripts/seed_first_party.py`](feral-registry/scripts/seed_first_party.py)
picked them up, but:

1. The Brain never loaded them on boot — `state.personas` /
   `state.workflow_packs` did not exist.
2. `/api/agents/list` returned only Agent Mitosis specialists from SQLite,
   so v2's Agents page showed zero of the 10 curated archetypes.
3. `/api/taskflows` listed runtime TaskFlow instances, not the 10
   curated templates.
4. `feral-core/cli/install.py`'s `kind == "agent"` path POSTed to
   `/api/mitosis/reload`, which did not exist. Hot-reload of installed
   personas was dead code.

Track C closes those four gaps while preserving the existing Mitosis
surface. Personas and Mitosis specialists are intentionally kept as two
separate concepts — personas are curated templates you spawn FROM,
specialists are the running agents that result.

## What ships in this track

### Commit 1 (this commit)

| Piece | File | Status |
|---|---|---|
| `PersonaManifest` / `WorkflowPackManifest` pydantic models + loaders that skip malformed JSON | [feral-core/agents/persona_loader.py](feral-core/agents/persona_loader.py) | shipped |
| Brain boot loads both dicts into `state.personas` + `state.workflow_packs` | [feral-core/api/state.py](feral-core/api/state.py) | shipped |
| REST routes `/api/agents/personas[/:id]`, `/api/workflows/packs[/:id]`, `POST /api/workflows/packs/:id/instantiate` | [feral-core/api/routes/personas.py](feral-core/api/routes/personas.py) | shipped |
| Loader contract tests (malformed-file skip, directory-missing, full-catalog shape) | [feral-core/tests/test_persona_loader.py](feral-core/tests/test_persona_loader.py) | shipped |
| Route contract tests (list + single + 404 + instantiate + 404) | [feral-core/tests/test_api_personas.py](feral-core/tests/test_api_personas.py) | shipped |
| v2 `Agents` page gets a `Personas` tab as default + "Spawn specialist from persona" button that POSTs to the existing `/api/agents/spawn` | [feral-client-v2/src/pages/Agents.jsx](feral-client-v2/src/pages/Agents.jsx) | shipped |
| v2 `Flows` page gets a `Packs` tab with "Install as TaskFlow" button that POSTs to the new instantiate route | [feral-client-v2/src/pages/Flows.jsx](feral-client-v2/src/pages/Flows.jsx) | shipped |
| v2 smoke tests for both new tabs | [feral-client-v2/src/__tests__/pages/](feral-client-v2/src/__tests__/pages/) | shipped |

### Follow-up PRs (queued)

- **Hot-reload route**: implement `POST /api/personas/reload` so
  `feral-core/cli/install.py`'s install path can refresh
  `state.personas` without restarting the Brain. Matching route on
  `/api/workflows/packs/reload`. One-day job.
- **Per-persona custom `/api/chat` route**: allow the v2 Chat page
  (Threads pane) to open a thread bound to a persona — the persona's
  `system_prompt` + `tool_permissions` + `memory_filter` get injected
  into the orchestrator for that thread only. Depends on
  [orchestrator.py](feral-core/agents/orchestrator.py) growing a
  per-thread persona override.
- **Scheduled workflow packs**: a pack with `schedule` != null should
  auto-instantiate on its cron. Hook into the existing `cron_service`
  from `state.init()` so an installed pack fires without manual
  "Install as TaskFlow" clicks.
- **Fourth-party persona contribution flow**: anyone can drop a JSON
  into `~/.feral/personas/` and Track C's loader should merge that
  directory with the first-party one. Small patch to `load_personas`.

## Success criteria

- [x] 10 first-party personas load on boot — confirmed by
  `test_first_party_personas_all_load`.
- [x] 10 first-party workflow packs load on boot — confirmed by
  `test_first_party_workflow_packs_all_load`.
- [x] v2 Agents page lists all 10 personas in a dedicated tab.
- [x] v2 Flows page lists all 10 workflow packs in a dedicated tab.
- [x] Instantiating a pack from v2 creates a live TaskFlow via the
  existing `TaskFlowRuntime.create_flow` path.
- [ ] Installed-from-registry personas hot-reload without a Brain
  restart (follow-up PR).
- [ ] Chat threads can be bound to a persona (follow-up PR).
- [ ] Workflow packs with `schedule` auto-fire on cron (follow-up PR).

## Persona + workflow manifest shape (reference)

Both schemas mirror what
[`feral-registry/tests/test_seed_personas_workflows.py`](feral-registry/tests/test_seed_personas_workflows.py)
asserts. The loader's pydantic models use `extra="allow"` so future
manifest fields don't force a code change before the JSONs ship.

Persona (minimal):

```json
{
  "agent_id": "coding_assistant",
  "name": "Coding Assistant",
  "description": "Pair-programming specialist.",
  "system_prompt": "You are a senior software engineer...",
  "tool_permissions": ["coding_tools", "code_interpreter"],
  "schedule": null,
  "memory_filter": "coding",
  "version": "1.0.0",
  "tags": ["coding", "productivity"]
}
```

Workflow pack (minimal):

```json
{
  "workflow_id": "morning_briefing",
  "name": "Morning Briefing",
  "description": "...",
  "schedule": "0 7 * * 1-5",
  "version": "1.0.0",
  "tags": ["morning", "productivity"],
  "steps": [
    {"type": "skill.invoke", "skill_id": "calendar", "endpoint": "list_today", "args": {}},
    {"type": "llm.chat", "prompt_template": "..."}
  ]
}
```

## Dependencies outward

- [TRACK_D_ADVANCED.md](TRACK_D_ADVANCED.md) Pillar E requires
  `home_ops` + `security_analyst` personas surfaced at runtime and in
  the UI; this track delivers both.
- The new `POST /api/workflows/packs/:id/instantiate` route is the
  canonical way for Pillar D's remote teleop flows to "install a
  curated automation" from a QR code / share link in the future.

## Running the new surfaces locally

```bash
cd /Users/mahmoudomar/Desktop/thoera-mac/ASOS/feral-core
python -m pytest tests/test_persona_loader.py tests/test_api_personas.py -q

cd ../feral-client-v2
npx vitest run src/__tests__/pages/Agents.test.jsx src/__tests__/pages/Flows.test.jsx
npx vite build && cp -R dist/. ../feral-core/webui-v2/

# Then boot the Brain and open http://127.0.0.1:9090/agents — the
# Personas tab is the default. /flows exposes the Packs tab.
```
