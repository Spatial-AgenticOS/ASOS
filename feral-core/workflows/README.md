# First-Party Workflow Packs

Each JSON file here is a ``kind=workflow`` TaskFlow pack. They are
loaded by ``feral-registry/scripts/seed_first_party.py`` and appear in
the marketplace under the ``workflow`` tab.

## Schema

```jsonc
{
  "workflow_id": "short_snake_case_id",
  "name": "Human-Readable Name",
  "description": "One-sentence pitch.",
  "schedule": "cron expression or null for on-demand",
  "version": "1.0.0",
  "tags": ["morning", "productivity"],
  "steps": [
    {
      "type": "skill.invoke",
      "skill_id": "calendar",
      "endpoint": "list_today",
      "args": {}
    },
    {
      "type": "llm.chat",
      "prompt_template": "Summarise today's meetings in 3 bullets: {{ previous_output }}"
    }
  ]
}
```

## Step types (validated by `feral-core/agents/taskflow.py`)

| Step `type` | What it does |
|---|---|
| `noop` | Placeholder, records a timestamp. |
| `sleep` | Pause `seconds` before the next step. |
| `note.save` | Save `content` to memory with `tags`. |
| `wiki.compile` | Compile/refresh a wiki page. |
| `memory.search` | Query semantic memory with `q`, result feeds next step. |
| `http.get` | Fetch `url`, result feeds next step. |
| `skill.invoke` | Call `skill_id`/`endpoint` with `args`. |
| `llm.chat` | Send `prompt_template` (Jinja-ish) to the current LLM. |
| `condition` | Branch based on `expression` over `{{ previous_output }}`. |

## Shipping a new pack

1. Add a JSON file here with a unique ``workflow_id``.
2. Run ``python -m scripts.seed_first_party``.
3. Verify it appears under the Marketplace → Workflow tab.
4. User installs via ``feral install <id>``, which upserts it into their
   local TaskFlow runtime.
