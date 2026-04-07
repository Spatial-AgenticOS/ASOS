"""
THEORA Embedding Engine
========================
Provides vector embeddings for semantic memory search.
Supports OpenAI, local sentence-transformers, or numpy fallback.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import struct
from typing import Optional

import numpy as np

logger = logging.getLogger("theora.memory.embeddings")

OPENAI_DIM = 1536
LOCAL_DIM = 384
CHUNK_SIZE = 400
CHUNK_OVERLAP = 80


def _tokenize_rough(text: str) -> list[str]:
    return text.split()


def chunk_text(text: str, max_tokens: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks of approximately max_tokens words."""
    words = _tokenize_rough(text)
    if len(words) <= max_tokens:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = start + max_tokens
        chunks.append(" ".join(words[start:end]))
        start += max_tokens - overlap
    return chunks


def vec_to_blob(vec: list[float] | np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class EmbeddingProvider:
    """Pluggable embedding provider with auto-detection."""

    def __init__(self):
        self._provider: Optional[str] = None
        self._model = None
        self._dim = LOCAL_DIM
        self._cache: dict[str, np.ndarray] = {}
        self._detect_provider()

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        return self._provider is not None

    def _detect_provider(self):
        if os.getenv("OPENAI_API_KEY"):
            self._provider = "openai"
            self._dim = OPENAI_DIM
            logger.info("Embedding provider: OpenAI text-embedding-3-small")
            return

        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._provider = "sentence_transformers"
            self._dim = LOCAL_DIM
            logger.info("Embedding provider: sentence-transformers (all-MiniLM-L6-v2)")
            return
        except ImportError:
            pass

        self._provider = "hash"
        self._dim = LOCAL_DIM
        logger.info("Embedding provider: hash fallback (no semantic similarity)")

    async def embed(self, text: str) -> np.ndarray:
        cache_key = hashlib.md5(text.encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        vec = await self._embed_impl(text)
        self._cache[cache_key] = vec
        if len(self._cache) > 5000:
            oldest = list(self._cache.keys())[:1000]
            for k in oldest:
                del self._cache[k]
        return vec

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        results = []
        uncached = []
        uncached_idx = []

        for i, text in enumerate(texts):
            cache_key = hashlib.md5(text.encode()).hexdigest()
            if cache_key in self._cache:
                results.append(self._cache[cache_key])
            else:
                results.append(None)
                uncached.append(text)
                uncached_idx.append(i)

        if uncached:
            if self._provider == "openai":
                vecs = await self._openai_batch(uncached)
            else:
                vecs = [await self._embed_impl(t) for t in uncached]
            for idx, vec in zip(uncached_idx, vecs):
                cache_key = hashlib.md5(uncached[uncached_idx.index(idx)].encode()).hexdigest()
                self._cache[cache_key] = vec
                results[idx] = vec

        return results

    async def _embed_impl(self, text: str) -> np.ndarray:
        if self._provider == "openai":
            return await self._openai_embed(text)
        elif self._provider == "sentence_transformers":
            return self._local_embed(text)
        else:
            return self._hash_embed(text)

    async def _openai_embed(self, text: str) -> np.ndarray:
        import httpx
        api_key = os.getenv("OPENAI_API_KEY", "")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "text-embedding-3-small", "input": text[:8000]},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            vec = data["data"][0]["embedding"]
            return np.array(vec, dtype=np.float32)

    async def _openai_batch(self, texts: list[str]) -> list[np.ndarray]:
        import httpx
        api_key = os.getenv("OPENAI_API_KEY", "")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "text-embedding-3-small", "input": [t[:8000] for t in texts]},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [np.array(d["embedding"], dtype=np.float32) for d in sorted_data]

    def _local_embed(self, text: str) -> np.ndarray:
        vec = self._model.encode(text[:2000], normalize_embeddings=True)
        return np.array(vec, dtype=np.float32)

    def _hash_embed(self, text: str) -> np.ndarray:
        h = hashlib.sha256(text.lower().encode()).digest()
        vec = np.frombuffer(h * (self._dim * 4 // len(h) + 1), dtype=np.float32)[:self._dim]
        vec = vec / (np.linalg.norm(vec) + 1e-8)
        return vec
