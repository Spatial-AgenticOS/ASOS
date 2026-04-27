"""A7 — shutdown / lifecycle correctness tests.

Validates that:
  * ``BrainState`` has a central background-task registry that cancels
    every registered task on ``shutdown_background_tasks``.
  * ``ProactiveEngine.stop()`` is awaitable and cancels the running
    evaluation loop so no further LLM evaluations fire after stop.
  * ``SyncEngine.stop_discovery`` tears down zeroconf without blocking
    the event loop (blocking unregister/close must run in a worker
    thread, mirroring ``services/mdns.py``).
  * The shutdown ordering documented in
    ``.internal/audit-v2026.5.5/A7-lifecycle.md`` is honoured:
    background producers stop BEFORE the shared LLM client is closed.
"""

from __future__ import annotations

import asyncio
import time

import pytest


# ──────────────────────────────────────────────────────────────────────
# Central background-task registry
# ──────────────────────────────────────────────────────────────────────

def test_state_registers_and_cancels_background_tasks() -> None:
    from api.state import BrainState

    brain = BrainState.__new__(BrainState)
    brain._background_tasks = set()

    async def _go() -> int:
        async def _forever():
            while True:
                await asyncio.sleep(0.01)

        tasks = [asyncio.create_task(_forever()) for _ in range(3)]
        for t in tasks:
            brain.register_background_task(t)

        assert len(brain._background_tasks) == 3

        cancelled = await brain.shutdown_background_tasks(timeout=1.0)
        for t in tasks:
            assert t.cancelled() or t.done()
        return cancelled

    cancelled = asyncio.run(_go())
    assert cancelled == 3


def test_shutdown_background_tasks_is_idempotent() -> None:
    from api.state import BrainState

    brain = BrainState.__new__(BrainState)
    brain._background_tasks = set()

    async def _go() -> None:
        await brain.shutdown_background_tasks(timeout=0.5)
        await brain.shutdown_background_tasks(timeout=0.5)

    asyncio.run(_go())


# ──────────────────────────────────────────────────────────────────────
# ProactiveEngine stop cancels the loop task
# ──────────────────────────────────────────────────────────────────────

def test_proactive_engine_stop_cancels_task() -> None:
    from agents.proactive_engine import ProactiveEngine

    eval_count = {"n": 0}

    async def _go() -> None:
        engine = ProactiveEngine(check_interval_s=0.01)

        async def _fake_evaluate():
            eval_count["n"] += 1

        engine._evaluate = _fake_evaluate  # type: ignore[assignment]

        await engine.start()
        task = engine._task
        assert task is not None and not task.done()

        await asyncio.sleep(0.05)
        assert eval_count["n"] > 0

        await engine.stop()
        assert engine._task is None
        assert task.done() or task.cancelled()

        snapshot = eval_count["n"]
        await asyncio.sleep(0.05)
        assert eval_count["n"] == snapshot, (
            "Proactive._evaluate fired after stop() — stop() must cancel the loop"
        )

    asyncio.run(_go())


# ──────────────────────────────────────────────────────────────────────
# SyncEngine.stop_discovery does not block the event loop
# ──────────────────────────────────────────────────────────────────────

def test_sync_engine_stop_discovery_non_blocking(tmp_path) -> None:
    from memory.sync import SyncEngine

    class _BlockingZeroconf:
        BLOCK_MS = 400

        def __init__(self) -> None:
            self.unregistered = False
            self.closed = False

        def unregister_service(self, info) -> None:
            time.sleep(self.BLOCK_MS / 1000.0)
            self.unregistered = True

        def close(self) -> None:
            time.sleep(self.BLOCK_MS / 1000.0)
            self.closed = True

    engine = SyncEngine(
        node_id="test-a7",
        memory_store=None,
        db_path=str(tmp_path / "sync_wal.db"),
    )
    zc = _BlockingZeroconf()
    engine._zeroconf = zc
    engine._service_info = object()

    async def _heartbeat_watcher(stop: asyncio.Event) -> float:
        loop = asyncio.get_running_loop()
        last = loop.time()
        worst = 0.0
        while not stop.is_set():
            await asyncio.sleep(0.010)
            now = loop.time()
            gap = now - last
            if gap > worst:
                worst = gap
            last = now
        return worst

    async def _run() -> float:
        stop = asyncio.Event()
        watcher = asyncio.create_task(_heartbeat_watcher(stop))
        await engine.stop_discovery()
        stop.set()
        return await watcher

    worst = asyncio.run(_run())
    assert zc.unregistered is True
    assert zc.closed is True
    assert worst < 0.500, (
        f"SyncEngine.stop_discovery stalled the event loop for {worst*1000:.0f}ms; "
        f"must offload blocking zeroconf calls to a worker thread"
    )
    assert engine._zeroconf is None
    assert engine._service_info is None
    assert engine._running is False


def test_sync_engine_stop_discovery_when_never_started(tmp_path) -> None:
    from memory.sync import SyncEngine

    engine = SyncEngine(
        node_id="test-a7-noop",
        memory_store=None,
        db_path=str(tmp_path / "sync_wal.db"),
    )
    assert engine._zeroconf is None

    async def _run() -> None:
        await engine.stop_discovery()

    asyncio.run(_run())
    assert engine._running is False


# ──────────────────────────────────────────────────────────────────────
# Shutdown ordering — producers stop BEFORE llm.close()
# ──────────────────────────────────────────────────────────────────────

def test_shutdown_event_stops_producers_before_closing_llm(monkeypatch) -> None:
    """Drive the FastAPI shutdown event handler against a fake state and
    assert the ordering contract: background tasks are cancelled and
    proactive/screen_loop/channel integrations are stopped BEFORE the
    shared LLM client is closed.
    """
    import api.server as server
    from api.state import BrainState

    order: list[str] = []

    class _Stoppable:
        def __init__(self, name: str, *, async_stop: bool = True):
            self._name = name
            self._async_stop = async_stop

        async def _astop(self):
            order.append(f"{self._name}.stop")

        def _sstop(self):
            order.append(f"{self._name}.stop")

        @property
        def stop(self):
            return self._astop if self._async_stop else self._sstop

    class _LLM:
        async def close(self):
            order.append("llm.close")

    class _Orchestrator:
        def __init__(self):
            self.llm = _LLM()

    class _MCP:
        async def disconnect_all(self):
            order.append("mcp.disconnect")

    class _Taskflows:
        async def stop(self):
            order.append("taskflows.stop")

    class _SyncEngine:
        async def stop_discovery(self):
            order.append("sync.stop")

    class _Memory:
        def close(self):
            order.append("memory.close")

    class _ChannelManager:
        async def stop_all(self):
            order.append("channel_manager.stop")

    fake = BrainState.__new__(BrainState)
    fake._background_tasks = set()

    async def _long_task():
        try:
            while True:
                await asyncio.sleep(0.01)
                order.append("bg.tick")
        except asyncio.CancelledError:
            order.append("bg.cancelled")
            raise

    async def _run() -> None:
        fake.register_background_task(asyncio.create_task(_long_task(), name="a7-test-bg"))
        await asyncio.sleep(0.02)

        fake.orchestrator = _Orchestrator()
        fake.mcp_client = _MCP()
        fake.sync_engine = _SyncEngine()
        fake.taskflows = _Taskflows()
        fake.memory = _Memory()
        fake.channel_manager = _ChannelManager()
        fake.proactive = _Stoppable("proactive", async_stop=True)
        fake.screen_loop = _Stoppable("screen_loop", async_stop=True)
        fake.mqtt_bridge = _Stoppable("mqtt_bridge", async_stop=True)
        fake.email_watcher = _Stoppable("email_watcher", async_stop=True)
        fake.consciousness = None

        monkeypatch.setattr(server, "state", fake)
        monkeypatch.setattr(
            server, "stop_advertisement", lambda: order.append("mdns.stop_adv"),
            raising=False,
        )

        await server.shutdown_event()

    asyncio.run(_run())

    assert "bg.cancelled" in order, "Registered bg task was not cancelled on shutdown"
    assert "llm.close" in order, "llm.close was never invoked"
    llm_idx = order.index("llm.close")

    for producer in (
        "bg.cancelled",
        "proactive.stop",
        "screen_loop.stop",
        "channel_manager.stop",
        "mqtt_bridge.stop",
        "email_watcher.stop",
        "memory.close",
    ):
        assert producer in order, f"expected {producer} in shutdown order, got {order}"
        assert order.index(producer) < llm_idx, (
            f"{producer} must run BEFORE llm.close; order was {order}"
        )

    assert "sync.stop" in order
    assert order.index("sync.stop") > llm_idx, "sync.stop should follow llm.close in A7 ordering"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
