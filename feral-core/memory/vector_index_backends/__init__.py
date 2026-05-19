"""Pluggable async ``VectorIndexBackend`` backends used by :class:`MemoryStore`.

v2026.5.33 — Option C async rewrite. The Protocol and every adapter
are async-native; :class:`MemoryStore` awaits backend operations
directly without thread bridging. The three first-party backends pick
the best path for their underlying client:

* ``sqlite_vec`` (default) — talks to SQLite via ``aiosqlite``.
* ``chroma`` — wraps Chroma's sync ``PersistentClient`` in
  ``asyncio.to_thread`` at the adapter boundary (Chroma's
  ``AsyncHttpClient`` requires a remote HTTP server, which we don't
  ship by default).
* ``qdrant`` — uses :class:`qdrant_client.AsyncQdrantClient`.

Adding a third-party backend is a matter of dropping a module in here
(or registering via :func:`register_backend`) that exposes a
``create(dim, **cfg) -> VectorIndexBackend`` factory whose returned
object satisfies the async Protocol.

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
