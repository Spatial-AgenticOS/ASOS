"""Unit tests for the AboutMeStore (structured self-model)."""

from __future__ import annotations

import time

import pytest

from agents.about_me import (
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_UNCONFIRMED,
    FACT_KINDS,
    AboutMeStore,
)


@pytest.fixture
def store(tmp_path):
    return AboutMeStore(db_path=str(tmp_path / "about_me.db"))


class TestCRUD:
    def test_upsert_creates_fact(self, store: AboutMeStore):
        f = store.upsert(
            kind="preference",
            text="I don't drink coffee after 4pm",
            tags=["diet", "sleep"],
        )
        assert f.id
        assert f.kind == "preference"
        assert f.confidence == CONFIDENCE_CONFIRMED
        assert "diet" in f.tags and "sleep" in f.tags
        assert f.created_at > 0

    def test_upsert_merges_duplicate(self, store: AboutMeStore):
        f1 = store.upsert(kind="place", text="Home is 123 X street", tags=["location"])
        f2 = store.upsert(kind="place", text="HOME IS 123 X STREET", tags=["home"])
        assert f1.id == f2.id
        assert set(f2.tags) == {"home", "location"}

    def test_list_filters_by_kind(self, store: AboutMeStore):
        store.upsert(kind="preference", text="p1")
        store.upsert(kind="relationship", text="r1")
        prefs = store.list(kind="preference")
        assert len(prefs) == 1
        assert prefs[0].kind == "preference"

    def test_list_filters_by_tag(self, store: AboutMeStore):
        store.upsert(kind="preference", text="p1", tags=["diet"])
        store.upsert(kind="preference", text="p2", tags=["fitness"])
        diet = store.list(tag="diet")
        assert len(diet) == 1
        assert "diet" in diet[0].tags

    def test_get_returns_none_for_unknown(self, store: AboutMeStore):
        assert store.get("bogus") is None

    def test_delete_removes_row(self, store: AboutMeStore):
        f = store.upsert(kind="goal", text="Launch theora")
        assert store.delete(f.id) is True
        assert store.get(f.id) is None
        assert store.delete("bogus") is False


class TestConfidenceLadder:
    def test_confirm_promotes_confidence(self, store: AboutMeStore):
        f = store.upsert(
            kind="preference",
            text="tea at 4pm",
            source="inferred_from_chat",
            confidence=CONFIDENCE_UNCONFIRMED,
        )
        assert f.confidence == CONFIDENCE_UNCONFIRMED
        confirmed = store.confirm(f.id)
        assert confirmed is not None
        assert confirmed.confidence == CONFIDENCE_CONFIRMED
        assert confirmed.source == "user_stated"

    def test_confirm_unknown_returns_none(self, store: AboutMeStore):
        assert store.confirm("bogus") is None

    def test_reject_converts_to_taboo(self, store: AboutMeStore):
        f = store.upsert(
            kind="preference",
            text="Prefers: coffee",
            source="inferred_from_chat",
            confidence=CONFIDENCE_UNCONFIRMED,
        )
        rejected = store.reject(f.id)
        assert rejected is not None
        assert rejected.kind == "taboo"
        assert "Never assume" in rejected.text
        assert "user_rejected" in rejected.tags
        assert rejected.confidence == CONFIDENCE_CONFIRMED

    def test_reject_unknown_returns_none(self, store: AboutMeStore):
        assert store.reject("bogus") is None

    def test_upsert_merge_preserves_higher_confidence(self, store: AboutMeStore):
        f1 = store.upsert(
            kind="preference",
            text="tea at 4pm",
            confidence=CONFIDENCE_UNCONFIRMED,
            source="inferred_from_chat",
        )
        f2 = store.upsert(
            kind="preference",
            text="tea at 4pm",
            confidence=CONFIDENCE_CONFIRMED,
            source="user_stated",
        )
        assert f2.id == f1.id
        assert f2.confidence == CONFIDENCE_CONFIRMED


class TestExpiration:
    def test_expired_facts_excluded_by_default(self, store: AboutMeStore):
        store.upsert(
            kind="context",
            text="Traveling to SF this week",
            expires_at=time.time() - 10,
        )
        alive = store.list()
        assert alive == []

    def test_expired_facts_returned_when_requested(self, store: AboutMeStore):
        store.upsert(
            kind="context",
            text="Traveling to SF this week",
            expires_at=time.time() - 10,
        )
        with_expired = store.list(include_expired=True)
        assert len(with_expired) == 1

    def test_sweep_drops_expired(self, store: AboutMeStore):
        store.upsert(
            kind="context",
            text="A",
            expires_at=time.time() - 10,
        )
        store.upsert(kind="context", text="B")
        n = store.sweep_expired()
        assert n == 1
        assert [f.text for f in store.list(include_expired=True)] == ["B"]


class TestSummaryAndPromptChunk:
    def test_summary_counts_by_kind(self, store: AboutMeStore):
        store.upsert(kind="preference", text="p1")
        store.upsert(kind="preference", text="p2")
        store.upsert(kind="goal", text="g1")
        s = store.summary()
        assert s["total_facts"] == 3
        assert s["per_kind"]["preference"] == 2
        assert s["per_kind"]["goal"] == 1
        assert set(s["kinds_supported"]) == set(FACT_KINDS)

    def test_system_prompt_chunk_empty_when_no_facts(self, store: AboutMeStore):
        assert store.system_prompt_chunk() == ""

    def test_system_prompt_chunk_includes_each_kind(self, store: AboutMeStore):
        store.upsert(kind="preference", text="tea over coffee")
        store.upsert(kind="goal", text="Launch theora v2")
        store.upsert(kind="taboo", text="Never mention Z")
        chunk = store.system_prompt_chunk()
        assert "Preferences" in chunk
        assert "Goals" in chunk
        assert "Taboos" in chunk
        assert "tea over coffee" in chunk
        assert "Launch theora v2" in chunk

    def test_system_prompt_chunk_respects_budget(self, store: AboutMeStore):
        for i in range(100):
            store.upsert(kind="preference", text=f"very long preference line number {i} " * 20)
        chunk = store.system_prompt_chunk(token_budget_chars=300)
        assert len(chunk) <= 300


class TestExtractor:
    def test_extracts_preference(self, store: AboutMeStore):
        hits = store.extract_from_text("I love green tea in the morning.")
        assert any(f.kind == "preference" and "green tea" in f.text for f in hits)

    def test_extracts_relationship(self, store: AboutMeStore):
        hits = store.extract_from_text("My sister Amy lives in Boston with her kids.")
        assert any(f.kind == "relationship" and "Amy" in f.text for f in hits)

    def test_extracts_place(self, store: AboutMeStore):
        hits = store.extract_from_text("I live in San Francisco these days.")
        assert any(f.kind == "place" for f in hits)

    def test_extracts_goal(self, store: AboutMeStore):
        hits = store.extract_from_text("My goal is to launch theora wristband in Q3.")
        assert any(f.kind == "goal" and "theora" in f.text for f in hits)

    def test_extractor_stores_at_unconfirmed_confidence(self, store: AboutMeStore):
        hits = store.extract_from_text("I prefer oat milk lattes.")
        assert hits
        for f in hits:
            assert f.confidence == CONFIDENCE_UNCONFIRMED
            assert f.source == "inferred_from_chat"

    def test_extractor_skips_empty(self, store: AboutMeStore):
        assert store.extract_from_text("") == []
        assert store.extract_from_text("   ") == []


class TestValidation:
    def test_rejects_unknown_kind(self, store: AboutMeStore):
        with pytest.raises(ValueError):
            store.upsert(kind="unknown_kind", text="x")  # type: ignore[arg-type]

    def test_rejects_unknown_source(self, store: AboutMeStore):
        with pytest.raises(ValueError):
            store.upsert(
                kind="preference",
                text="x",
                source="bogus",  # type: ignore[arg-type]
            )

    def test_rejects_empty_text(self, store: AboutMeStore):
        with pytest.raises(ValueError):
            store.upsert(kind="preference", text="   ")
