"""MemoryBackend Protocol — the pluggable vector-store contract.

FERAL's semantic memory writes go to whichever backend the user
selected in ``~/.feral/config.yaml`` under the ``memory_backend`` key
(default ``sqlite_vec``). Every backend implementation (sqlite_vec,
chroma, qdrant, and future ones published on registry.feral.sh under
``kind=memory``) conforms to the Protocol below so orchestrator +
skill code never has to branch on backend type.

Design rules
------------
* Async surface only. Even the default sqlite_vec backend wraps its
  synchronous calls in ``asyncio.to_thread`` so callers stay async.
* IDs are opaque strings owned by the caller — backends never mint
  their own.
* The vector dimensionality is fixed at backend construction time to
  keep per-insert payloads small.
* Errors surface as exceptions, never swallowed booleans. Callers
  decide whether to degrade.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Optional, Protocol, runtime_checkable

logger = logging.getLogger("feral.memory.backends")


@dataclass
class MemoryRecord:
    """One row written to or read from a memory backend.

    ``embedding`` is optional on write: backends that compute their own
    embeddings may ignore it. It is always populated on read.
    """

    id: str
    text: str
    embedding: Optional[list[float]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    score: Optional[float] = None


@runtime_checkable
class MemoryBackend(Protocol):
    """The minimal contract every memory backend must satisfy."""

    backend_id: str
    dim: int

    async def upsert(self, records: Iterable[MemoryRecord]) -> None:
        """Insert or replace a batch of records. MUST be idempotent by id."""
        ...

    async def search(
        self,
        query_vec: list[float],
        *,
        limit: int = 10,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[MemoryRecord]:
        """Top-k vector search. ``filter`` is backend-specific metadata filter."""
        ...

    async def delete(self, ids: Iterable[str]) -> None:
        """Remove by id. Unknown ids MUST NOT raise."""
        ...

    async def stats(self) -> dict[str, Any]:
        """Return diagnostic counts + backend-specific info.

        Expected keys (best-effort):
            - ``backend`` (string, the backend_id)
            - ``count`` (int, number of records)
            - ``dim`` (int, vector dimensionality)
        """
        ...

    async def close(self) -> None:
        """Release resources (connections, file handles). Idempotent."""
        ...


# ─────────────────────────────────────────────────────────────
# Loader — picks the configured backend at startup.
# ─────────────────────────────────────────────────────────────

_REGISTRY: dict[str, str] = {
    # backend_id -> dotted module path relative to feral-core
    "sqlite_vec": "memory.backends.sqlite_vec",
    "chroma": "memory.backends.chroma",
    "qdrant": "memory.backends.qdrant",
}


def register_backend(backend_id: str, module_path: str) -> None:
    """Register a backend module path so ``load_backend`` can find it.

    Third-party backends published to registry.feral.sh under
    ``kind=memory`` land in ``~/.feral/memory-backends/<id>/`` and can
    call this at import time.
    """
    _REGISTRY[backend_id] = module_path


async def load_backend(
    backend_id: str, *, dim: int, **config: Any
) -> MemoryBackend:
    """Instantiate the configured memory backend.

    Raises :class:`ValueError` if the backend_id is unknown and
    :class:`ImportError` (with a friendly message) if the required
    optional extra isn't installed.
    """
    if backend_id not in _REGISTRY:
        raise ValueError(
            f"unknown memory backend '{backend_id}'. "
            f"Known: {sorted(_REGISTRY.keys())}. "
            "Install a community backend via `feral install <id>` if it's on "
            "registry.feral.sh."
        )

    module_path = _REGISTRY[backend_id]
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"backend '{backend_id}' is not installed — "
            f"`pip install feral-ai[memory-{backend_id}]` or "
            f"`feral install <registry_item_id>`. Underlying error: {exc}"
        ) from exc

    factory = getattr(module, "create", None)
    if factory is None:
        raise ImportError(
            f"backend module '{module_path}' exposes no `create(dim, **cfg)` "
            "factory. Every backend must provide one."
        )

    backend = await factory(dim=dim, **config)
    if not isinstance(backend, MemoryBackend):
        raise TypeError(
            f"backend factory for '{backend_id}' returned "
            f"{type(backend).__name__}, which does not satisfy the MemoryBackend "
            "Protocol."
        )
    logger.info("memory backend loaded: %s (dim=%d)", backend_id, backend.dim)
    return backend


async def iter_records(
    records: list[MemoryRecord], *, chunk: int = 128
) -> AsyncIterator[list[MemoryRecord]]:
    """Utility: yield ``records`` in batches for backends that prefer it."""
    for i in range(0, len(records), chunk):
        yield records[i : i + chunk]
