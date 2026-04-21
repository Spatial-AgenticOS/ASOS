"""Track C — persona + workflow-pack loader contract.

Asserts the first-party manifests ship in the tree and that the
loader validates + returns them. Bad files must be skipped, not
crash the Brain boot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.persona_loader import (
    PersonaManifest,
    WorkflowPackManifest,
    default_personas_dir,
    default_workflow_packs_dir,
    load_personas,
    load_workflow_packs,
)


pytestmark = pytest.mark.no_auto_feral_home

EXPECTED_PERSONA_IDS = {
    "accessibility",
    "coding_assistant",
    "devops",
    "executive_assistant",
    "health_tracker",
    "home_ops",
    "journaling",
    "parental",
    "research_assistant",
    "security_analyst",
}

EXPECTED_WORKFLOW_IDS = {
    "code_review",
    "expense_sort",
    "invoice_ocr",
    "meeting_recap",
    "morning_briefing",
    "pr_triage",
    "standup_composer",
    "weekly_health",
    "weekly_home_check",
    "weekly_summary",
}


def test_first_party_personas_all_load():
    personas = load_personas(default_personas_dir())
    assert set(personas.keys()) == EXPECTED_PERSONA_IDS
    for persona in personas.values():
        assert isinstance(persona, PersonaManifest)
        assert persona.name
        assert persona.system_prompt
        assert persona.tool_permissions, (
            f"Persona {persona.agent_id} declares no tool_permissions"
        )


def test_first_party_workflow_packs_all_load():
    packs = load_workflow_packs(default_workflow_packs_dir())
    assert set(packs.keys()) == EXPECTED_WORKFLOW_IDS
    for pack in packs.values():
        assert isinstance(pack, WorkflowPackManifest)
        assert pack.steps, f"Workflow {pack.workflow_id} has no steps"
        for step in pack.steps:
            assert step.type, f"Workflow {pack.workflow_id} has a step with no type"


def test_loader_skips_malformed_manifests(tmp_path: Path):
    """One malformed manifest must not stop the rest from loading."""
    (tmp_path / "valid.json").write_text(json.dumps({
        "agent_id": "valid",
        "name": "Valid",
        "description": "ok",
        "system_prompt": "prompt",
        "tool_permissions": ["x"],
    }))
    (tmp_path / "broken.json").write_text("{ this is not json")
    (tmp_path / "wrong_shape.json").write_text(json.dumps({"something": "else"}))

    result = load_personas(tmp_path)
    assert list(result.keys()) == ["valid"]


def test_loader_returns_empty_dict_when_directory_missing(tmp_path: Path):
    assert load_personas(tmp_path / "does_not_exist") == {}
    assert load_workflow_packs(tmp_path / "does_not_exist") == {}
