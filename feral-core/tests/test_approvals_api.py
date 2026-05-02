"""REST coverage for execution-approval inbox routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.orchestrator import Orchestrator
from api.routes.approvals import router as approvals_router
from security.exec_approvals import ApprovalManager

pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def orchestrator() -> Orchestrator:
    reg = MagicMock()
    reg.skills = {}
    reg.find_skills_for_query = MagicMock(return_value=[])
    reg.get_tools_for_skills = MagicMock(return_value=[])
    orch = Orchestrator(
        skill_registry=reg,
        send_to_client=AsyncMock(),
        daemons={},
        memory=None,
        vision_buffer=None,
        perception=None,
        learner=None,
        approval_manager=ApprovalManager(db_path=":memory:"),
    )
    orch._send_text = AsyncMock()
    orch._try_genui_for_result = AsyncMock()
    orch._execute_tool_call_for_llm = AsyncMock(
        return_value={"success": True, "data": {"note": "executed"}},
    )
    return orch


@pytest.fixture
def approvals_client(orchestrator: Orchestrator):
    app = FastAPI()
    app.include_router(approvals_router)
    fake_state = SimpleNamespace(orchestrator=orchestrator)
    with patch("api.routes.approvals.state", fake_state):
        yield TestClient(app, raise_server_exceptions=False), orchestrator


def _new_pending(orchestrator: Orchestrator, session_id: str, tool: str = "browser__navigate") -> dict:
    pending = orchestrator.tool_runner.enforce_safety(
        tool,
        {"url": "https://example.com"},
        session_id=session_id,
    )
    assert pending is not None
    assert pending.get("status") == "pending_approval"
    return pending


def test_list_pending_approvals_and_session_filter(approvals_client):
    client, orch = approvals_client
    _new_pending(orch, "s1")
    _new_pending(orch, "s2")

    all_rows = client.get("/api/approvals")
    assert all_rows.status_code == 200
    payload = all_rows.json()
    assert payload["count"] == 2

    s1_rows = client.get("/api/approvals?session_id=s1")
    assert s1_rows.status_code == 200
    body = s1_rows.json()
    assert body["count"] == 1
    assert body["approvals"][0]["session_id"] == "s1"


def test_approve_pending_request_executes_tool(approvals_client):
    client, orch = approvals_client
    pending = _new_pending(orch, "s-approve")

    r = client.post(
        f"/api/approvals/{pending['request_id']}/approve",
        json={"session_id": "s-approve"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["status"] == "approved"
    assert body["request_id"] == pending["request_id"]
    orch._execute_tool_call_for_llm.assert_awaited_once()
    assert orch.tool_runner.get_pending(pending["request_id"]) is None


def test_reject_pending_request_does_not_execute_tool(approvals_client):
    client, orch = approvals_client
    pending = _new_pending(orch, "s-reject")

    r = client.post(
        f"/api/approvals/{pending['request_id']}/reject",
        json={"session_id": "s-reject"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["status"] == "rejected"
    orch._execute_tool_call_for_llm.assert_not_awaited()
    assert orch.tool_runner.get_pending(pending["request_id"]) is None


def test_approve_with_session_mismatch_returns_409(approvals_client):
    client, orch = approvals_client
    pending = _new_pending(orch, "s1")

    r = client.post(
        f"/api/approvals/{pending['request_id']}/approve",
        json={"session_id": "s2"},
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "session_mismatch"
    assert detail["pending_session_id"] == "s1"
    assert orch.tool_runner.get_pending(pending["request_id"]) is not None


def test_unknown_approval_returns_404(approvals_client):
    client, _orch = approvals_client
    r = client.post("/api/approvals/does-not-exist/approve")
    assert r.status_code == 404
