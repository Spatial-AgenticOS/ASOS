"""Contract tests for first-party agent persona + workflow pack seeds.

These tests assert:
1. Every JSON file in ``feral-core/agents/personas/`` parses and carries
   the required keys (``agent_id``, ``name``, ``description``,
   ``system_prompt``, ``tool_permissions``, ``version``).
2. Every JSON file in ``feral-core/workflows/`` parses and has a non-empty
   ``steps`` list where each step declares a ``type`` recognised by the
   TaskFlow runtime.
3. ``seed_first_party._load_agent_seeds`` and ``_load_workflow_seeds``
   discover these files and produce SeedItem entries under the ``agent``
   and ``workflow`` kinds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PERSONAS_DIR = REPO_ROOT / "feral-core" / "agents" / "personas"
WORKFLOWS_DIR = REPO_ROOT / "feral-core" / "workflows"


PERSONA_REQUIRED = {
    "agent_id", "name", "description", "system_prompt",
    "tool_permissions", "version",
}
WORKFLOW_REQUIRED = {"workflow_id", "name", "description", "steps", "version"}
# Step types the runtime understands — keep in sync with
# feral-core/agents/taskflow.py.
VALID_STEP_TYPES = {
    "noop", "sleep", "note.save", "wiki.compile", "memory.search",
    "http.get", "skill.invoke", "llm.chat", "condition",
}


def _persona_files():
    return sorted(PERSONAS_DIR.glob("*.json")) if PERSONAS_DIR.exists() else []


def _workflow_files():
    return sorted(WORKFLOWS_DIR.glob("*.json")) if WORKFLOWS_DIR.exists() else []


@pytest.mark.parametrize("path", _persona_files(), ids=lambda p: p.stem)
def test_persona_manifest_shape(path: Path):
    data = json.loads(path.read_text())
    missing = PERSONA_REQUIRED - set(data.keys())
    assert not missing, f"{path.name} missing keys: {missing}"
    assert isinstance(data["tool_permissions"], list)
    assert data["tool_permissions"], f"{path.name} has empty tool_permissions"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.stem)
def test_workflow_manifest_shape(path: Path):
    data = json.loads(path.read_text())
    missing = WORKFLOW_REQUIRED - set(data.keys())
    assert not missing, f"{path.name} missing keys: {missing}"
    steps = data["steps"]
    assert isinstance(steps, list) and steps, f"{path.name} has no steps"
    for i, step in enumerate(steps):
        assert isinstance(step, dict), f"{path.name} step[{i}] not a dict"
        assert step.get("type") in VALID_STEP_TYPES, (
            f"{path.name} step[{i}] unknown type: {step.get('type')!r}"
        )


def test_seed_loaders_pick_up_every_file():
    # Make the registry package importable for this test.
    sys.path.insert(0, str(REPO_ROOT / "feral-registry"))
    from scripts import seed_first_party as seeder  # type: ignore

    agent_seeds = seeder._load_agent_seeds()
    workflow_seeds = seeder._load_workflow_seeds()

    agent_files = _persona_files()
    workflow_files = _workflow_files()

    assert len(agent_seeds) == len(agent_files), (
        f"expected {len(agent_files)} personas loaded, got {len(agent_seeds)}"
    )
    assert len(workflow_seeds) == len(workflow_files), (
        f"expected {len(workflow_files)} workflows loaded, got {len(workflow_seeds)}"
    )
    assert all(s.kind == "agent" for s in agent_seeds)
    assert all(s.kind == "workflow" for s in workflow_seeds)


def test_expected_first_party_count():
    """At least 10 personas + 10 workflows per Track C success criterion."""
    assert len(_persona_files()) >= 10
    assert len(_workflow_files()) >= 10
