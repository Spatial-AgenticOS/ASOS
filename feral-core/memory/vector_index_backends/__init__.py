"""Pluggable sync ``VectorIndex`` backends used by :class:`MemoryStore`.

This sits **alongside** the async :mod:`memory.backends` layer (which
exposes an async :class:`MemoryBackend` Protocol for skill code that
wants explicit async semantics). The two abstractions cover the same
storage targets (sqlite-vec, Chroma, Qdrant) from two angles:

* :class:`memory.backends.MemoryBackend` — async surface, suited for
  skill code that already runs on the event loop.
* :class:`memory.vector_index_backends.VectorIndexBackend` — sync
  surface that ``MemoryStore`` injects in place of the legacy
  hard-wired :class:`memory.embeddings.VectorIndex`. Chroma and Qdrant
  Python clients are sync, so this layer has no async/sync bridging
  ceremony.

Adding a third-party backend is a matter of dropping a module in here
(or registering via :func:`register_backend`) that exposes a
``create(dim, **cfg) -> VectorIndexBackend`` factory.

The brain selects the active backend at boot from
``settings.memory.backend`` (default ``sqlite_vec``). If the chosen
backend's optional dependency is missing or the backend can't construct,
boot fails loudly — there is no silent fall-back to sqlite-vec.

See ``audit-r12 D4`` (the "selector is theater" defect) for the
historical context.
"""

from __future__ import annotations

from .base import VectorIndexBackend, load_vector_index, register_backend

__all__ = ["VectorIndexBackend", "load_vector_index", "register_backend"]
