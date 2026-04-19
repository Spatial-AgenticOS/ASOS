"""Contract tests for MemoryBackend adapters.

Every backend listed in :data:`_BACKENDS` goes through the exact same
four-step round-trip: upsert a few records, search for the closest one,
delete one, confirm stats report matches. If the backend's optional
dependency isn't installed the test is skipped — CI on a minimal
install still runs the sqlite_vec contract, and adding a backend
doesn't break the suite for anyone missing its library.
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import pytest

from memory.backends.base import MemoryRecord, load_backend

pytestmark = pytest.mark.asyncio


_BACKENDS: list[tuple[str, str]] = [
    # (backend_id, required_module_to_skip_if_missing)
    ("sqlite_vec", "memory.backends.sqlite_vec"),
    ("chroma", "chromadb"),
    ("qdrant", "qdrant_client"),
]

_DIM = 8
_SAMPLE_VECS = [
    ("rec_a", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "alpha"),
    ("rec_b", [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "beta"),
    ("rec_c", [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0], "gamma"),
]


def _skip_if_missing(module: str) -> None:
    try:
        importlib.import_module(module)
    except ImportError:
        pytest.skip(f"{module} not installed — skipping backend test")


@pytest.fixture(params=_BACKENDS, ids=lambda p: p[0])
def backend_spec(request):
    backend_id, required_module = request.param
    _skip_if_missing(required_module)
    return backend_id


async def _make_backend(backend_id: str, tmp_path: Path):
    # Route each backend to an isolated tmp dir so tests don't stomp on
    # each other or on a developer's real ~/.feral/.
    if backend_id == "sqlite_vec":
        return await load_backend(
            backend_id, dim=_DIM, db_path=str(tmp_path / "memory.db")
        )
    if backend_id == "chroma":
        return await load_backend(
            backend_id, dim=_DIM, persist_dir=str(tmp_path / "chroma")
        )
    if backend_id == "qdrant":
        return await load_backend(
            backend_id, dim=_DIM, persist_dir=str(tmp_path / "qdrant")
        )
    raise RuntimeError(f"no _make_backend branch for {backend_id}")


async def test_backend_round_trip(backend_spec, tmp_path):
    backend = await _make_backend(backend_spec, tmp_path)
    try:
        records = [
            MemoryRecord(id=rid, text=txt, embedding=vec, metadata={"tag": txt})
            for rid, vec, txt in _SAMPLE_VECS
        ]

        await backend.upsert(records)

        # The query vector is closest to rec_a (identical first basis vector).
        results = await backend.search([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], limit=3)
        assert len(results) >= 1, f"{backend_spec} returned no results"
        assert results[0].id == "rec_a", f"{backend_spec} top-1 should be rec_a, got {results[0].id}"

        await backend.delete(["rec_a"])
        after = await backend.search([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], limit=3)
        ids = [r.id for r in after]
        assert "rec_a" not in ids, f"{backend_spec} did not delete rec_a"

        stats = await backend.stats()
        assert stats["backend"] == backend_spec
        assert stats["dim"] == _DIM
        assert isinstance(stats.get("count"), int)
    finally:
        await backend.close()


async def test_backend_rejects_wrong_dim(backend_spec, tmp_path):
    backend = await _make_backend(backend_spec, tmp_path)
    try:
        with pytest.raises(ValueError):
            await backend.upsert(
                [MemoryRecord(id="bad", text="x", embedding=[1.0, 2.0, 3.0])]
            )
        with pytest.raises(ValueError):
            await backend.search([1.0, 2.0, 3.0], limit=1)
    finally:
        await backend.close()


async def test_backend_delete_unknown_ids_noop(backend_spec, tmp_path):
    backend = await _make_backend(backend_spec, tmp_path)
    try:
        # Must not raise.
        await backend.delete(["does_not_exist"])
    finally:
        await backend.close()
