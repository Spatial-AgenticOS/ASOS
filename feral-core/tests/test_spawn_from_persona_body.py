"""Persona-manifest spawn path for /api/agents/spawn.

Before this commit the route only read ``pattern_id``; the v2 Agents
page's "Spawn specialist from persona" button sent a full persona body
which was silently ignored. These tests pin the new contract:

* A persona body (``name`` + ``system_prompt`` present) creates a
  SpecialistAgent without needing a Mitosis TaskPattern or the LLM.
* The spawned specialist carries the supplied memory_filter +
  tool_permissions.
* Missing both ``pattern_id`` and the persona body returns an error
  with success=False.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture()
def client_with_mitosis(tmp_path: Path):
    """TestClient bound to a real AgentMitosisEngine (SQLite in tmp)."""
    from agents.agent_mitosis import AgentMitosisEngine

    engine = AgentMitosisEngine(db_path=str(tmp_path / "mitosis.db"))

    mock = MagicMock()
    mock.agent_mitosis = engine

    with patch("api.state.state", mock), patch("api.routes.agent_mitosis.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), engine


def test_spawn_from_persona_body_creates_specialist(client_with_mitosis):
    client, engine = client_with_mitosis
    r = client.post("/api/agents/spawn", json={
        "name": "Coding Assistant",
        "description": "Pair-programming specialist.",
        "system_prompt": "You are a senior software engineer...",
        "tool_permissions": ["coding_tools", "code_interpreter"],
        "memory_filter": "coding",
        "source_pattern": "user asks for code review",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True, body
    assert body["source"] == "persona_manifest"
    assert body["agent"]["name"] == "Coding Assistant"
    assert "coding_tools" in body["agent"]["tool_permissions"]
    assert body["agent"]["memory_filter"] == "coding"

    # Engine persisted the specialist and can list it.
    listed = engine.list_specialists()
    assert any(s.get("name") == "Coding Assistant" for s in listed), listed


def test_spawn_without_pattern_id_or_body_returns_error(client_with_mitosis):
    client, _ = client_with_mitosis
    r = client.post("/api/agents/spawn", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert "pattern_id" in body.get("error", "") or "system_prompt" in body.get("error", "")


def test_repeated_spawn_overwrites_same_agent(client_with_mitosis):
    """Clicking Spawn twice on the same persona updates the row, doesn't dup."""
    client, engine = client_with_mitosis
    persona = {
        "name": "Home Ops",
        "description": "Home automation specialist.",
        "system_prompt": "You run the house.",
        "tool_permissions": ["smart_home"],
        "memory_filter": "home",
    }
    r1 = client.post("/api/agents/spawn", json=persona)
    r2 = client.post("/api/agents/spawn", json={**persona, "description": "Updated"})
    assert r1.json()["success"] and r2.json()["success"]
    names = [s.get("name") for s in engine.list_specialists()]
    assert names.count("Home Ops") == 1, f"duplicate specialists: {names}"


def test_pattern_id_path_still_works(client_with_mitosis):
    """The old pattern_id path still returns the legacy behaviour.

    When the pattern doesn't exist (no LLM either) we expect a
    ``success: False`` — the route didn't crash, just can't spawn.
    """
    client, _ = client_with_mitosis
    r = client.post("/api/agents/spawn", json={"pattern_id": "pattern_nonexistent"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body.get("error") == "Spawn failed"
