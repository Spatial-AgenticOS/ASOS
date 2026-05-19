"""Sync ``VectorIndexBackend`` Protocol — the pluggable vector store
that :class:`MemoryStore` actually queries on its hot path.

Why a sync Protocol when ``memory.backends`` already has an async one?
Because ``MemoryStore`` is sync (called from FastAPI sync paths,
background sweepers, SQLite cursor-mid-transaction). Routing its
queries through an async Protocol would require sync/async bridging
that violates the no-event-loop-reentrancy rule. Chroma and Qdrant
both publish sync Python clients, so a sync Protocol is a clean fit by
construction; the async layer in ``memory.backends`` remains available
for skill code that wants explicit async semantics.

Public surface (intentionally tiny):

    indexed: bool                       # backend reports it's actually indexed
    count: int                          # number of vectors currently stored
    upsert(chunk_id, embedding)         # idempotent by id
    upsert_batch(items)                 # optimised batch path
    delete(chunk_id)                    # silent on unknown id
    search(query_vec, limit)            # top-k, returns (id, distance)
    search_cosine(query_vec, limit)     # top-k, returns (id, similarity)
    close()                             # release handles

This is exactly the surface :class:`memory.embeddings.VectorIndex`
already exposes; the legacy sqlite-vec implementation conforms without
modification.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Iterable, Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger("feral.memory.vector_index_backends")


@runtime_checkable
class VectorIndexBackend(Protocol):
    """The minimal sync contract every vector index backend must satisfy.

    ``indexed`` reports whether the backend actually has an index up
    and running (e.g. the sqlite-vec extension loaded successfully).
    ``False`` means a degraded mode where ``upsert`` is a no-op and
    ``search_cosine`` returns ``[]``; ``MemoryStore`` then falls back
    to its FTS5 keyword search. This degradation policy is the same
    for every backend — silent skip rather than crash on first use.
    """

    backend_id: str
    indexed: bool
    count: int

    def upsert(self, chunk_id: str, embedding: np.ndarray) -> None: ...
    def upsert_batch(self, items: Iterable[tuple[str, np.ndarray]]) -> None: ...
    def delete(self, chunk_id: str) -> None: ...
    def search(self, query_vec: np.ndarray, limit: int = 20) -> list[tuple[str, float]]: ...
    def search_cosine(self, query_vec: np.ndarray, limit: int = 20) -> list[tuple[str, float]]: ...
    def close(self) -> None: ...


# ─────────────────────────────────────────────
# Registry + sync loader
# ─────────────────────────────────────────────

_REGISTRY: dict[str, str] = {
    # backend_id -> dotted module path relative to feral-core
    "sqlite_vec": "memory.vector_index_backends.sqlite_vec",
    "chroma": "memory.vector_index_backends.chroma",
    "qdrant": "memory.vector_index_backends.qdrant",
}


def register_backend(backend_id: str, module_path: str) -> None:
    """Register a backend module path so :func:`load_vector_index` can
    find it. Third-party backends published as ``kind=memory-vec`` on
    registry.feral.sh land in ``~/.feral/vector-index-backends/<id>/``
    and call this at import time."""
    _REGISTRY[backend_id] = module_path


def load_vector_index(
    backend_id: str, *, dim: int, **config: Any
) -> VectorIndexBackend:
    """Synchronously instantiate the configured vector-index backend.

    The audit-r12 D4 "selector is theater" defect was that
    :class:`memory.MemoryStore` hardwired
    :class:`memory.embeddings.VectorIndex` at boot regardless of
    ``settings.memory.backend``. This function is the wiring that
    closes the loop: ``BrainState.__init__`` calls it with the
    configured backend id, then injects the result into
    ``MemoryStore``.

    Raises
    ------
    ValueError
        ``backend_id`` is not registered. Lists known ids in the
        error message.
    ImportError
        The backend module's optional dependency (``chromadb``,
        ``qdrant-client``, …) is not installed. Suggests the right
        ``feral-ai[memory-<id>]`` extra.
    TypeError
        The backend module's ``create`` factory returned something
        that does not satisfy :class:`VectorIndexBackend`.

    No silent fall-back to sqlite-vec — a misconfigured backend MUST
    surface at boot, never at first query.
    """
    if backend_id not in _REGISTRY:
        raise ValueError(
            f"unknown memory vector-index backend {backend_id!r}. "
            f"Known: {sorted(_REGISTRY.keys())}. "
            "Install a community backend via `feral install <id>` if "
            "it's on registry.feral.sh."
        )

    module_path = _REGISTRY[backend_id]
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"vector-index backend {backend_id!r} could not be imported: "
            f"{exc}. Install with `pip install feral-ai[memory-"
            f"{backend_id}]` (or `feral install <registry_item_id>` for "
            "community backends)."
        ) from exc

    factory = getattr(module, "create", None)
    if factory is None:
        raise ImportError(
            f"backend module {module_path!r} exposes no "
            "`create(dim, **cfg)` factory. Every vector-index backend "
            "must provide one."
        )

    backend = factory(dim=dim, **config)
    if not isinstance(backend, VectorIndexBackend):
        raise TypeError(
            f"vector-index factory for {backend_id!r} returned "
            f"{type(backend).__name__}, which does not satisfy the "
            "VectorIndexBackend Protocol (missing one of indexed, "
            "count, upsert, upsert_batch, delete, search, "
            "search_cosine, close)."
        )
    logger.info(
        "vector index backend loaded: %s (indexed=%s, count=%d)",
        backend_id, backend.indexed, backend.count,
    )
    return backend
