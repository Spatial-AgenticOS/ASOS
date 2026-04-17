"""
Tests for the Ambient surface API routes (briefing, snapshot, next_event).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.no_auto_feral_home]


def _make_mock_state():
    """Minimal BrainState mock for ambient endpoints."""
    s = MagicMock()
    s.orchestrator = MagicMock()
    s.sessions = {}
    s.perception = MagicMock()

    s.baseline_engine = MagicMock()
    s.baseline_engine.get_all_baselines = MagicMock(return_value=[])

    s.intent_compiler = None
    s.email_watcher = None

    s.skill_registry = MagicMock()
    s.skill_registry.skills = {}

    return s


@pytest.fixture
def _patched_app(_disable_api_key_middleware_for_tests):
    """Import the app with a mocked state so we don't need the full brain."""
    mock = _make_mock_state()
    with patch("api.routes.ambient.state", mock), \
         patch("api.state.state", mock):
        from api.routes.ambient import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        yield app, mock


async def test_briefing_returns_structure(_patched_app):
    app, mock = _patched_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/ambient/briefing")
    assert resp.status_code == 200
    body = resp.json()
    assert "greeting" in body
    assert "sleep" in body
    assert "agenda" in body
    assert "weather" in body
    assert "goals" in body
    assert "vip_emails" in body
    assert isinstance(body["agenda"], list)
    assert isinstance(body["goals"], list)


async def test_briefing_includes_sleep_when_hrv_present(_patched_app):
    app, mock = _patched_app
    mock.baseline_engine.get_all_baselines.return_value = [
        {"metric": "hrv_ms", "value": 42, "trend": "improving"},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/ambient/briefing")
    body = resp.json()
    assert body["sleep"] is not None
    assert body["sleep"]["hrv_ms"] == 42
    assert body["sleep"]["trend"] == "improving"


async def test_briefing_503_without_orchestrator(_patched_app):
    app, mock = _patched_app
    mock.orchestrator = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/ambient/briefing")
    assert resp.status_code == 503


async def test_snapshot_suggests_mode_by_time(_patched_app):
    app, _ = _patched_app
    morning = datetime(2026, 4, 16, 7, 30, 0)
    with patch("api.routes.ambient.datetime") as mock_dt:
        mock_dt.now.return_value = morning
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/ambient/snapshot")
    body = resp.json()
    assert body["suggested_mode"] == "briefing"


async def test_snapshot_desk_mode_during_work_hours(_patched_app):
    app, _ = _patched_app
    noon = datetime(2026, 4, 16, 12, 0, 0)
    with patch("api.routes.ambient.datetime") as mock_dt:
        mock_dt.now.return_value = noon
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/ambient/snapshot")
    body = resp.json()
    assert body["suggested_mode"] == "desk"


async def test_snapshot_wind_down_at_night(_patched_app):
    app, _ = _patched_app
    night = datetime(2026, 4, 16, 22, 0, 0)
    with patch("api.routes.ambient.datetime") as mock_dt:
        mock_dt.now.return_value = night
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/ambient/snapshot")
    body = resp.json()
    assert body["suggested_mode"] == "wind_down"


async def test_next_event_graceful_without_calendar(_patched_app):
    app, mock = _patched_app
    mock.skill_registry.skills = {}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/ambient/next_event")
    body = resp.json()
    assert body["event"] is None
    assert "hint" in body
    assert "Calendar" in body["hint"]


async def test_next_event_returns_data_when_calendar_available(_patched_app):
    app, mock = _patched_app
    cal_mock = MagicMock()
    cal_mock.execute = AsyncMock(return_value={
        "success": True,
        "data": {"title": "Standup", "start": "09:00", "end": "09:15"},
    })
    mock.skill_registry.skills = {"calendar_lookup": cal_mock}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/ambient/next_event")
    body = resp.json()
    assert body["title"] == "Standup"
