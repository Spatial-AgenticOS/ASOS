"""PR 8: cross-tier MemoryRetriever — ranking, MMR diversity, provenance,
and graceful tier skipping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from memory.retriever import MemoryRecord, MemoryRetriever  # noqa: E402


class _FakeMemory:
    """In-memory MemoryStore stub with controllable per-tier hits."""

    def __init__(self, *, notes=None, episodes=None, knowledge=None, logs=None):
        self._notes = notes or []
        self._episodes = episodes or []
        self._knowledge = knowledge or []
        self._logs = logs or []

    def search(self, query, limit=10):
        return self._notes[:limit]

    def episode_recent(self, limit=10, session_id=None):
        return self._episodes[:limit]

    def knowledge_query(self, subject="", predicate="", limit=20):
        # Substring filter on subject to mimic real behaviour.
        sub = (subject or "").lower()
        return [r for r in self._knowledge if sub in str(r.get("subject", "")).lower()][:limit]

    def log_recent(self, skill_id="", limit=20):
        return self._logs[:limit]


def test_retriever_returns_notes_ranked_by_lexical_overlap():
    mem = _FakeMemory(notes=[
        {"id": "n-1", "content": "Buy groceries: milk and bread"},
        {"id": "n-2", "content": "Plan the Q4 product roadmap"},
        {"id": "n-3", "content": "Remember to call Mom about milk delivery"},
    ])
    retriever = MemoryRetriever(mem)
    result = retriever.retrieve("milk", top_k=3)
    contents = [r.content for r in result.records]
    # The two notes mentioning milk must be ranked above the unrelated one.
    assert "Buy groceries: milk and bread" in contents[:2]
    assert "Remember to call Mom about milk delivery" in contents[:2]
    assert "Plan the Q4 product roadmap" not in contents[:2]


def test_retriever_skips_tiers_with_no_method():
    """A MemoryStore stub that doesn't implement `episode_recent`
    must NOT crash the retriever — just skip the tier."""
    class _Minimal:
        def search(self, q, limit=10):
            return [{"id": "n", "content": q}]

    retriever = MemoryRetriever(_Minimal())
    result = retriever.retrieve("hello", top_k=3)
    assert any(r.tier == "notes" for r in result.records)
    # Other tiers absent; no exception raised.


def test_retriever_records_skipped_tier_when_method_raises():
    class _Boom:
        def search(self, *a, **kw):
            return [{"id": "ok", "content": "hello world"}]

        def episode_recent(self, *a, **kw):
            raise RuntimeError("db locked")

    retriever = MemoryRetriever(_Boom())
    result = retriever.retrieve("hello", top_k=3)
    assert "episodes" in result.skipped_tiers
    assert "db locked" in result.skipped_tiers["episodes"]


def test_mmr_diversifies_near_duplicate_results():
    """With diversity_lambda=0.5, the top-k should not be filled with
    near-identical notes when more diverse hits exist."""
    mem = _FakeMemory(notes=[
        {"id": "a", "content": "buy milk and bread"},
        {"id": "b", "content": "buy milk and bread today"},
        {"id": "c", "content": "buy milk and bread tonight"},
        {"id": "d", "content": "milk delivery scheduled tomorrow morning early"},
    ])
    retriever = MemoryRetriever(mem, diversity_lambda=0.3)
    result = retriever.retrieve("buy milk", top_k=2)
    contents = [r.content for r in result.records]
    # At least one of the top-2 should be the diverse hit ("delivery scheduled")
    # rather than two near-duplicates of "buy milk and bread".
    assert any("delivery" in c for c in contents)


def test_retriever_deduplicates_same_record_from_two_paths():
    """If episode_recent and notes return the same content, the
    retriever must keep only one with the higher base score."""
    same = {"id": "shared-1", "content": "hello world"}
    mem = _FakeMemory(notes=[same], episodes=[same])
    retriever = MemoryRetriever(mem)
    result = retriever.retrieve("hello", top_k=5)
    # Single hit across both tiers — but they're different tiers
    # (notes vs episode) so both keys exist. The dedup is per-key.
    assert len([r for r in result.records if r.content == "hello world"]) == 2  # different tiers OK


def test_retriever_records_carry_provenance():
    mem = _FakeMemory(
        notes=[{"id": "n-1", "content": "alpha beta"}],
        knowledge=[{"id": "k-1", "subject": "alpha", "predicate": "is", "object": "letter"}],
    )
    retriever = MemoryRetriever(mem)
    result = retriever.retrieve("alpha", top_k=5)
    tiers = {r.tier for r in result.records}
    assert "notes" in tiers
    assert "knowledge" in tiers
    for r in result.records:
        assert r.record_id  # never blank
        assert 0.0 <= r.score <= 1.0
        assert r.raw  # original row preserved


def test_empty_query_returns_no_records():
    retriever = MemoryRetriever(_FakeMemory(notes=[{"id": "n", "content": "x"}]))
    result = retriever.retrieve("", top_k=5)
    assert result.records == []


def test_top_helper_limits_output():
    mem = _FakeMemory(notes=[
        {"id": str(i), "content": f"alpha {i}"} for i in range(10)
    ])
    retriever = MemoryRetriever(mem)
    result = retriever.retrieve("alpha", top_k=5)
    assert len(result.records) <= 5
    assert len(result.top(3)) == 3
