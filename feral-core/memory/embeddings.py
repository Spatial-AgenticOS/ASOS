"""
FERAL Embedding Engine
========================
Provides vector embeddings for semantic memory search.

Vector Index Strategy (matches OpenClaw's approach):
  1. Try sqlite-vec extension → vec0 virtual table with vec_distance_cosine
  2. Fall back to numpy brute-force scan (degraded, still works)

Embedding Providers:
  1. OpenAI text-embedding-3-small (1536d)
  2. Local sentence-transformers (384d)
  3. Hash fallback (no semantic similarity — development only)
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import struct
from typing import Optional

import numpy as np

logger = logging.getLogger("feral.memory.embeddings")

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
    return np.frombuffer(blob, dtype=np.float32).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ─────────────────────────────────────────────
# sqlite-vec integration
# ─────────────────────────────────────────────

_SQLITE_VEC_AVAILABLE: Optional[bool] = None


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Attempt to load the sqlite-vec extension. Cache the result."""
    global _SQLITE_VEC_AVAILABLE
    if _SQLITE_VEC_AVAILABLE is False:
        return False
    if _SQLITE_VEC_AVAILABLE is True:
        try:
            conn.enable_load_extension(True)
            import sqlite_vec
            sqlite_vec.load(conn)
            return True
        except Exception:
            _SQLITE_VEC_AVAILABLE = False
            return False

    try:
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        _SQLITE_VEC_AVAILABLE = True
        logger.info("sqlite-vec loaded — using vec0 virtual table for vector search")
        return True
    except ImportError:
        logger.info("sqlite-vec not installed — using numpy fallback for vector search")
        _SQLITE_VEC_AVAILABLE = False
        return False
    except Exception as e:
        logger.info(f"sqlite-vec load failed ({e}) — using numpy fallback")
        _SQLITE_VEC_AVAILABLE = False
        return False


def sqlite_vec_available() -> bool:
    """Check if sqlite-vec can be loaded."""
    global _SQLITE_VEC_AVAILABLE
    if _SQLITE_VEC_AVAILABLE is not None:
        return _SQLITE_VEC_AVAILABLE
    try:
        conn = sqlite3.connect(":memory:")
        result = _try_load_sqlite_vec(conn)
        conn.close()
        return result
    except Exception:
        _SQLITE_VEC_AVAILABLE = False
        return False


class VectorIndex:
    """
    Indexed vector search using sqlite-vec (vec0 virtual table)
    with automatic fallback to brute-force numpy scan.
    """

    def __init__(self, db_path: str, dimension: int, table_name: str = "vec_index"):
        self._db_path = db_path
        self._dim = dimension
        self._table_name = table_name
        self._use_vec = False
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        if self._use_vec:
            _try_load_sqlite_vec(conn)
        return conn

    def _init(self):
        self._use_vec = sqlite_vec_available()
        conn = self._conn()
        if self._use_vec:
            try:
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS {self._table_name}
                    USING vec0(
                        chunk_id TEXT PRIMARY KEY,
                        embedding FLOAT[{self._dim}]
                    )
                """)
                conn.commit()
                logger.info(f"vec0 table '{self._table_name}' ready (dim={self._dim})")
            except Exception as e:
                logger.warning(f"vec0 creation failed: {e} — falling back to numpy")
                self._use_vec = False
        conn.close()

    @property
    def indexed(self) -> bool:
        return self._use_vec

    def upsert(self, chunk_id: str, embedding: np.ndarray):
        """Insert or update a vector in the index."""
        if not self._use_vec:
            return
        conn = self._conn()
        try:
            blob = vec_to_blob(embedding)
            conn.execute(
                f"INSERT OR REPLACE INTO {self._table_name}(chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, blob),
            )
            conn.commit()
        except Exception as e:
            logger.debug(f"vec0 upsert failed: {e}")
        finally:
            conn.close()

    def upsert_batch(self, items: list[tuple[str, np.ndarray]]):
        if not self._use_vec or not items:
            return
        conn = self._conn()
        try:
            conn.executemany(
                f"INSERT OR REPLACE INTO {self._table_name}(chunk_id, embedding) VALUES (?, ?)",
                [(cid, vec_to_blob(vec)) for cid, vec in items],
            )
            conn.commit()
        except Exception as e:
            logger.debug(f"vec0 batch upsert failed: {e}")
        finally:
            conn.close()

    def delete(self, chunk_id: str):
        if not self._use_vec:
            return
        conn = self._conn()
        try:
            conn.execute(f"DELETE FROM {self._table_name} WHERE chunk_id = ?", (chunk_id,))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def search(self, query_vec: np.ndarray, limit: int = 20) -> list[tuple[str, float]]:
        """
        Search for nearest vectors. Returns [(chunk_id, distance), ...].
        Uses vec_distance_cosine when sqlite-vec is available.
        """
        if not self._use_vec:
            return []
        conn = self._conn()
        try:
            blob = vec_to_blob(query_vec)
            rows = conn.execute(f"""
                SELECT chunk_id, distance
                FROM {self._table_name}
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            """, (blob, limit)).fetchall()
            return [(r["chunk_id"], float(r["distance"])) for r in rows]
        except Exception as e:
            logger.debug(f"vec0 search failed: {e}")
            return []
        finally:
            conn.close()

    def search_cosine(self, query_vec: np.ndarray, limit: int = 20) -> list[tuple[str, float]]:
        """
        Search returning cosine similarity (1.0 = identical).
        vec_distance_cosine returns distance (0 = identical), so we convert.
        """
        results = self.search(query_vec, limit)
        return [(cid, 1.0 - dist) for cid, dist in results]

    @property
    def count(self) -> int:
        if not self._use_vec:
            return 0
        conn = self._conn()
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {self._table_name}").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0
        finally:
            conn.close()


# ─────────────────────────────────────────────
# Embedding queue for reliable async embedding
# ─────────────────────────────────────────────

class EmbedQueue:
    """
    Reliable async embedding queue. Items are retried on failure
    instead of being silently dropped (unlike fire-and-forget).
    """

    def __init__(self, embedder: "EmbeddingProvider", vector_index: Optional[VectorIndex] = None):
        self._embedder = embedder
        self._vector_index = vector_index
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    def enqueue(self, chunk_id: str, text: str, source_table: str, source_id: str,
                chunk_index: int, db_path: str):
        try:
            self._queue.put_nowait({
                "chunk_id": chunk_id, "text": text, "source_table": source_table,
                "source_id": source_id, "chunk_index": chunk_index, "db_path": db_path,
            })
        except asyncio.QueueFull:
            logger.warning("Embed queue full — dropping oldest")

    async def _process_loop(self):
        import time
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return

            retries = 3
            for attempt in range(retries):
                try:
                    vec = await self._embedder.embed(item["text"])
                    blob = vec_to_blob(vec)
                    conn = sqlite3.connect(item["db_path"])
                    conn.execute("PRAGMA busy_timeout=5000")
                    conn.execute(
                        """INSERT OR REPLACE INTO memory_chunks
                           (id, source_table, source_id, chunk_index, text_content, embedding, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (item["chunk_id"], item["source_table"], item["source_id"],
                         item["chunk_index"], item["text"][:2000], blob, time.time()),
                    )
                    conn.commit()
                    conn.close()
                    if self._vector_index:
                        self._vector_index.upsert(item["chunk_id"], vec)
                    break
                except Exception as e:
                    if attempt == retries - 1:
                        logger.warning(f"Embed failed after {retries} attempts for {item['chunk_id']}: {e}")
                    else:
                        await asyncio.sleep(1.0 * (attempt + 1))

    @property
    def pending(self) -> int:
        return self._queue.qsize()


# ─────────────────────────────────────────────
# Embedding Provider
# ─────────────────────────────────────────────

class EmbeddingProvider:
    """Pluggable embedding provider with auto-detection and LRU cache."""

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
    def provider_name(self) -> str:
        return self._provider or "none"

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
        results: list[Optional[np.ndarray]] = [None] * len(texts)
        uncached = []
        uncached_idx = []

        for i, text in enumerate(texts):
            cache_key = hashlib.md5(text.encode()).hexdigest()
            if cache_key in self._cache:
                results[i] = self._cache[cache_key]
            else:
                uncached.append(text)
                uncached_idx.append(i)

        if uncached:
            if self._provider == "openai":
                vecs = await self._openai_batch(uncached)
            else:
                vecs = [await self._embed_impl(t) for t in uncached]
            for j, idx in enumerate(uncached_idx):
                cache_key = hashlib.md5(uncached[j].encode()).hexdigest()
                self._cache[cache_key] = vecs[j]
                results[idx] = vecs[j]

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
        return vec.copy()
