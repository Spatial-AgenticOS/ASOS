"""Phase 13 — brain identity discovery endpoint tests."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Build a minimal FastAPI test client with a mock feral state."""
    from fastapi import FastAPI
    from api.routes.discovery import router

    app = FastAPI()
    app.include_router(router)

    mock_state = SimpleNamespace(
        brain_id="test-brain-001",
        primary_session_id="primary-abc123",
    )
    app.state.feral = mock_state
    return TestClient(app)


class TestDiscoveryBrain:
    def test_happy_path(self, client):
        resp = client.get("/api/discovery/brain")
        assert resp.status_code == 200
        data = resp.json()
        assert data["brain_id"] == "test-brain-001"
        assert data["fingerprint"] == hashlib.sha256(b"primary-abc123").hexdigest()[:16]
        assert "host" in data
        assert isinstance(data["port"], int)
        assert "version" in data

    def test_fingerprint_stability(self, client):
        r1 = client.get("/api/discovery/brain").json()
        r2 = client.get("/api/discovery/brain").json()
        assert r1["fingerprint"] == r2["fingerprint"]
        assert r1["fingerprint"] != ""

    def test_missing_data_fallback(self):
        from fastapi import FastAPI
        from api.routes.discovery import router

        app = FastAPI()
        app.include_router(router)
        app.state.feral = SimpleNamespace()
        c = TestClient(app)
        resp = c.get("/api/discovery/brain")
        assert resp.status_code == 200
        data = resp.json()
        assert data["brain_id"] == ""
        assert data["fingerprint"] == ""
