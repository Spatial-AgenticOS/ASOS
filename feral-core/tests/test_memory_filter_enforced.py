"""SpecialistAgent.memory_filter must narrow the memory context.

The field has existed on PersonaManifest + SpecialistAgent since Track C
but the orchestrator never read it — cross-domain leakage was silent.
This commit threads it through ``build_context_for_llm`` and post-filters
episodes / recent actions. Tests here pin the new behaviour.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.no_auto_feral_home


class _FakeStore:
    """Minimal MemoryStore stand-in that the context_builder needs."""

    def __init__(self, *, episodes, execs):
        self._episodes = episodes
        self._execs = execs
        self._kg = None

    def working_context_string(self, session_id, limit=8):
        return ""

    async def knowledge_search(self, query, limit=5):
        return []

    async def episode_search(self, query, limit=3):
        return self._episodes

    async def episode_search_hybrid(self, query, limit=3):
        return self._episodes

    async def episode_recent(self, limit=3, session_id=None):
        return self._episodes

    async def log_recent(self, limit=5):
        return self._execs


def test_topic_match_matches_across_fields():
    from memory.context_builder import _topic_match

    assert _topic_match({"event_type": "coding_task"}, "coding")
    assert _topic_match({"summary": "Wrote unit tests for parser"}, "unit")
    assert _topic_match({"skill_id": "journal"}, "journal")
    assert _topic_match({"tags": ["security", "audit"]}, "security")
    assert not _topic_match({"event_type": "home_ops", "summary": "Turned on the lights"}, "coding")
    # empty topic means no filtering
    assert _topic_match({"summary": "anything"}, "")


async def test_memory_filter_drops_out_of_scope_episodes():
    """A 'coding' memory_filter must drop 'journal' episodes."""
    from memory.context_builder import build_context_for_llm_async

    store = _FakeStore(
        episodes=[
            {"event_type": "coding_commit", "summary": "Fixed a bug in parser"},
            {"event_type": "journal_entry", "summary": "Felt anxious this morning"},
        ],
        execs=[
            {"skill_id": "coding_tools", "result_status": "ok"},
            {"skill_id": "journal", "result_status": "ok"},
        ],
    )
    text = await build_context_for_llm_async(store, session_id="s1", memory_filter="coding")
    assert "Fixed a bug in parser" in text
    assert "Felt anxious" not in text
    assert "coding_tools" in text
    assert "journal" not in text


async def test_memory_filter_empty_means_no_filter():
    """Default/empty memory_filter preserves legacy behaviour."""
    from memory.context_builder import build_context_for_llm_async

    store = _FakeStore(
        episodes=[
            {"event_type": "coding_commit", "summary": "a"},
            {"event_type": "journal_entry", "summary": "b"},
        ],
        execs=[{"skill_id": "x", "result_status": "ok"}],
    )
    text = await build_context_for_llm_async(store, session_id="s1")  # no memory_filter kwarg
    assert "a" in text and "b" in text


async def test_memory_store_forwards_memory_filter_kwarg():
    """The MemoryStore wrapper accepts + forwards the new kwarg."""
    from memory import store as store_mod

    s = store_mod.MemoryStore.__new__(store_mod.MemoryStore)

    captured = {}

    async def _fake_builder(store, session_id, query, max_tokens_budget, memory_filter):
        captured.update({
            "session_id": session_id,
            "query": query,
            "budget": max_tokens_budget,
            "memory_filter": memory_filter,
        })
        return "OK"

    # Monkeypatch the async builder underneath.
    original = store_mod.context_build_context_for_llm_async
    store_mod.context_build_context_for_llm_async = _fake_builder
    try:
        out = await s.build_context_for_llm("sess", memory_filter="security")
    finally:
        store_mod.context_build_context_for_llm_async = original

    assert out == "OK"
    assert captured["memory_filter"] == "security"
