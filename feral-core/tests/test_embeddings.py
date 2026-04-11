"""Tests for FERAL memory embedding utilities and vector index."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from memory.embeddings import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    LOCAL_DIM,
    EmbedQueue,
    EmbeddingProvider,
    VectorIndex,
    blob_to_vec,
    chunk_text,
    cosine_similarity,
    vec_to_blob,
)


@pytest.fixture
def temp_db_path():
    """Temporary SQLite file path for VectorIndex tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def _force_hash_provider(ep: EmbeddingProvider) -> None:
    ep._provider = "hash"
    ep._dim = LOCAL_DIM
    ep._model = None


class TestChunkText:
    """Tests for chunk_text word-based splitting."""

    def test_short_text_single_chunk(self):
        text = "hello world"
        chunks = chunk_text(text)
        assert chunks == [text]

    def test_splitting_and_overlap(self):
        words = [f"w{i}" for i in range(CHUNK_SIZE + 50)]
        text = " ".join(words)
        chunks = chunk_text(text, max_tokens=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        assert len(chunks) > 1
        first_words = chunks[0].split()
        second_words = chunks[1].split()
        overlap_words = set(first_words[-CHUNK_OVERLAP:]) & set(second_words[:CHUNK_OVERLAP])
        assert len(overlap_words) == CHUNK_OVERLAP


class TestVecBlobRoundtrip:
    """vec_to_blob / blob_to_vec symmetry."""

    def test_roundtrip_list(self):
        vec = [0.25, -1.5, 2.0]
        blob = vec_to_blob(vec)
        out = blob_to_vec(blob)
        assert out.dtype == np.float32
        np.testing.assert_allclose(out, np.array(vec, dtype=np.float32))

    def test_roundtrip_ndarray(self):
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        out = blob_to_vec(vec_to_blob(vec))
        np.testing.assert_allclose(out, vec.astype(np.float32))


class TestCosineSimilarity:
    """cosine_similarity edge cases."""

    def test_identical_vectors_are_one(self):
        a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert abs(cosine_similarity(a, a) - 1.0) < 1e-6

    def test_orthogonal_vectors_are_zero(self):
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        assert abs(cosine_similarity(a, b)) < 1e-6


class TestEmbeddingProvider:
    """EmbeddingProvider hash fallback and dimension."""

    @pytest.mark.asyncio
    async def test_hash_fallback_consistent_vectors(self):
        with patch.object(EmbeddingProvider, "_detect_provider", _force_hash_provider):
            p = EmbeddingProvider()
        assert p.provider_name == "hash"
        v1 = await p.embed("same text")
        v2 = await p.embed("same text")
        np.testing.assert_allclose(v1, v2)
        assert v1.shape == (LOCAL_DIM,)

    def test_dimension_property(self):
        with patch.object(EmbeddingProvider, "_detect_provider", _force_hash_provider):
            p = EmbeddingProvider()
        assert p.dimension == LOCAL_DIM


class TestVectorIndex:
    """VectorIndex with temp DB; search may be empty without sqlite-vec."""

    def test_create_upsert_search(self, temp_db_path):
        dim = 8
        idx = VectorIndex(temp_db_path, dimension=dim)
        v = np.ones(dim, dtype=np.float32)
        idx.upsert("chunk-1", v)
        results = idx.search(v, limit=5)
        assert isinstance(results, list)
        if not idx.indexed:
            assert results == []


class TestEmbedQueue:
    """EmbedQueue pending counter."""

    def test_enqueue_increments_pending(self, temp_db_path):
        mock_embedder = MagicMock()
        mock_embedder.embed = AsyncMock(return_value=np.zeros(LOCAL_DIM, dtype=np.float32))
        q = EmbedQueue(mock_embedder)
        q.enqueue("cid", "hello", "memory_chunks", "src1", 0, temp_db_path)
        assert q.pending == 1
