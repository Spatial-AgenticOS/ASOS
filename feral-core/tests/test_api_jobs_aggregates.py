"""/api/jobs aggregates TaskFlows + routines + specialists + drafts + daemons.

This is the single source of truth the v2 Home 'Right now' pane reads +
the Consciousness Layer writes into. If one source throws, the endpoint
still returns data from the others (each aggregator is try/except
wrapped). Tests confirm:

* TaskFlow in 'running' status surfaces as kind=taskflow with progress.
* Scheduled routine firing within the next hour surfaces as kind=routine.
* Mitosis specialists surface as kind=specialist with ready status.
* Tool Genesis pending drafts surface as kind=tool_genesis.
* Live HUP daemons surface as kind=daemon.
* Filter by kind narrows the returned set.
* A broken aggregator does NOT 500 the endpoint.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@dataclass
class _FakeJob:
    id: int
    description: str
    session_id: str
    created_at: float
    next_run: float
    enabled: bool = True
    cron_expr: str = "0 9 * * *"


class _FakeTaskflowRuntime:
    def __init__(self, flows):
        self._flows = flows

    def list_flows(self, *, status="", limit=25, session_id=""):
        if not status:
            return list(self._flows)
        return [f for f in self._flows if f.get("status") == status]


class _FakeCron:
    def __init__(self, jobs):
        self._jobs = jobs

    def list_jobs(self, session_id=None):
        return list(self._jobs)


class _FakeMitosis:
    def __init__(self, specialists):
        self._specialists = specialists

    def list_specialists(self):
        return list(self._specialists)


class _FakeToolGenesis:
    def __init__(self, drafts):
        self._drafts = drafts

    def get_pending_skills(self):
        return list(self._drafts)


class _FakeWs:
    def __init__(self, node_type, capabilities):
        self._feral_node_type = node_type
        self._feral_capabilities = capabilities


def _populated_state():
    mock = MagicMock()
    now = time.time()
    mock.taskflows = _FakeTaskflowRuntime([
        {
            "id": "flow-1", "title": "Weekly Summary",
            "status": "running", "session_id": "s1",
            "current_step": 2, "step_count": 7,
            "created_at": now - 60, "updated_at": now - 5,
        },
        {
            "id": "flow-2", "title": "Standup Composer",
            "status": "paused", "session_id": "s2",
            "current_step": 1, "step_count": 4,
            "created_at": now - 120, "updated_at": now - 30,
        },
    ])
    mock.cron_service = _FakeCron([
        _FakeJob(id=1, description="Morning brief", session_id="s1",
                 created_at=now - 86400, next_run=now + 600),
        _FakeJob(id=2, description="Far-future job", session_id="s1",
                 created_at=now - 86400, next_run=now + 7200),  # outside window
        _FakeJob(id=3, description="Disabled job", session_id="s1",
                 created_at=now, next_run=now + 300, enabled=False),
    ])
    mock.agent_mitosis = _FakeMitosis([
        {
            "agent_id": "coding_assistant",
            "name": "Coding Assistant",
            "tool_permissions": ["coding_tools"],
            "memory_filter": "coding",
            "tasks_completed": 3,
            "created_at": now - 3600,
        },
    ])
    mock.tool_genesis = _FakeToolGenesis([
        {
            "id": "draft-7",
            "name": "fetch_stock_price",
            "status": "pending_review",
            "created_at": now - 100,
            "risk_score": 0.2,
        },
    ])
    mock.daemons = {
        "feral-w300-1": _FakeWs("glasses", ["camera", "imu"]),
        "feral-wristband-1": _FakeWs("wearable", ["heart_rate"]),
    }
    return mock


@pytest.fixture()
def client_populated():
    mock = _populated_state()
    with patch("api.state.state", mock), patch("api.routes.jobs.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False)


def test_endpoint_returns_all_kinds(client_populated):
    r = client_populated.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 5
    kinds = {it["kind"] for it in body["items"]}
    assert {"taskflow", "routine", "specialist", "tool_genesis", "daemon"}.issubset(kinds)


def test_taskflow_progress_populated(client_populated):
    r = client_populated.get("/api/jobs?kind=taskflow")
    items = r.json()["items"]
    running = next(it for it in items if it["name"] == "Weekly Summary")
    assert running["status"] == "running"
    assert running["progress"] is not None
    assert 0.0 <= running["progress"] <= 1.0
    # Step detail preserved.
    assert running["detail"]["step"] == 2


def test_routine_near_window_only(client_populated):
    r = client_populated.get("/api/jobs?kind=routine")
    names = [it["name"] for it in r.json()["items"]]
    # The far-future and disabled ones are filtered out.
    assert "Morning brief" in names
    assert "Far-future job" not in names
    assert "Disabled job" not in names


def test_daemon_carries_real_node_type(client_populated):
    r = client_populated.get("/api/jobs?kind=daemon")
    items = r.json()["items"]
    glasses = next(it for it in items if "w300" in it["name"])
    assert glasses["detail"]["node_type"] == "glasses"
    assert "camera" in glasses["detail"]["capabilities"]


def test_broken_aggregator_does_not_500(client_populated):
    """If one source raises, the endpoint still returns the others."""
    from api.routes import jobs as jobs_route

    original = jobs_route.state.taskflows

    class _Explode:
        def list_flows(self, *a, **kw):
            raise RuntimeError("simulated failure")

    jobs_route.state.taskflows = _Explode()
    try:
        r = client_populated.get("/api/jobs")
        assert r.status_code == 200
        kinds = {it["kind"] for it in r.json()["items"]}
        # taskflow missing, rest still present
        assert "taskflow" not in kinds
        assert "specialist" in kinds
    finally:
        jobs_route.state.taskflows = original


def test_filter_by_kind_narrows(client_populated):
    r = client_populated.get("/api/jobs?kind=specialist")
    kinds = {it["kind"] for it in r.json()["items"]}
    assert kinds == {"specialist"}


def test_counts_by_kind_exposed(client_populated):
    r = client_populated.get("/api/jobs")
    counts = r.json()["counts_by_kind"]
    assert counts["daemon"] == 2
    assert counts["specialist"] == 1
    assert counts["tool_genesis"] == 1
