"""Pluggable memory backends.

The default backend is sqlite-vec (with a numpy fallback for platforms
that lack the extension). Users can switch to Chroma, Qdrant, or a
future backend by setting ``config.memory_backend`` and installing the
optional extra that ships the backend's client library
(``feral-ai[memory-chroma]``, ``feral-ai[memory-qdrant]``).

Every backend implements the same :class:`MemoryBackend` Protocol so
skills calling the memory store are backend-agnostic. Adding a new
backend is a matter of adding one adapter file that conforms.
"""

from .base import MemoryBackend, MemoryRecord, load_backend

__all__ = ["MemoryBackend", "MemoryRecord", "load_backend"]
