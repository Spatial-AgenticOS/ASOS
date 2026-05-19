"""Qdrant backend for :class:`VectorIndexBackend`.

Installed via ``pip install feral-ai[memory-qdrant]`` or as a
``kind=memory-vec`` item on registry.feral.sh. Defaults to Qdrant's
local embedded mode (``QdrantClient(path=...)``) so the database lives
under ``~/.feral/qdrant/`` — no external server required. Operators
who want a remote Qdrant pass ``url=`` in ``settings.memory.backend_config``.

Collections are scoped per embedding dimensionality
(``feral_vec_dim_<n>``) to avoid silent shape drift when a user swaps
embedding models. ``size`` matches ``dim`` exactly; cosine distance
matches what sqlite-vec and Chroma return so ``MemoryStore`` can swap
backends without changing its hot path.

Why a sync backend when ``memory/backends/qdrant.py`` already exists?
Same reason as the Chroma analogue: that one targets the async
:class:`MemoryBackend` Protocol for skill code that wants async; this
one targets ``MemoryStore``'s sync hot path. The Qdrant Python client
is sync (the async client is a separate package), so this is a clean
fit.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from config.loader import feral_data_home

logger = logging.getLogger("feral.memory.vector_index_backends.qdrant")

_COLLECTION_PREFIX = "feral_vec_dim_"


class QdrantVectorIndex:
    """Qdrant-backed vector index that satisfies
    :class:`VectorIndexBackend`. Sync only (the Qdrant client is sync
    by default; the async client is a separate package)."""

    backend_id: str = "qdrant"

    def __init__(
        self,
        *,
        dim: int,
        persist_dir: Optional[str] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection: Optional[str] = None,
    ) -> None:
        try:
            from qdrant_client import QdrantClient  # type: ignore
            from qdrant_client.http.models import Distance, VectorParams  # type: ignore
            from qdrant_client.http import models as qm  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "qdrant backend requires `pip install "
                "feral-ai[memory-qdrant]`. Underlying error: " + str(exc)
            ) from exc

        self.dim = dim
        if url is not None:
            self._client = QdrantClient(url=url, api_key=api_key)
        else:
            if persist_dir is None:
                persist_dir = str(feral_data_home() / "qdrant")
            Path(persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=persist_dir)
        self._collection = collection or f"{_COLLECTION_PREFIX}{dim}"
        # Hold a reference to the model module for upsert PointStruct etc.
        self._qm = qm
        # Create the collection if missing. ``recreate_collection`` would
        # wipe vectors on restart — we want idempotent ``ensure``.
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    @property
    def indexed(self) -> bool:
        # If the client opened and the collection exists, the index is
        # available — Qdrant maintains the HNSW graph automatically.
        return True

    @property
    def count(self) -> int:
        try:
            info = self._client.get_collection(collection_name=self._collection)
            return int(getattr(info, "points_count", 0) or 0)
        except Exception as exc:
            logger.debug("qdrant count() failed: %s", exc)
            return 0

    def _make_point(self, chunk_id: str, embedding: np.ndarray):
        return self._qm.PointStruct(
            id=chunk_id, vector=embedding.tolist()
        )

    def upsert(self, chunk_id: str, embedding: np.ndarray) -> None:
        vec = np.asarray(embedding, dtype=np.float32)
        if vec.shape[0] != self.dim:
            raise ValueError(
                f"qdrant backend dim mismatch: collection dim={self.dim}, "
                f"vector dim={vec.shape[0]}"
            )
        self._client.upsert(
            collection_name=self._collection,
            points=[self._make_point(chunk_id, vec)],
            wait=False,
        )

    def upsert_batch(self, items: Iterable[tuple[str, np.ndarray]]) -> None:
        points = []
        for chunk_id, embedding in items:
            vec = np.asarray(embedding, dtype=np.float32)
            if vec.shape[0] != self.dim:
                raise ValueError(
                    f"qdrant backend dim mismatch on chunk_id={chunk_id!r}: "
                    f"collection dim={self.dim}, vector dim={vec.shape[0]}"
                )
            points.append(self._make_point(chunk_id, vec))
        if not points:
            return
        self._client.upsert(
            collection_name=self._collection, points=points, wait=False,
        )

    def delete(self, chunk_id: str) -> None:
        try:
            self._client.delete(
                collection_name=self._collection,
                points_selector=self._qm.PointIdsList(points=[chunk_id]),
                wait=False,
            )
        except Exception as exc:
            logger.debug("qdrant delete(%r) failed: %s", chunk_id, exc)

    def search(
        self, query_vec: np.ndarray, limit: int = 20
    ) -> list[tuple[str, float]]:
        """Returns ``[(chunk_id, distance), ...]`` where distance is in
        ``[0, 2]`` (cosine distance) to match the sqlite-vec shape.
        Qdrant's ``search`` returns ``score`` as similarity in
        ``[-1, 1]``; we convert with ``distance = 1 - score`` (same
        relation Chroma and sqlite-vec use)."""
        vec = np.asarray(query_vec, dtype=np.float32)
        if vec.shape[0] != self.dim:
            return []
        try:
            hits = self._client.search(
                collection_name=self._collection,
                query_vector=vec.tolist(),
                limit=max(1, int(limit)),
                with_payload=False,
                with_vectors=False,
            )
        except Exception as exc:
            logger.debug("qdrant search failed: %s", exc)
            return []
        return [(str(h.id), 1.0 - float(h.score)) for h in hits]

    def search_cosine(
        self, query_vec: np.ndarray, limit: int = 20
    ) -> list[tuple[str, float]]:
        return [(cid, 1.0 - dist) for cid, dist in self.search(query_vec, limit)]

    def close(self) -> None:
        # QdrantClient has no explicit close on the local/embedded mode;
        # the file handle releases on GC. Defined for Protocol parity.
        try:
            self._client.close()  # type: ignore[attr-defined]
        except Exception:
            pass


def create(
    *,
    dim: int,
    persist_dir: Optional[str] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    collection: Optional[str] = None,
    **_: Any,
) -> QdrantVectorIndex:
    return QdrantVectorIndex(
        dim=dim,
        persist_dir=persist_dir,
        url=url,
        api_key=api_key,
        collection=collection,
    )
