"""Orchestrator + TaskFlow re-entry after consciousness resume.

Tests the end-to-end contract:

1. A running TaskFlow registers itself in ConsciousnessStore when
   TaskFlowRuntime.create_flow() is called.
2. Pausing + resuming via /api/consciousness/resume routes through
   state.taskflows.resume_flow() which flips the SQLite row back to
   QUEUED so the scheduler picks it up on its next tick.
3. kind=thought resume calls orchestrator.register_paused_thought()
   which queues the fragment; the next handle_command() call drains
   the queue and pre-pends it to conversation_history.

We don't spin up the full orchestrator here — we'd need an LLM
provider + skill registry + memory. Instead we exercise the public
surfaces directly: resume route, TaskFlowRuntime resume_flow, and
orchestrator.register_paused_thought + drain_paused_thoughts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture()
def store(tmp_path: Path):
    from memory.consciousness import ConsciousnessStore
    return ConsciousnessStore(tmp_path / "c.sqlite")


def test_resume_flow_routes_through_taskflow_runtime(store):
    """When a consciousness entity kind=flow is resumed, the route
    calls state.taskflows.resume_flow(flow_id) before flipping
    status. A fake runtime records the call."""
    from memory.consciousness import ConsciousnessEntity

    # Seed an active flow entity.
    store.record(ConsciousnessEntity(
        id="flow-abc", kind="flow", status="paused",
        summary="Weekly Summary",
        context_json={"step": 2, "steps": 5},
        owner_session_id="s1",
    ))

    called = []

    class _FakeRuntime:
        def resume_flow(self, flow_id: str):
            called.append(flow_id)
            return {"id": flow_id, "status": "queued"}

    mock = MagicMock()
    mock.consciousness = store
    mock.taskflows = _FakeRuntime()
    mock.intent_compiler = None
    mock.orchestrator = None

    with patch("api.state.state", mock), patch("api.routes.consciousness.state", mock):
        from api.server import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/api/consciousness/resume", json={"id": "flow-abc"})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["rehydrated"]["kind"] == "flow"
    assert body["rehydrated"]["method"] == "taskflow_resume_flow"
    assert called == ["flow-abc"]
    # Status really flipped to active.
    assert store.get("flow-abc").status == "active"


def test_resume_thought_registers_with_orchestrator(store):
    from memory.consciousness import ConsciousnessEntity

    store.record(ConsciousnessEntity(
        id="th-1", kind="thought", status="paused",
        owner_session_id="session-xyz",
        context_json={"text": "was going to finish that coffee review"},
        summary="mid-sentence thought",
    ))

    registered = []

    class _FakeOrch:
        def register_paused_thought(self, *, session_id, thought_id, text):
            registered.append({
                "session_id": session_id,
                "thought_id": thought_id,
                "text": text,
            })

    mock = MagicMock()
    mock.consciousness = store
    mock.taskflows = None
    mock.intent_compiler = None
    mock.orchestrator = _FakeOrch()

    with patch("api.state.state", mock), patch("api.routes.consciousness.state", mock):
        from api.server import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/api/consciousness/resume", json={"id": "th-1"})

    assert r.status_code == 200
    assert r.json()["rehydrated"]["method"] == "orchestrator_register_paused_thought"
    assert len(registered) == 1
    assert registered[0]["session_id"] == "session-xyz"
    assert "coffee" in registered[0]["text"]


def test_rehydration_failure_leaves_status_paused(store):
    """If the runtime's resume method raises, the entity stays
    paused so retries can re-run."""
    from memory.consciousness import ConsciousnessEntity

    store.record(ConsciousnessEntity(
        id="flow-bad", kind="flow", status="paused",
        summary="Bad flow",
    ))

    class _BrokenRuntime:
        def resume_flow(self, flow_id: str):
            raise RuntimeError("simulated downstream failure")

    mock = MagicMock()
    mock.consciousness = store
    mock.taskflows = _BrokenRuntime()

    with patch("api.state.state", mock), patch("api.routes.consciousness.state", mock):
        from api.server import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/api/consciousness/resume", json={"id": "flow-bad"})

    body = r.json()
    assert body["ok"] is False
    assert "simulated downstream failure" in body["reason"]
    assert store.get("flow-bad").status == "paused"


def test_orchestrator_register_and_drain_paused_thoughts():
    """Orchestrator's new register_paused_thought + drain_paused_thoughts
    survive idempotency + multi-session scoping."""
    from agents.orchestrator import Orchestrator
    from unittest.mock import MagicMock

    o = Orchestrator.__new__(Orchestrator)
    o._paused_thoughts = {}

    o.register_paused_thought(session_id="s1", thought_id="t1", text="one")
    o.register_paused_thought(session_id="s1", thought_id="t2", text="two")
    # Duplicate id — ignored.
    o.register_paused_thought(session_id="s1", thought_id="t1", text="duplicate")
    o.register_paused_thought(session_id="s2", thought_id="t1", text="other session")

    drained_s1 = o.drain_paused_thoughts("s1")
    assert [t["id"] for t in drained_s1] == ["t1", "t2"]
    assert drained_s1[0]["text"] == "one"  # dup didn't overwrite

    # Second drain on the same session yields nothing.
    assert o.drain_paused_thoughts("s1") == []

    # Other session still has its thought.
    assert len(o.drain_paused_thoughts("s2")) == 1


def test_resume_taskflow_endpoint_survives_brain_restart_simulation(tmp_path):
    """Full simulation: write a flow entity + snapshot the store,
    throw the store away, open a fresh store, restore from the
    snapshot, then resume. The entity rehydrates correctly.
    """
    from memory.consciousness import ConsciousnessStore, ConsciousnessEntity

    a = ConsciousnessStore(tmp_path / "a.sqlite")
    a.record(ConsciousnessEntity(
        id="flow-persisted", kind="flow", status="paused",
        summary="Across-restart flow",
        context_json={"step": 1, "steps": 3},
        owner_session_id="sess-1",
        ttl_seconds=3600,
    ))
    blob = a.snapshot()

    # Simulate restart: fresh store, restore.
    b = ConsciousnessStore(tmp_path / "b.sqlite")
    b.restore(blob)

    called = []

    class _Runtime:
        def resume_flow(self, fid):
            called.append(fid)

    mock = MagicMock()
    mock.consciousness = b
    mock.taskflows = _Runtime()

    with patch("api.state.state", mock), patch("api.routes.consciousness.state", mock):
        from api.server import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/api/consciousness/resume", json={"id": "flow-persisted"})

    assert r.json()["ok"] is True
    assert called == ["flow-persisted"]
    assert b.get("flow-persisted").status == "active"
