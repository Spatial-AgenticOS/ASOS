"""Chroma backend for :class:`VectorIndexBackend`.

Installed via ``pip install feral-ai[memory-chroma]`` or as a
``kind=memory-vec`` item on registry.feral.sh. Uses Chroma's
:class:`PersistentClient` so the database lives under
``~/.feral/chroma/`` by default — no external server required.

Collections are scoped per embedding dimensionality
(``feral_vec_dim_<n>``) to avoid silent shape drift when a user swaps
embedding models. The id-only return shape matches
:class:`memory.embeddings.VectorIndex` exactly so ``MemoryStore`` can
swap backends without changing its hot path.

Why a sync backend when ``memory/backends/chroma.py`` already exists?
That one targets the async :class:`MemoryBackend` Protocol for skill
code that wants async semantics. ``MemoryStore`` is sync, called from
SQLite cursor-mid-transaction and background sweepers; this layer
matches that calling convention without sync/async bridging.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from config.loader import feral_data_home

logger = logging.getLogger("feral.memory.vector_index_backends.chroma")

_COLLECTION_PREFIX = "feral_vec_dim_"


class ChromaVectorIndex:
    """Chroma-backed vector index that satisfies
    :class:`VectorIndexBackend`. Sync only (Chroma's Python client is
    sync) — perfect fit for ``MemoryStore``'s hot path."""

    backend_id: str = "chroma"

    def __init__(
        self,
        *,
        dim: int,
        persist_dir: Optional[str] = None,
        collection: Optional[str] = None,
    ) -> None:
        try:
            import chromadb  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "chroma backend requires `pip install "
                "feral-ai[memory-chroma]`. The wheels for `chromadb` "
                "are large; we don't pull them in by default. "
                f"Underlying error: {exc}"
            ) from exc

        self.dim = dim
        if persist_dir is None:
            persist_dir = str(feral_data_home() / "chroma")
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._persist_dir = persist_dir
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection_name = collection or f"{_COLLECTION_PREFIX}{dim}"
        # `metadata={"hnsw:space": "cosine"}` makes the on-disk index
        # use cosine distance directly; we still convert to similarity
        # in search_cosine() so callers see the same shape they get
        # from the sqlite-vec backend.
        self._coll = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine", "feral.dim": dim},
        )

    @property
    def indexed(self) -> bool:
        # Chroma's collection is the index — if the client opened
        # successfully, the index is available.
        return True

    @property
    def count(self) -> int:
        try:
            return int(self._coll.count())
        except Exception as exc:
            logger.debug("chroma count() failed: %s", exc)
            return 0

    def upsert(self, chunk_id: str, embedding: np.ndarray) -> None:
        vec = np.asarray(embedding, dtype=np.float32)
        if vec.shape[0] != self.dim:
            raise ValueError(
                f"chroma backend dim mismatch: collection dim={self.dim}, "
                f"vector dim={vec.shape[0]}"
            )
        # Chroma's upsert is idempotent by id — exactly the contract
        # this Protocol requires.
        self._coll.upsert(ids=[chunk_id], embeddings=[vec.tolist()])

    def upsert_batch(self, items: Iterable[tuple[str, np.ndarray]]) -> None:
        ids: list[str] = []
        vecs: list[list[float]] = []
        for chunk_id, embedding in items:
            vec = np.asarray(embedding, dtype=np.float32)
            if vec.shape[0] != self.dim:
                raise ValueError(
                    f"chroma backend dim mismatch on chunk_id={chunk_id!r}: "
                    f"collection dim={self.dim}, vector dim={vec.shape[0]}"
                )
            ids.append(chunk_id)
            vecs.append(vec.tolist())
        if not ids:
            return
        self._coll.upsert(ids=ids, embeddings=vecs)

    def delete(self, chunk_id: str) -> None:
        # Chroma's delete is silent on unknown ids — matches Protocol.
        try:
            self._coll.delete(ids=[chunk_id])
        except Exception as exc:
            logger.debug("chroma delete(%r) failed: %s", chunk_id, exc)

    def search(
        self, query_vec: np.ndarray, limit: int = 20
    ) -> list[tuple[str, float]]:
        """Return ``[(chunk_id, distance), ...]`` matching the
        sqlite-vec shape. Chroma already uses cosine distance for our
        collections (configured in ``__init__``)."""
        vec = np.asarray(query_vec, dtype=np.float32)
        if vec.shape[0] != self.dim:
            return []
        try:
            res = self._coll.query(
                query_embeddings=[vec.tolist()],
                n_results=max(1, int(limit)),
                include=["distances"],
            )
        except Exception as exc:
            logger.debug("chroma search failed: %s", exc)
            return []
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        return [(cid, float(d)) for cid, d in zip(ids, dists)]

    def search_cosine(
        self, query_vec: np.ndarray, limit: int = 20
    ) -> list[tuple[str, float]]:
        return [(cid, 1.0 - dist) for cid, dist in self.search(query_vec, limit)]

    def close(self) -> None:
        # PersistentClient has no explicit close; the underlying DB
        # handles flush on drop. Method defined for Protocol parity.
        self._client = None  # type: ignore[assignment]


def create(
    *,
    dim: int,
    persist_dir: Optional[str] = None,
    collection: Optional[str] = None,
    **_: Any,
) -> ChromaVectorIndex:
    return ChromaVectorIndex(dim=dim, persist_dir=persist_dir, collection=collection)
