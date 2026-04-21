"""Track C — /api/agents/personas + /api/workflows/packs contract.

Exercises the new FastAPI routes with real persona + workflow manifests
from the tree. Uses a minimal BrainState patch so the routes see the
same data the Brain boot would produce.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.persona_loader import (
    default_personas_dir,
    default_workflow_packs_dir,
    load_personas,
    load_workflow_packs,
)


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture()
def client():
    personas = load_personas(default_personas_dir())
    packs = load_workflow_packs(default_workflow_packs_dir())

    mock = MagicMock()
    mock.personas = personas
    mock.workflow_packs = packs

    created = {"id": "flow-abc", "title": "Morning Briefing"}
    mock.taskflows = MagicMock()
    mock.taskflows.create_flow.return_value = created

    with patch("api.state.state", mock), patch("api.routes.personas.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), created


def test_list_personas_returns_all_first_party(client):
    c, _ = client
    r = c.get("/api/agents/personas")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 10
    ids = {p["agent_id"] for p in body["personas"]}
    assert "coding_assistant" in ids
    assert "home_ops" in ids
    assert "security_analyst" in ids


def test_get_single_persona(client):
    c, _ = client
    r = c.get("/api/agents/personas/coding_assistant")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "coding_assistant"
    assert body["system_prompt"]
    assert "coding_tools" in body["tool_permissions"]


def test_get_unknown_persona_returns_404(client):
    c, _ = client
    r = c.get("/api/agents/personas/no_such_persona")
    assert r.status_code == 404


def test_list_workflow_packs_returns_all_first_party(client):
    c, _ = client
    r = c.get("/api/workflows/packs")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 10
    ids = {p["workflow_id"] for p in body["packs"]}
    assert "morning_briefing" in ids
    assert "pr_triage" in ids


def test_get_single_workflow_pack(client):
    c, _ = client
    r = c.get("/api/workflows/packs/morning_briefing")
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_id"] == "morning_briefing"
    assert body["steps"]


def test_instantiate_workflow_pack_creates_taskflow(client):
    c, created = client
    r = c.post("/api/workflows/packs/morning_briefing/instantiate")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["workflow_id"] == "morning_briefing"
    assert body["flow"] == created


def test_instantiate_unknown_pack_returns_404(client):
    c, _ = client
    r = c.post("/api/workflows/packs/does_not_exist/instantiate")
    assert r.status_code == 404
