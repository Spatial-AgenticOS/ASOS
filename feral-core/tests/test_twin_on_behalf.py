"""Tests for TwinPolicy + TwinPolicyEngine + DigitalTwin.execute.

Confirms:
  * disabled domain    → denied
  * no policy          → queued (default draft_only)
  * draft_only         → queued in approval store
  * auto_send + pass   → executor called, execution recorded
  * outside window     → queued
  * daily cap reached  → queued
  * supervisor paused  → denied
  * requires_user_online + user offline → queued
  * REST: upsert / list / delete policies; approve / reject
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from agents.supervisor import Supervisor, SupervisorStore
from agents.twin_policy import (
    TwinPolicy,
    TwinPolicyEngine,
    TwinPolicyStore,
    _in_window,
    _parse_window,
)


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def engine(tmp_path):
    store = TwinPolicyStore(db_path=str(tmp_path / "twin.db"))
    sup_store = SupervisorStore(db_path=str(tmp_path / "sup.db"))
    sup = Supervisor(store=sup_store)
    return TwinPolicyEngine(store=store, supervisor=sup)


# ── window helpers ───────────────────────────────────────────────


def test_parse_window_ok():
    assert _parse_window("09:00-21:00") == (9, 0, 21, 0)


def test_parse_window_bad():
    with pytest.raises(ValueError):
        _parse_window("9am-9pm")


def test_in_window_daytime():
    now = time.strptime("2026-01-01 10:00", "%Y-%m-%d %H:%M")
    assert _in_window("09:00-21:00", now) is True
    assert _in_window("00:00-05:00", now) is False


def test_in_window_cross_midnight():
    now = time.strptime("2026-01-01 23:30", "%Y-%m-%d %H:%M")
    assert _in_window("22:00-06:00", now) is True
    now2 = time.strptime("2026-01-01 12:00", "%Y-%m-%d %H:%M")
    assert _in_window("22:00-06:00", now2) is False


# ── decide() ─────────────────────────────────────────────────────


def test_decide_no_policy_returns_queued(engine):
    d = engine.decide("respond_imessage")
    assert d["verdict"] == "queued"
    assert d["reason"] == "no_policy_default_draft"


def test_decide_disabled_returns_denied(engine):
    engine.store.upsert_policy(TwinPolicy(domain="x", mode="disabled"))
    d = engine.decide("x")
    assert d["verdict"] == "denied"


def test_decide_draft_only_returns_queued(engine):
    engine.store.upsert_policy(TwinPolicy(domain="x", mode="draft_only"))
    d = engine.decide("x")
    assert d["verdict"] == "queued"


def test_decide_auto_send_ok(engine):
    engine.store.upsert_policy(TwinPolicy(domain="x", mode="auto_send"))
    d = engine.decide("x")
    assert d["verdict"] == "allowed"


def test_decide_supervisor_paused_denies(engine):
    engine.store.upsert_policy(TwinPolicy(domain="x", mode="auto_send"))
    engine.supervisor.set_paused(True)
    assert engine.decide("x")["verdict"] == "denied"


def test_decide_outside_window_queues(engine):
    # Window that never matches "now" — use an impossible one-minute slot.
    now_min = time.localtime().tm_min
    unreachable = (now_min + 5) % 60
    window = f"{(time.localtime().tm_hour + 12) % 24:02d}:{unreachable:02d}-{(time.localtime().tm_hour + 12) % 24:02d}:{unreachable:02d}"
    engine.store.upsert_policy(TwinPolicy(domain="x", mode="auto_send", time_windows=[window]))
    assert engine.decide("x")["verdict"] == "queued"


def test_decide_daily_cap_reached(engine):
    engine.store.upsert_policy(TwinPolicy(domain="x", mode="auto_send", max_per_day=1))
    engine.record_execution("x")
    assert engine.decide("x")["verdict"] == "queued"
    assert engine.decide("x")["reason"] == "daily_cap_reached"


def test_decide_requires_user_online_when_offline(engine):
    engine.store.upsert_policy(TwinPolicy(domain="x", mode="auto_send", requires_user_online=True))
    engine.set_user_online_probe(lambda: False)
    assert engine.decide("x")["verdict"] == "queued"
    assert engine.decide("x")["reason"] == "user_offline"


# ── queue_for_approval / resolve ─────────────────────────────────


def test_queue_then_resolve(engine):
    row = engine.queue_for_approval("respond_imessage", "send", {"to": "sam", "text": "hi"})
    assert row.status == "pending"

    resolved = engine.resolve(row.approval_id, verdict="approved")
    assert resolved.status == "approved"


def test_resolve_unknown_returns_none(engine):
    assert engine.resolve("ghost", verdict="approved") is None


# ── DigitalTwin.execute ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_digital_twin_execute_respects_policy(engine):
    from agents.digital_twin import DigitalTwin
    twin = DigitalTwin(memory=MagicMock(), identity_loader=MagicMock(), llm=MagicMock())
    twin.set_policy_engine(engine)

    # disabled → denied
    engine.store.upsert_policy(TwinPolicy(domain="a", mode="disabled"))
    out = await twin.execute("a", "do", {"x": 1})
    assert out["status"] == "denied"

    # draft_only → queued
    engine.store.upsert_policy(TwinPolicy(domain="b", mode="draft_only"))
    out = await twin.execute("b", "do", {"x": 2})
    assert out["status"] == "queued"
    assert out["approval_id"]

    # auto_send + executor → executed
    engine.store.upsert_policy(TwinPolicy(domain="c", mode="auto_send"))
    executor = AsyncMock(return_value={"sent": True})
    out = await twin.execute("c", "do", {"x": 3}, executor=executor)
    assert out["status"] == "executed"
    executor.assert_awaited_once()
    # daily count went up.
    assert engine.store.daily_count("c") == 1


@pytest.mark.asyncio
async def test_digital_twin_execute_without_policy_engine_denies():
    from agents.digital_twin import DigitalTwin
    twin = DigitalTwin(memory=MagicMock(), identity_loader=MagicMock(), llm=MagicMock())
    out = await twin.execute("a", "b", {})
    assert out["status"] == "denied"
    assert out["reason"] == "policy_engine_not_wired"


# ── REST surface ─────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path):
    sup_store = SupervisorStore(db_path=str(tmp_path / "sup.db"))
    sup = Supervisor(store=sup_store)
    store = TwinPolicyStore(db_path=str(tmp_path / "twin.db"))
    engine = TwinPolicyEngine(store=store, supervisor=sup)

    mock = MagicMock()
    mock.twin_policy = engine
    mock.supervisor = sup
    with patch("api.state.state", mock), \
         patch("api.routes.twin.state", mock), \
         patch("api.routes.supervisor.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), engine


def test_rest_upsert_and_list_policies(client):
    c, engine = client
    r = c.post("/api/twin/policies", json={
        "domain": "respond_imessage",
        "mode": "draft_only",
        "time_windows": ["09:00-21:00"],
        "max_per_day": 5,
    })
    assert r.status_code == 200
    r2 = c.get("/api/twin/policies")
    assert r2.status_code == 200
    body = r2.json()
    assert len(body["policies"]) == 1
    assert body["policies"][0]["mode"] == "draft_only"


def test_rest_delete_policy(client):
    c, engine = client
    engine.store.upsert_policy(TwinPolicy(domain="x"))
    r = c.delete("/api/twin/policies/x")
    assert r.status_code == 200
    assert engine.store.get_policy("x") is None


def test_rest_approvals_lifecycle(client):
    c, engine = client
    row = engine.queue_for_approval("respond_imessage", "send", {"to": "s"})
    r = c.get("/api/twin/approvals?status=pending")
    assert r.json()["count"] == 1

    r2 = c.post(f"/api/twin/approvals/{row.approval_id}/approve")
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"


def test_rest_reject_unknown_404(client):
    c, _ = client
    r = c.post("/api/twin/approvals/ghost/reject")
    assert r.status_code == 404


def test_rest_status_reports_kill_switch(client):
    c, engine = client
    engine.store.upsert_policy(TwinPolicy(domain="x"))
    engine.queue_for_approval("x", "a", {})
    engine.supervisor.set_paused(True)
    r = c.get("/api/twin/status")
    assert r.status_code == 200
    body = r.json()
    assert body["policies"] >= 1
    assert body["pending_approvals"] >= 1
    assert body["supervisor_paused"] is True


def test_rest_upsert_bad_mode_returns_400(client):
    c, _ = client
    r = c.post("/api/twin/policies", json={"domain": "x", "mode": "telepathy"})
    assert r.status_code == 400


def test_rest_upsert_missing_domain_returns_400(client):
    c, _ = client
    r = c.post("/api/twin/policies", json={"mode": "draft_only"})
    assert r.status_code == 400
