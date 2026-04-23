"""API parity tests — backfill for routes the v2 client calls that used to
404 quietly.

Covers:
  * DELETE /api/geofences/{id}        — missing before, crashed v2 Geofences page
  * POST   /api/tool-genesis/reject   — missing before, Forge.jsx fell back to
                                        /api/skills/reject which also 404s
  * POST   /api/tool-genesis/{id}/reject — path-style parity w/ jobs.py hint
  * POST   /api/geofences             — accepts both {lat, lon, radius_m}
                                        and the v2 client's {lat, lng, radius}

Geofence route tests mock ``state.location_engine`` so the real SQLite
thread-safety constraints don't bite. Integration against the real engine
is already covered by tests/test_perception_deep.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


# ── Geofences ────────────────────────────────────────────────────────


def _fake_fence(name: str, lat: float, lon: float, radius_m: float):
    """Lightweight stand-in for perception.location.Geofence."""
    fence = MagicMock()
    fence.name = name
    fence.radius_m = radius_m
    fence.center = MagicMock(lat=lat, lon=lon)
    fence.on_enter = ""
    fence.on_exit = ""
    return fence


@pytest.fixture
def geofence_client():
    engine = MagicMock()
    engine._rows: list = []

    def add(name, lat, lon, radius_m, on_enter="", on_exit=""):
        fence = _fake_fence(name, lat, lon, radius_m)
        engine._rows.append(fence)
        return fence

    def remove(name):
        before = len(engine._rows)
        engine._rows = [f for f in engine._rows if f.name != name]
        return len(engine._rows) < before

    def list_fences():
        return list(engine._rows)

    engine.add_geofence.side_effect = add
    engine.remove_geofence.side_effect = remove
    engine.list_geofences.side_effect = list_fences

    mock = MagicMock()
    mock.location_engine = engine
    with patch("api.state.state", mock), patch("api.routes.timeline.state", mock):
        from api.server import app

        yield TestClient(app, raise_server_exceptions=False), engine


def test_add_geofence_accepts_v2_client_body(geofence_client):
    c, engine = geofence_client
    r = c.post(
        "/api/geofences",
        json={"name": "home", "lat": 40.0, "lng": -74.0, "radius": 120},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["geofence"]["id"] == "home"
    assert body["geofence"]["lng"] == -74.0
    assert body["geofence"]["radius_m"] == 120

    engine.add_geofence.assert_called_once()
    args, kwargs = engine.add_geofence.call_args
    assert kwargs["lon"] == -74.0
    assert kwargs["radius_m"] == 120


def test_add_geofence_accepts_canonical_body(geofence_client):
    c, engine = geofence_client
    r = c.post(
        "/api/geofences",
        json={"name": "gym", "lat": 41.0, "lon": -74.5, "radius_m": 300},
    )
    assert r.status_code == 200
    args, kwargs = engine.add_geofence.call_args
    assert kwargs["lon"] == -74.5
    assert kwargs["radius_m"] == 300


def test_list_geofences_includes_id_and_v2_keys(geofence_client):
    c, engine = geofence_client
    engine._rows.append(_fake_fence("office", 40.7, -74.0, 200.0))

    r = c.get("/api/geofences")
    assert r.status_code == 200
    body = r.json()
    assert len(body["geofences"]) == 1
    row = body["geofences"][0]
    assert row["id"] == "office"
    assert row["name"] == "office"
    assert row["lng"] == -74.0
    assert row["lon"] == -74.0
    assert row["radius"] == 200.0
    # Legacy `fences` key still present for backward compat.
    assert body["fences"] == body["geofences"]


def test_delete_geofence_removes_row(geofence_client):
    c, engine = geofence_client
    engine._rows.append(_fake_fence("home", 40.0, -74.0, 100.0))
    r = c.delete("/api/geofences/home")
    assert r.status_code == 200
    assert r.json()["success"] is True
    engine.remove_geofence.assert_called_once_with("home")
    assert engine._rows == []


def test_delete_unknown_geofence_returns_404(geofence_client):
    c, _engine = geofence_client
    r = c.delete("/api/geofences/ghost")
    assert r.status_code == 404


def test_add_geofence_missing_lon_returns_400(geofence_client):
    c, _engine = geofence_client
    r = c.post("/api/geofences", json={"name": "broken", "lat": 40.0})
    assert r.status_code == 400


# ── Tool Genesis reject ──────────────────────────────────────────────


@pytest.fixture
def tool_genesis_client():
    engine = MagicMock()
    engine.reject.return_value = True

    mock = MagicMock()
    mock.tool_genesis = engine
    with patch("api.state.state", mock), patch("api.routes.tool_genesis.state", mock):
        from api.server import app

        yield TestClient(app, raise_server_exceptions=False), engine


def test_reject_body_style_accepts_tool_id(tool_genesis_client):
    c, engine = tool_genesis_client
    r = c.post("/api/tool-genesis/reject", json={"tool_id": "gen-123"})
    assert r.status_code == 200
    assert r.json() == {"success": True, "rejected": "gen-123"}
    engine.reject.assert_called_once_with("gen-123")


def test_reject_body_style_accepts_alias_fields(tool_genesis_client):
    c, engine = tool_genesis_client
    r = c.post("/api/tool-genesis/reject", json={"draft_id": "gen-abc"})
    assert r.status_code == 200
    engine.reject.assert_called_once_with("gen-abc")


def test_reject_body_missing_id_returns_400(tool_genesis_client):
    c, _engine = tool_genesis_client
    r = c.post("/api/tool-genesis/reject", json={})
    assert r.status_code == 400


def test_reject_path_style(tool_genesis_client):
    c, engine = tool_genesis_client
    r = c.post("/api/tool-genesis/gen-xyz/reject")
    assert r.status_code == 200
    assert r.json() == {"success": True, "rejected": "gen-xyz"}
    engine.reject.assert_called_once_with("gen-xyz")


def test_reject_unknown_tool_returns_404(tool_genesis_client):
    c, engine = tool_genesis_client
    engine.reject.return_value = False
    r = c.post("/api/tool-genesis/reject", json={"tool_id": "ghost"})
    assert r.status_code == 404
