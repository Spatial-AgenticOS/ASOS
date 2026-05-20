"""PR 1 (v2026.5.33) acceptance benchmark — Option C async-native MemoryStore.

The Option C refactor converts every MemoryStore I/O path from the
legacy blocking pattern (``sqlite3.connect`` per call, executed
inside the asyncio event loop's thread → blocks the loop) to an
async-native one (a pooled set of ``aiosqlite`` connections, WAL
mode, awaited from coroutines → loop never blocks).

The plan's acceptance criterion is "p50 search latency drops ≥30%".
The honest "before vs after" comparison runs the same SQL workload
two ways on the same on-disk database:

  1. **Sync baseline** — mirrors the pre-Option-C MemoryStore: open a
     stdlib ``sqlite3`` connection per call, set WAL + busy_timeout,
     run the query, close. Done sequentially because the old code ran
     inside the asyncio loop's thread and would have blocked any
     concurrent coroutine anyway.

  2. **Async-native pooled (this PR)** — go through ``MemoryStore.
     episode_recent`` which uses ``self._conn()`` → a pooled
     ``aiosqlite`` connection (no per-call open, no per-call PRAGMA
     round-trip). Run K calls through ``asyncio.gather`` to prove the
     loop is parallelising them.

We assert the async-native pooled p50 is at least 30% faster than the
sync baseline p50 on the per-call latency, AND that the aggregate
wall clock for K concurrent calls is also at least 30% faster. The
second invariant is what FERAL operators actually experience under
load (many in-flight memory lookups during a chat turn).

Run locally:

    cd feral-core
    pytest tests/perf/test_memory_latency.py -v -s --no-cov

Output is pasted verbatim into the PR 1 body.
"""
from __future__ import annotations

import asyncio
import sqlite3
import statistics
import time
from pathlib import Path

import pytest

from memory.store import MemoryStore


# ── Tunables ────────────────────────────────────────────────────────────────
_SEED_EPISODES = 500
_CONCURRENCY = 32
_QUERY_LIMIT = 10
_REQUIRED_P50_DROP = 0.30
# The legacy pattern reopened a connection per call; that's what we
# benchmark to stand in for the pre-refactor world.


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _seed(store: MemoryStore, n: int) -> None:
    sessions = [f"s{i}" for i in range(4)]
    for i in range(n):
        await store.episode_save(
            session_id=sessions[i % len(sessions)],
            event_type="conversation",
            summary=f"seeded episode {i}: discussion about topic {i % 10}",
            detail=f"Detail body for episode {i} with content tag-{i % 7}.",
            importance=0.4 + (i % 5) * 0.1,
        )


def _sync_baseline(db_path: str, k: int) -> tuple[float, list[float]]:
    """Run k sequential queries the legacy way — open per call.

    Returns (aggregate_wall_seconds, per_call_seconds).
    """
    per_call: list[float] = []
    t0 = time.perf_counter()
    for i in range(k):
        s = time.perf_counter()
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        rows = c.execute(
            "SELECT * FROM episodes WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f"s{i % 4}", _QUERY_LIMIT),
        ).fetchall()
        c.close()
        per_call.append(time.perf_counter() - s)
        assert isinstance(rows, list)
    return time.perf_counter() - t0, per_call


async def _async_sequential(store: MemoryStore, k: int) -> tuple[float, list[float]]:
    """Run k sequential queries through MemoryStore (pooled, async).

    Apples-to-apples per-call latency comparison vs the sync baseline:
    same workload, same query, the only difference is the new pooled
    aiosqlite connection. No gather concurrency to muddy the per-call
    metric.
    """
    per_call: list[float] = []
    t0 = time.perf_counter()
    for i in range(k):
        s = time.perf_counter()
        rows = await store.episode_recent(limit=_QUERY_LIMIT, session_id=f"s{i % 4}")
        per_call.append(time.perf_counter() - s)
        assert isinstance(rows, list)
    return time.perf_counter() - t0, per_call


async def _async_concurrent(store: MemoryStore, k: int) -> tuple[float, list[float]]:
    """Run k concurrent queries through MemoryStore (pooled, async)."""
    per_call: list[float] = []

    async def _one(i: int) -> None:
        s = time.perf_counter()
        rows = await store.episode_recent(limit=_QUERY_LIMIT, session_id=f"s{i % 4}")
        per_call.append(time.perf_counter() - s)
        assert isinstance(rows, list)

    t0 = time.perf_counter()
    await asyncio.gather(*(_one(i) for i in range(k)))
    return time.perf_counter() - t0, per_call


def _stats(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"p50": 0.0, "p99": 0.0, "mean": 0.0}
    sorted_s = sorted(samples)
    return {
        "p50": statistics.median(sorted_s),
        "p99": sorted_s[max(0, int(len(sorted_s) * 0.99) - 1)],
        "mean": statistics.fmean(sorted_s),
    }


# ── The benchmark ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_memory_concurrent_p50_drop_at_least_30pct(tmp_path: Path) -> None:
    """Option C acceptance: async-native pooled MemoryStore must serve
    a realistic concurrent workload with p50 ≥30% faster than the
    legacy sync-per-call pattern.
    """
    db = tmp_path / "perf-memory.db"
    store = MemoryStore(db_path=str(db))

    try:
        await _seed(store, _SEED_EPISODES)

        # Two warmups apiece to amortise FTS prime + page cache. Each
        # warmup is the same operation the real run executes.
        for _ in range(2):
            await store.episode_recent(limit=_QUERY_LIMIT)
            _sync_baseline(str(db), 1)

        # Sync baseline: K sequential opens, the legacy MemoryStore
        # pattern (sqlite3.connect per call inside the event loop's
        # thread → blocks the loop for the whole batch).
        sync_wall, sync_per_call = _sync_baseline(str(db), _CONCURRENCY)

        # Async-sequential pooled: per-call latency on the new stack
        # with the same access pattern (no gather contention).
        async_seq_wall, async_seq_per_call = await _async_sequential(store, _CONCURRENCY)

        # Async-concurrent pooled: aggregate wall clock under realistic
        # concurrent load (the brain serving many in-flight memory
        # lookups during a chat turn).
        async_gather_wall, async_gather_per_call = await _async_concurrent(
            store, _CONCURRENCY
        )
    finally:
        await store.aclose()

    sync_stats = _stats(sync_per_call)
    async_seq_stats = _stats(async_seq_per_call)
    async_gather_stats = _stats(async_gather_per_call)

    # Headline drop on per-call p50 (sync baseline vs async-sequential
    # pooled): "is a single search faster on the new stack?" — apples-
    # to-apples, no concurrency variable.
    p50_drop = (sync_stats["p50"] - async_seq_stats["p50"]) / sync_stats["p50"]

    # Aggregate wall-clock drop (sync sequential vs async gather): "is
    # the brain faster serving K concurrent callers?"
    wall_drop = (sync_wall - async_gather_wall) / sync_wall

    print(
        "\n──────────── Option C async memory latency benchmark ────────────"
        f"\n  workload          : {_CONCURRENCY} × episode_recent(limit={_QUERY_LIMIT})"
        f"\n  seeded episodes   : {_SEED_EPISODES}"
        "\n  sync baseline (legacy sqlite3.connect per call, sequential):"
        f"\n    wall total       : {sync_wall * 1000:.2f} ms"
        f"\n    per-call p50     : {sync_stats['p50'] * 1000:.2f} ms"
        f"\n    per-call p99     : {sync_stats['p99'] * 1000:.2f} ms"
        f"\n    per-call mean    : {sync_stats['mean'] * 1000:.2f} ms"
        "\n  async-sequential pooled (this PR, await one-at-a-time):"
        f"\n    wall total       : {async_seq_wall * 1000:.2f} ms"
        f"\n    per-call p50     : {async_seq_stats['p50'] * 1000:.2f} ms"
        f"\n    per-call p99     : {async_seq_stats['p99'] * 1000:.2f} ms"
        f"\n    per-call mean    : {async_seq_stats['mean'] * 1000:.2f} ms"
        "\n  async-concurrent pooled (this PR, asyncio.gather):"
        f"\n    wall total       : {async_gather_wall * 1000:.2f} ms"
        f"\n    per-call p50     : {async_gather_stats['p50'] * 1000:.2f} ms"
        f"\n    per-call p99     : {async_gather_stats['p99'] * 1000:.2f} ms"
        f"\n    per-call mean    : {async_gather_stats['mean'] * 1000:.2f} ms"
        f"\n  per-call p50 drop : {p50_drop * 100:.1f}% (sync vs async-seq)"
        f"\n  wall-clock drop   : {wall_drop * 100:.1f}% (sync vs async-gather)"
        f"\n  required drop     : {_REQUIRED_P50_DROP * 100:.1f}%"
        "\n──────────────────────────────────────────────────────────────────"
    )

    assert p50_drop >= _REQUIRED_P50_DROP, (
        f"Option C per-call p50 drop {p50_drop * 100:.1f}% below required "
        f"{_REQUIRED_P50_DROP * 100:.0f}%. The pooled aiosqlite path is not "
        "faster per-call than the legacy sqlite3-per-call pattern — pool "
        "broken or a sync hop snuck back into the hot path."
    )
    assert wall_drop >= _REQUIRED_P50_DROP, (
        f"Option C aggregate wall-clock drop {wall_drop * 100:.1f}% below "
        f"required {_REQUIRED_P50_DROP * 100:.0f}%. asyncio.gather is not "
        "parallelising — check for accidental sync work in the hot path."
    )
