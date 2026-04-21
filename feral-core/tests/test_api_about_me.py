"""API contract tests for /api/about-me.

Uses a real AboutMeStore on a temp SQLite file and patches the shared
``state`` object so every route sees it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.about_me import AboutMeStore


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture()
def client(tmp_path):
    store = AboutMeStore(db_path=str(tmp_path / "about_me.db"))

    mock = MagicMock()
    mock.about_me = store

    with patch("api.state.state", mock), patch("api.routes.about_me.state", mock):
        from api.server import app

        yield TestClient(app, raise_server_exceptions=False), store


def test_list_empty(client):
    c, _ = client
    r = c.get("/api/about-me")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["facts"] == []
    assert "preference" in body["kinds_supported"]


def test_post_upsert_and_list(client):
    c, store = client
    r = c.post(
        "/api/about-me",
        json={
            "kind": "preference",
            "text": "I don't drink coffee after 4pm",
            "tags": ["diet"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    fid = body["fact"]["id"]
    assert fid

    r2 = c.get("/api/about-me")
    assert r2.status_code == 200
    assert r2.json()["count"] == 1


def test_post_rejects_bad_kind(client):
    c, _ = client
    r = c.post(
        "/api/about-me",
        json={"kind": "not_a_kind", "text": "x"},
    )
    assert r.status_code == 400


def test_post_rejects_bad_source(client):
    c, _ = client
    r = c.post(
        "/api/about-me",
        json={"kind": "preference", "text": "tea", "source": "bogus"},
    )
    assert r.status_code == 400


def test_post_rejects_empty_text(client):
    c, _ = client
    r = c.post(
        "/api/about-me",
        json={"kind": "preference", "text": "   "},
    )
    # pydantic's min_length=1 trims fails first → 422, and upstream empty-text
    # guard gives 400. Accept either so this contract test isn't brittle to
    # which layer rejects first.
    assert r.status_code in (400, 422)


def test_get_with_filter_by_kind(client):
    c, _ = client
    c.post("/api/about-me", json={"kind": "preference", "text": "a"})
    c.post("/api/about-me", json={"kind": "goal", "text": "b"})
    r = c.get("/api/about-me", params={"kind": "goal"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["facts"][0]["kind"] == "goal"


def test_get_with_bad_kind_returns_400(client):
    c, _ = client
    r = c.get("/api/about-me", params={"kind": "xxx"})
    assert r.status_code == 400


def test_confirm_promotes(client):
    c, store = client
    f = store.upsert(kind="preference", text="tea at 4pm", confidence=0.5, source="inferred_from_chat")
    r = c.post(f"/api/about-me/{f.id}/confirm")
    assert r.status_code == 200
    assert r.json()["fact"]["confidence"] == 1.0
    assert r.json()["fact"]["source"] == "user_stated"


def test_confirm_unknown_returns_404(client):
    c, _ = client
    r = c.post("/api/about-me/unknown/confirm")
    assert r.status_code == 404


def test_reject_converts_to_taboo(client):
    c, store = client
    f = store.upsert(kind="preference", text="Coffee", confidence=0.5, source="inferred_from_chat")
    r = c.post(f"/api/about-me/{f.id}/reject")
    assert r.status_code == 200
    body = r.json()
    assert body["fact"]["kind"] == "taboo"
    assert "Never assume" in body["fact"]["text"]


def test_reject_unknown_returns_404(client):
    c, _ = client
    r = c.post("/api/about-me/unknown/reject")
    assert r.status_code == 404


def test_delete_removes(client):
    c, store = client
    f = store.upsert(kind="goal", text="ship v2026.4.23")
    r = c.delete(f"/api/about-me/{f.id}")
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert store.get(f.id) is None


def test_delete_unknown_returns_404(client):
    c, _ = client
    r = c.delete("/api/about-me/unknown")
    assert r.status_code == 404


def test_summary_includes_preview(client):
    c, store = client
    store.upsert(kind="preference", text="tea over coffee")
    store.upsert(kind="goal", text="ship v2026.4.23")
    r = c.get("/api/about-me/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_facts"] == 2
    assert body["per_kind"]["preference"] == 1
    assert body["per_kind"]["goal"] == 1
    assert "About the user" in body["system_prompt_preview"]


def test_returns_503_when_store_missing():
    mock = MagicMock()
    mock.about_me = None
    with patch("api.state.state", mock), patch("api.routes.about_me.state", mock):
        from api.server import app

        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/api/about-me")
        assert r.status_code == 503
