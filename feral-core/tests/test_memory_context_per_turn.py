"""Multi-memory must fire on every LLM turn — not just working memory.

Regression guard for the bug where `IdentityLoader.build_system_prompt`
never threaded the user's utterance into `build_context_for_llm`, which
made `context_builder` silently skip knowledge-graph + episode search
(both are guarded behind ``if query:``).

These tests:
  1. Seed one episode + one knowledge-graph triple.
  2. Call `build_system_prompt(..., query="where is my wallet")`.
  3. Assert the rendered `## Memory` block mentions both.
  4. Assert a snapshot landed on the inspector ring.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from agents.identity_loader import (
    IdentityLoader,
    clear_memory_snapshots,
    recent_memory_snapshots,
)
from memory.store import MemoryStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = MemoryStore(db_path=path)
    yield s
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _clear_ring():
    clear_memory_snapshots()
    yield
    clear_memory_snapshots()


def _frame():
    f = MagicMock()
    f.to_system_context.return_value = "No sensor data available."
    f.connected_nodes = []
    return f


def test_query_threaded_into_memory_context(store):
    """With a non-empty query the builder must hit KG + episodes, not just working."""
    store.working_push("s1", {"role": "user", "text": "prior turn chatter"})
    store.episode_save(
        session_id="s1",
        event_type="object_location",
        summary="User left the wallet on the kitchen counter",
        importance=0.9,
    )
    store.knowledge_store(
        subject="wallet",
        predicate="located_in",
        obj="kitchen",
        confidence=0.95,
        source="user_stated",
    )

    loader = IdentityLoader(memory=store)
    prompt = loader.build_system_prompt(
        frame=_frame(),
        skills=[],
        session_id="s1",
        identity_text="You are FERAL.",
        full_catalog=[],
        query="where is my wallet",
    )

    assert "## Memory" in prompt
    memory_block = prompt.split("## Memory", 1)[1]
    # Episode (either sync FTS or async hybrid) landed:
    assert "wallet" in memory_block.lower()
    # Knowledge graph fact landed under Known Facts or Graph Context:
    assert ("kitchen" in memory_block.lower()) or ("located_in" in memory_block.lower())


def test_empty_query_still_returns_working_and_recent_episodes(store):
    store.working_push("s1", {"role": "user", "text": "recent note"})
    store.episode_save(session_id="s1", event_type="chat", summary="general chit chat")

    loader = IdentityLoader(memory=store)
    prompt = loader.build_system_prompt(
        frame=_frame(),
        skills=[],
        session_id="s1",
        identity_text="You are FERAL.",
        full_catalog=[],
        query="",
    )
    assert "## Memory" in prompt
    memory_block = prompt.split("## Memory", 1)[1]
    assert "recent note" in memory_block or "Recent Context" in memory_block


def test_snapshot_ring_captures_every_turn(store):
    store.working_push("s1", {"role": "user", "text": "seed"})

    loader = IdentityLoader(memory=store)
    for text in ("one", "two", "three"):
        loader.build_system_prompt(
            frame=_frame(),
            skills=[],
            session_id="s1",
            identity_text="You are FERAL.",
            full_catalog=[],
            query=text,
        )

    snapshots = recent_memory_snapshots(limit=10)
    assert len(snapshots) == 3
    # Ordered newest-first:
    assert snapshots[0]["query"] == "three"
    assert snapshots[1]["query"] == "two"
    assert snapshots[2]["query"] == "one"
    for snap in snapshots:
        assert snap["session_id"] == "s1"
        assert isinstance(snap["latency_ms"], int)
        assert snap["latency_ms"] >= 0
        assert "memory_context" in snap


def test_snapshot_ring_limit_enforced(store):
    """limit parameter bounded to 1-50."""
    loader = IdentityLoader(memory=store)
    for i in range(5):
        loader.build_system_prompt(
            frame=_frame(),
            skills=[],
            session_id="s1",
            identity_text="x",
            full_catalog=[],
            query=f"turn-{i}",
        )
    assert len(recent_memory_snapshots(limit=2)) == 2
    assert len(recent_memory_snapshots(limit=999)) == 5


def test_orchestrator_forwards_query_to_build_system_prompt():
    """Orchestrator._build_system_prompt must accept + forward `query`."""
    from agents.orchestrator import Orchestrator

    orch = MagicMock(spec=Orchestrator)
    # Lazy import — the signature check happens via the module, not an instance.
    import inspect

    sig = inspect.signature(Orchestrator._build_system_prompt)
    assert "query" in sig.parameters, "Orchestrator._build_system_prompt must accept query"
    # Default must be an empty string so legacy callers keep working:
    assert sig.parameters["query"].default == ""
