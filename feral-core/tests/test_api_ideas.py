"""API contract tests for /api/ideas."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.ideas_engine import IdeasEngine, IdeasStore


pytestmark = pytest.mark.no_auto_feral_home


class FakeConsciousness:
    def __init__(self, entities):
        self._e = entities

    def list_active(self, **_):
        return list(self._e)


class FakeAboutMe:
    def __init__(self, facts):
        self._f = facts

    def list(self, **_):
        return list(self._f)


@pytest.fixture()
def client(tmp_path):
    store = IdeasStore(db_path=str(tmp_path / "ideas.db"))
    engine = IdeasEngine(
        store=store,
        consciousness=FakeConsciousness([]),
        about_me=FakeAboutMe([]),
    )
    mock = MagicMock()
    mock.ideas_engine = engine

    with patch("api.state.state", mock), patch("api.routes.ideas.state", mock):
        from api.server import app

        yield TestClient(app, raise_server_exceptions=False), engine


def test_today_empty(client):
    c, _ = client
    r = c.get("/api/ideas/today")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["ideas"] == []


def test_today_after_baseline_alert(client):
    c, engine = client
    alert = SimpleNamespace(
        metric_id="hr_resting",
        alert_type="anomaly",
        severity="warning",
        deviation_sigma=2.3,
        baseline_mean=58.0,
        current_value=72.0,
    )
    engine.handle_baseline_alert(alert)
    r = c.get("/api/ideas/today")
    body = r.json()
    assert body["count"] == 1
    assert body["ideas"][0]["kind"] == "health"


def test_accept_marks_idea(client):
    c, engine = client
    alert = SimpleNamespace(
        metric_id="steps",
        alert_type="trend",
        severity="info",
        deviation_sigma=1.5,
        baseline_mean=8000,
        current_value=2000,
    )
    idea = engine.handle_baseline_alert(alert)
    assert idea is not None
    r = c.post(f"/api/ideas/{idea.id}/accept")
    assert r.status_code == 200
    assert r.json()["success"] is True
    r2 = c.get("/api/ideas/today")
    assert r2.json()["count"] == 0  # accepted → removed from today pane


def test_accept_unknown_returns_404(client):
    c, _ = client
    r = c.post("/api/ideas/unknown/accept")
    assert r.status_code == 404


def test_dismiss_marks_and_suppresses(client):
    c, engine = client
    alert = SimpleNamespace(
        metric_id="hrv",
        alert_type="anomaly",
        severity="warning",
        deviation_sigma=2.1,
        baseline_mean=50.0,
        current_value=33.0,
    )
    for _ in range(3):
        idea = engine.handle_baseline_alert(alert)
        assert idea is not None
        r = c.post(f"/api/ideas/{idea.id}/dismiss")
        assert r.status_code == 200
    # Fourth alert should be suppressed via dismiss_weight >= 3.
    assert engine.handle_baseline_alert(alert) is None


def test_dismiss_unknown_returns_404(client):
    c, _ = client
    r = c.post("/api/ideas/unknown/dismiss")
    assert r.status_code == 404


def test_refresh_runs_triggers(client, tmp_path):
    store = IdeasStore(db_path=str(tmp_path / "ideas2.db"))
    engine = IdeasEngine(
        store=store,
        consciousness=FakeConsciousness(
            [
                SimpleNamespace(
                    id="x",
                    kind="intent",
                    summary="ship now",
                    updated_at=time.time(),
                    status="waiting_user",
                )
            ]
        ),
        about_me=FakeAboutMe([]),
    )
    mock = MagicMock()
    mock.ideas_engine = engine
    with patch("api.state.state", mock), patch("api.routes.ideas.state", mock):
        from api.server import app

        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/api/ideas/refresh")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        new_kinds = {i["kind"] for i in body["new_ideas"]}
        assert "work" in new_kinds


def test_503_without_engine():
    mock = MagicMock()
    mock.ideas_engine = None
    with patch("api.state.state", mock), patch("api.routes.ideas.state", mock):
        from api.server import app

        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/api/ideas/today")
        assert r.status_code == 503
