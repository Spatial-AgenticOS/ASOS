"""Phase 0 + 1B regression tests for `feral-core/api/routes/memory.py`.

Covers MEMORY_SYSTEM_FIX_PLAN.md:
- Phase 0.1: ``/api/knowledge/{relationship,visualize}`` no longer raises
  ``AttributeError`` on ``state.memory._knowledge_graph`` (the attribute
  was the wrong name; the canonical path is ``state.memory.kg``).
- Phase 0.2: ``GET/POST /api/memory/backend`` log a warning instead of
  silently swallowing a corrupt settings.json.
- Phase 1B: ``/api/memory/backend`` exposes ``active_store`` +
  ``pending_unapplied`` so dashboards can show the running brain's
  truth even when the configured backend doesn't match.
- Phase 5 (partial): ``/internal/memory/stats`` carries an
  ``observability`` block with ``sqlite_vec_loaded``, ``chunk_count``,
  ``embedding_provider``, and ``degraded_semantic_search``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))

    from config.loader import ConfigLoader
    config = ConfigLoader(project_dir=str(tmp_path))
    config.discover()

    # Real-ish ``state.memory`` with a working KG and a settable
    # ``stats()`` result. Real ``MemoryStore`` would pull a sqlite DB
    # off disk; the routes only need the duck-typed attributes the
    # handlers reach for.
    memory = MagicMock()
    memory.stats.return_value = {"notes": 0, "episodes": 0}
    # Default: no KG (covers the 503 path for /api/knowledge/*).
    memory.kg = None
    memory._vec_index = MagicMock(indexed=False)
    memory._embed_queue = MagicMock(provider="openai")
    memory._db_path = str(tmp_path / "memory.db")

    mock_state = MagicMock()
    mock_state.config = config
    mock_state.memory = memory

    with (
        patch("api.state.state", mock_state),
        patch("api.routes.memory.state", mock_state),
    ):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), memory


# ── Phase 0.1: knowledge route attribute fix ──────────────────────────


def test_knowledge_relationship_returns_503_when_kg_unavailable(env):
    c, memory = env
    memory.kg = None
    r = c.get("/api/knowledge/relationship?entity_a=alice&entity_b=bob")
    assert r.status_code == 503
    body = r.json()
    assert "Knowledge graph unavailable" in body["detail"]


def test_knowledge_relationship_400_on_missing_args(env):
    c, _ = env
    r = c.get("/api/knowledge/relationship")
    assert r.status_code == 400
    assert "Both entity_a and entity_b" in r.json()["detail"]


def test_knowledge_relationship_calls_relationship_query_on_real_kg(env):
    c, memory = env
    memory.kg = MagicMock()  # presence is enough; the import path is mocked too

    fake_result = {"path": [{"a": "alice"}, {"b": "bob"}], "length": 2}
    with patch("memory.enhanced_search.relationship_query", return_value=fake_result) as f:
        r = c.get("/api/knowledge/relationship?entity_a=alice&entity_b=bob&max_depth=3")
    assert r.status_code == 200, r.text
    assert r.json() == fake_result
    f.assert_called_once_with(memory.kg, "alice", "bob", 3)


def test_knowledge_visualize_returns_503_when_kg_unavailable(env):
    c, memory = env
    memory.kg = None
    r = c.get("/api/knowledge/visualize?entity=alice")
    assert r.status_code == 503


def test_knowledge_visualize_400_on_missing_entity(env):
    c, _ = env
    r = c.get("/api/knowledge/visualize")
    assert r.status_code == 400


def test_knowledge_visualize_calls_graph_visualization_data(env):
    c, memory = env
    memory.kg = MagicMock()
    fake = {"nodes": [{"id": "x"}], "edges": []}
    with patch("memory.enhanced_search.graph_visualization_data", return_value=fake) as f:
        r = c.get("/api/knowledge/visualize?entity=alice&depth=3&limit=12")
    assert r.status_code == 200, r.text
    assert r.json() == fake
    f.assert_called_once_with(memory.kg, "alice", max_depth=3, limit=12)


# ── Phase 1B: backend honesty ────────────────────────────────────────


def test_get_memory_backend_exposes_active_store(env):
    c, _ = env
    r = c.get("/api/memory/backend")
    assert r.status_code == 200
    body = r.json()
    assert body["active_store"] == "memory_db_vec_chunks"
    # Default settings: backend == "sqlite_vec" → not pending.
    assert body["backend"] == "sqlite_vec"
    assert body["pending_unapplied"] is False


def test_get_memory_backend_pending_when_user_picked_chroma(env, tmp_path):
    c, _ = env
    settings = tmp_path / "settings.json"
    import json
    settings.write_text(json.dumps({"memory": {"backend": "chroma"}}))
    r = c.get("/api/memory/backend")
    body = r.json()
    assert body["backend"] == "chroma"
    assert body["pending_unapplied"] is True


def test_post_memory_backend_returns_pending_note(env):
    c, _ = env
    # Force chroma to be "installed" so the route accepts it.
    with patch("api.routes.memory._memory_backend_installed", return_value=True):
        r = c.post("/api/memory/backend", json={"backend": "chroma"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["backend"] == "chroma"
    assert body["pending_unapplied"] is True
    assert "Phase 1A" in body["note"]
    assert body["active_store"] == "memory_db_vec_chunks"


# ── Phase 0.2: corrupt settings.json logs instead of swallowing ──────


def test_corrupt_settings_logs_warning_and_defaults(env, tmp_path, caplog):
    c, _ = env
    (tmp_path / "settings.json").write_text("not-json{{{")
    with caplog.at_level("WARNING", logger="feral.memory.api"):
        r = c.get("/api/memory/backend")
    assert r.status_code == 200
    # Default fallback when read fails.
    assert r.json()["backend"] == "sqlite_vec"
    assert any("settings.json read failed" in m for m in caplog.messages)


# ── Phase 5: observability on /internal/memory/stats ─────────────────


def test_memory_stats_includes_observability_block(env):
    c, memory = env
    memory._vec_index.indexed = True
    r = c.get("/internal/memory/stats")
    assert r.status_code == 200
    body = r.json()
    obs = body["observability"]
    assert obs["sqlite_vec_loaded"] is True
    assert obs["embedding_provider"] == "openai"
    assert obs["active_vector_store"] == "memory_db_vec_chunks"
    # No chunks in this test DB, so degraded_semantic_search is False.
    assert obs["chunk_count"] == 0
    assert obs["degraded_semantic_search"] is False


def test_memory_stats_flags_degraded_when_chunks_exist_but_no_vec(env, tmp_path):
    c, memory = env
    memory._vec_index.indexed = False
    # Create a memory.db with one chunk row so the COUNT(*) query
    # exercises the degraded path.
    import sqlite3
    db = tmp_path / "memory.db"
    memory._db_path = str(db)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE memory_chunks (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO memory_chunks DEFAULT VALUES")
    conn.commit()
    conn.close()

    r = c.get("/internal/memory/stats")
    body = r.json()
    obs = body["observability"]
    assert obs["sqlite_vec_loaded"] is False
    assert obs["chunk_count"] == 1
    assert obs["degraded_semantic_search"] is True
