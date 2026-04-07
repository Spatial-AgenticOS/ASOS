"""Tests for THEORA knowledge graph (entities, relations, traversal, FTS)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from memory.embeddings import LOCAL_DIM, EmbeddingProvider
from memory.knowledge_graph import KnowledgeGraph


def _force_hash_provider(ep: EmbeddingProvider) -> None:
    ep._provider = "hash"
    ep._dim = LOCAL_DIM
    ep._model = None


@pytest.fixture
def kg_db():
    """Temp SQLite DB path and embedder for KnowledgeGraph."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    with patch.object(EmbeddingProvider, "_detect_provider", _force_hash_provider):
        embedder = EmbeddingProvider()
    graph = KnowledgeGraph(path, embedder)
    yield graph, path, embedder
    try:
        os.unlink(path)
    except OSError:
        pass


class TestAddEntity:
    """add_entity creates rows and merges duplicates by name."""

    @pytest.mark.asyncio
    async def test_creates_entity_with_id(self, kg_db):
        kg, path, _ = kg_db
        out = await kg.add_entity("Acme Corp", entity_type="organization")
        assert "id" in out
        assert out["name"] == "Acme Corp"
        assert out["entity_type"] == "organization"
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, name, entity_type FROM entities WHERE id = ?", (out["id"],)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["name"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_duplicate_merges_mention_count(self, kg_db):
        kg, path, _ = kg_db
        first = await kg.add_entity("MergeMe", "thing")
        second = await kg.add_entity("MergeMe", "thing")
        assert first["id"] == second["id"]
        conn = sqlite3.connect(path)
        mc = conn.execute(
            "SELECT mention_count FROM entities WHERE id = ?", (first["id"],)
        ).fetchone()[0]
        conn.close()
        assert mc == 2


class TestAddRelation:
    """Relations connect entities."""

    @pytest.mark.asyncio
    async def test_creates_relation(self, kg_db):
        kg, _, _ = kg_db
        rel = await kg.add_relation("Alice", "knows", "Bob", source_type="person", target_type="person")
        assert "id" in rel
        assert rel["source"] == "Alice"
        assert rel["relation"] == "knows"
        assert rel["target"] == "Bob"


class TestTraverse:
    """Graph traversal depth."""

    @pytest.mark.asyncio
    async def test_single_hop(self, kg_db):
        kg, _, _ = kg_db
        await kg.add_relation("StartNode", "links", "EndNode")
        rows = kg.traverse("StartNode", max_depth=2, limit=20)
        assert len(rows) >= 1
        targets = {r["target"] for r in rows}
        assert "EndNode" in targets

    @pytest.mark.asyncio
    async def test_multi_hop(self, kg_db):
        kg, _, _ = kg_db
        await kg.add_relation("Alpha", "next", "Beta")
        await kg.add_relation("Beta", "next", "Gamma")
        rows = kg.traverse("Alpha", max_depth=3, limit=50)
        assert len(rows) >= 2
        depths = {r["depth"] for r in rows}
        assert depths.intersection({1, 2, 3})


class TestSearchEntities:
    """FTS + vector hybrid search."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, kg_db):
        kg, _, _ = kg_db
        await kg.add_entity("Searchable Phoenix", "place")
        results = await kg.search_entities("Phoenix", limit=10)
        assert isinstance(results, list)
        assert len(results) >= 1
        names = {r["name"] for r in results}
        assert "Searchable Phoenix" in names


class TestHeuristicExtract:
    """Pattern-based extraction without LLM."""

    def test_my_name_is_john(self, kg_db):
        kg, _, _ = kg_db
        out = kg._heuristic_extract("Hello, my name is John")
        assert any(
            r.get("source") == "user" and r.get("relation") == "is_named" and r.get("target") == "John"
            for r in out
        )


class TestBuildGraphContext:
    """LLM context string from graph neighborhood."""

    @pytest.mark.asyncio
    async def test_returns_string_context(self, kg_db):
        kg, _, _ = kg_db
        await kg.add_relation("ContextUser", "prefers", "Tea")
        ctx = await kg.build_graph_context("Tea", max_chars=4000)
        assert isinstance(ctx, str)
        if ctx:
            assert "Knowledge Graph" in ctx or "ContextUser" in ctx or "Tea" in ctx


class TestStats:
    """Aggregate counts."""

    @pytest.mark.asyncio
    async def test_stats_counts(self, kg_db):
        kg, _, _ = kg_db
        await kg.add_entity("S1", "thing")
        await kg.add_entity("S2", "thing")
        await kg.add_relation("S1", "relates_to", "S2")
        st = kg.stats()
        assert st["entities"] >= 2
        assert st["relations"] >= 1
        assert "aliases" in st
