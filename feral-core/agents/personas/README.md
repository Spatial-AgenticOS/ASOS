# First-Party Agent Personas

Each JSON file here is a ``kind=agent`` registry manifest. They are
loaded by ``feral-registry/scripts/seed_first_party.py`` and appear in
the marketplace under the ``agent`` tab.

## Schema

```jsonc
{
  "agent_id": "short_snake_case_id",
  "name": "Human-Readable Name",
  "description": "One-sentence pitch. Shown in the marketplace card.",
  "system_prompt": "The actual persona text the LLM receives when this specialist is invoked.",
  "source_pattern": "A phrase that, when it recurs 5+ times, triggers the mitosis engine to propose this specialist.",
  "tool_permissions": ["skill_id_a", "skill_id_b"],
  "schedule": null,
  "memory_filter": null,
  "version": "1.0.0",
  "tags": ["coding", "productivity"]
}
```

- ``tool_permissions`` must be a subset of skill_ids that exist in
  ``feral-core/skills/manifests/``. Unknown skills are silently dropped
  at runtime.
- ``schedule`` is optional cron syntax. Null means on-demand only.
- ``memory_filter`` optionally scopes this persona's memory reads to a
  topic (e.g. "coding" only sees coding-related episodic entries).

## Shipping a new persona

1. Add a JSON file here.
2. Run ``python -m scripts.seed_first_party`` (Fly SSH or local registry).
3. Verify in the marketplace UI that it appears under ``kind=agent``.
