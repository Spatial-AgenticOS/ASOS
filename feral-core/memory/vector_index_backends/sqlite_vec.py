"""Default sqlite-vec backend for :class:`VectorIndexBackend`.

Wraps the long-standing :class:`memory.embeddings.VectorIndex` (which
owns the ``vec0`` virtual table when the sqlite-vec extension is
installed, with a numpy brute-force fallback when it isn't). Existing
deploys see no behaviour change — this is the same code path that has
shipped with FERAL since 2026-04 — just routed through the new
Protocol-typed selector so the brain has one wiring point for "the
configured backend" instead of a hardcoded import.

No external dependency: sqlite-vec is optional at the SQLite layer,
not at the Python-package layer, so this backend is always loadable.
The ``indexed`` property reports whether the extension is actually
available on the host.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

import numpy as np

from config.loader import feral_data_home
from memory.embeddings import VectorIndex

logger = logging.getLogger("feral.memory.vector_index_backends.sqlite_vec")


class SQLiteVecIndex:
    """Thin Protocol-typed adapter over :class:`VectorIndex`.

    Forwards every method 1:1 so the legacy code path that uses
    :class:`VectorIndex` directly (anything calling
    ``MemoryStore.refresh()`` / sync-engine introspection) continues to
    work. New code paths can rely on the Protocol surface only.
    """

    backend_id: str = "sqlite_vec"

    def __init__(self, *, dim: int, db_path: Optional[str] = None,
                 table_name: str = "vec_chunks") -> None:
        if db_path is None:
            data_dir = feral_data_home()
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "memory.db")
        self._inner = VectorIndex(db_path=db_path, dimension=dim, table_name=table_name)
        self.dim = dim
        self.db_path = db_path

    @property
    def indexed(self) -> bool:
        return self._inner.indexed

    @property
    def count(self) -> int:
        return self._inner.count

    def upsert(self, chunk_id: str, embedding: np.ndarray) -> None:
        self._inner.upsert(chunk_id, embedding)

    def upsert_batch(self, items: Iterable[tuple[str, np.ndarray]]) -> None:
        self._inner.upsert_batch(list(items))

    def delete(self, chunk_id: str) -> None:
        self._inner.delete(chunk_id)

    def search(self, query_vec: np.ndarray, limit: int = 20) -> list[tuple[str, float]]:
        return self._inner.search(query_vec, limit)

    def search_cosine(self, query_vec: np.ndarray, limit: int = 20) -> list[tuple[str, float]]:
        return self._inner.search_cosine(query_vec, limit)

    def close(self) -> None:
        # VectorIndex opens connections per call (no persistent handle)
        # so there is nothing explicit to release. Defined for Protocol
        # parity with backends that DO hold long-lived handles.
        pass

    @property
    def inner(self) -> VectorIndex:
        """Escape hatch for callers that still need the underlying
        :class:`VectorIndex` (e.g. ``EmbedQueue`` for its sqlite-specific
        write-through optimisation). Kept narrow on purpose — new code
        should use the Protocol surface."""
        return self._inner


def create(*, dim: int, db_path: Optional[str] = None,
           table_name: str = "vec_chunks", **_: Any) -> SQLiteVecIndex:
    """Factory the registry calls via :func:`load_vector_index`."""
    return SQLiteVecIndex(dim=dim, db_path=db_path, table_name=table_name)
