"""Chroma memory backend.

Installed via ``pip install feral-ai[memory-chroma]`` or as a
``kind=memory`` item from registry.feral.sh. Uses Chroma's
:class:`PersistentClient` so the DB lives under ``~/.feral/chroma/`` by
default — no external server required.

The Chroma collection is scoped per embedding dimensionality to avoid
silent shape drift when a user switches embedding models.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from config.loader import feral_data_home

from .base import MemoryBackend, MemoryRecord

logger = logging.getLogger("feral.memory.backends.chroma")

_COLLECTION_PREFIX = "feral_memory_dim_"


class ChromaBackend:
    """Chroma-backed memory store."""

    backend_id: str = "chroma"

    def __init__(self, *, dim: int, persist_dir: Optional[str] = None) -> None:
        self.dim = dim
        try:
            import chromadb  # type: ignore
            from chromadb.config import Settings  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "chroma backend requires `pip install feral-ai[memory-chroma]` "
                "(ships chromadb)."
            ) from exc

        data_home = feral_data_home()
        self._persist_dir = str(Path(persist_dir) if persist_dir else data_home / "chroma")
        Path(self._persist_dir).mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=self._persist_dir,
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
        self._collection_name = f"{_COLLECTION_PREFIX}{dim}"
        # ``get_or_create_collection`` is idempotent; we don't pass an
        # embedding function because callers supply vectors directly.
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine", "feral_dim": dim},
        )

    # ─── MemoryBackend surface ─────────────────────────────

    async def upsert(self, records: Iterable[MemoryRecord]) -> None:
        batch = list(records)
        if not batch:
            return
        await asyncio.to_thread(self._upsert_sync, batch)

    def _upsert_sync(self, batch: list[MemoryRecord]) -> None:
        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for rec in batch:
            if rec.embedding is None:
                logger.warning("chroma backend skipping %s: no embedding", rec.id)
                continue
            if len(rec.embedding) != self.dim:
                raise ValueError(
                    f"embedding dim mismatch for {rec.id}: "
                    f"expected {self.dim}, got {len(rec.embedding)}"
                )
            ids.append(rec.id)
            embeddings.append(list(rec.embedding))
            documents.append(rec.text)
            # Chroma metadata must be primitive-valued; flatten for safety.
            metadatas.append({k: _scalar(v) for k, v in (rec.metadata or {}).items()})
        if not ids:
            return
        self._collection.upsert(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
        )

    async def search(
        self,
        query_vec: list[float],
        *,
        limit: int = 10,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[MemoryRecord]:
        if len(query_vec) != self.dim:
            raise ValueError(
                f"query vector dim {len(query_vec)} != backend dim {self.dim}"
            )
        return await asyncio.to_thread(self._search_sync, query_vec, limit, filter or {})

    def _search_sync(
        self, query_vec: list[float], limit: int, filter: dict[str, Any]
    ) -> list[MemoryRecord]:
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_vec],
            "n_results": limit,
        }
        if filter:
            kwargs["where"] = filter
        result = self._collection.query(**kwargs)

        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        mds = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]

        records: list[MemoryRecord] = []
        for i, rec_id in enumerate(ids):
            # chroma cosine distance -> similarity in [0, 1].
            score = 1.0 - float(dists[i]) if i < len(dists) else None
            records.append(
                MemoryRecord(
                    id=rec_id,
                    text=docs[i] if i < len(docs) else "",
                    metadata=mds[i] if i < len(mds) else {},
                    score=score,
                )
            )
        return records

    async def delete(self, ids: Iterable[str]) -> None:
        batch = list(ids)
        if not batch:
            return
        await asyncio.to_thread(lambda: self._collection.delete(ids=batch))

    async def stats(self) -> dict[str, Any]:
        count = await asyncio.to_thread(self._collection.count)
        return {
            "backend": self.backend_id,
            "count": int(count),
            "dim": self.dim,
            "persist_dir": self._persist_dir,
            "collection": self._collection_name,
        }

    async def close(self) -> None:
        # chromadb's PersistentClient flushes on collection calls; nothing
        # explicit to release.
        return None


def _scalar(value: Any) -> Any:
    """Chroma metadata values must be str/int/float/bool. Coerce everything else."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        import json

        return json.dumps(value, default=str)
    except Exception:
        return str(value)


# ─────────────────────────────────────────────────────────────


async def create(
    *, dim: int, persist_dir: Optional[str] = None, **_: Any
) -> MemoryBackend:
    return ChromaBackend(dim=dim, persist_dir=persist_dir)
