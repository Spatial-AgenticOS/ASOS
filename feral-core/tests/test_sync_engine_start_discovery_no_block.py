"""Audit-r9 H1 / brief #08 regression test.

Pre-fix, `SyncEngine.start_discovery` ran synchronous `Zeroconf()` +
`register_service()` + `ServiceBrowser(...)` directly on the asyncio
loop. Even on a clean LAN those calls blocked long enough for
python-zeroconf to raise `EventLoopBlocked`, which surfaced as
`mDNS discovery skipped: EventLoopBlocked()` on every brain boot.

This test pins the contract: while `start_discovery()` is in flight,
the asyncio loop must keep ticking — no >500 ms gaps. We mirror the
`test_mdns_no_event_loop_blocked.py` pattern: monkeypatch zeroconf
with a stub whose sync registration sleeps 400 ms (enough to block a
non-fixed implementation), then assert a heartbeat watcher never
sees a gap >=500 ms.
"""

from __future__ import annotations

import asyncio
import sys
import time
import types

import pytest


class _FakeServiceInfo:
    def __init__(self, *a, **kw):
        self.type = a[0] if a else kw.get("type_")
        self.name = a[1] if len(a) > 1 else kw.get("name")
        self.addresses = list(kw.get("addresses", []))
        self.port = kw.get("port", 0)
        self.properties = kw.get("properties", {})


class _FakeZeroconf:
    BLOCK_MS = 400

    def __init__(self, *a, **kw) -> None:
        self._registered: list = []
        # Simulate a real zeroconf init that does some sync work.
        time.sleep(self.BLOCK_MS / 1000.0)

    def register_service(self, info) -> None:
        time.sleep(self.BLOCK_MS / 1000.0)
        self._registered.append(info)

    def unregister_service(self, info) -> None:
        if info in self._registered:
            self._registered.remove(info)

    def close(self) -> None:
        return None

    def get_service_info(self, type_, name, timeout=3000):
        return None


class _FakeServiceBrowser:
    def __init__(self, zc, type_, listener):
        self._zc = zc
        self._type = type_
        self._listener = listener


class _FakeAsyncZeroconf:
    BLOCK_MS = 400

    def __init__(self, *a, **kw) -> None:
        self._registered: list = []
        self.zeroconf = _FakeZeroconf.__new__(_FakeZeroconf)
        self.zeroconf._registered = []

    async def async_register_service(self, info) -> None:
        await asyncio.sleep(self.BLOCK_MS / 1000.0)
        self._registered.append(info)

    async def async_unregister_all_services(self) -> None:
        return None

    async def async_close(self) -> None:
        return None


class _FakeAsyncServiceBrowser:
    def __init__(self, zc, type_, handlers=None) -> None:
        self._zc = zc
        self._type = type_
        self._handlers = handlers

    async def async_cancel(self) -> None:
        return None


@pytest.fixture
def patched_zeroconf(monkeypatch: pytest.MonkeyPatch):
    fake_zc_mod = types.ModuleType("zeroconf")
    fake_zc_mod.Zeroconf = _FakeZeroconf
    fake_zc_mod.ServiceInfo = _FakeServiceInfo
    fake_zc_mod.ServiceBrowser = _FakeServiceBrowser
    fake_zc_mod.ServiceListener = object

    fake_async_mod = types.ModuleType("zeroconf.asyncio")
    fake_async_mod.AsyncZeroconf = _FakeAsyncZeroconf
    fake_async_mod.AsyncServiceInfo = _FakeServiceInfo
    fake_async_mod.AsyncServiceBrowser = _FakeAsyncServiceBrowser

    monkeypatch.setitem(sys.modules, "zeroconf", fake_zc_mod)
    monkeypatch.setitem(sys.modules, "zeroconf.asyncio", fake_async_mod)
    yield


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


def test_start_discovery_async_does_not_stall_loop(
    patched_zeroconf, tmp_path
) -> None:
    """Async path: AsyncZeroconf is available → no >500ms loop gap."""
    from memory.sync import SyncEngine

    async def _run() -> tuple[bool, float]:
        eng = SyncEngine(node_id="audit-r9-test", db_path=str(tmp_path / "wal.db"))
        stop = asyncio.Event()
        watcher = asyncio.create_task(_heartbeat_watcher(stop))
        await eng.start_discovery()
        running = eng._running  # snapshot BEFORE stop_discovery flips it
        stop.set()
        worst = await watcher
        await eng.stop_discovery()
        return running, worst

    running, worst_gap = asyncio.run(_run())
    assert running is True, "discovery did not enter running state"
    assert worst_gap < 0.500, (
        f"start_discovery() must not stall the loop by >=500ms; "
        f"worst gap was {worst_gap*1000:.0f}ms"
    )


def test_start_discovery_sync_fallback_does_not_stall_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Sync fallback: AsyncZeroconf import fails → still no >500ms gap.

    Pre-fix this path called `Zeroconf()` + `register_service` directly
    on the loop; the only safe behaviour is `loop.run_in_executor` so
    the worker thread takes the hit.
    """
    fake_zc_mod = types.ModuleType("zeroconf")
    fake_zc_mod.Zeroconf = _FakeZeroconf
    fake_zc_mod.ServiceInfo = _FakeServiceInfo
    fake_zc_mod.ServiceBrowser = _FakeServiceBrowser
    fake_zc_mod.ServiceListener = object
    monkeypatch.setitem(sys.modules, "zeroconf", fake_zc_mod)

    # Ensure the asyncio submodule import inside start_discovery raises.
    monkeypatch.setitem(sys.modules, "zeroconf.asyncio", None)

    from memory.sync import SyncEngine

    async def _run() -> tuple[bool, float]:
        eng = SyncEngine(node_id="audit-r9-sync", db_path=str(tmp_path / "wal.db"))
        stop = asyncio.Event()
        watcher = asyncio.create_task(_heartbeat_watcher(stop))
        await eng.start_discovery()
        running = eng._running
        stop.set()
        worst = await watcher
        await eng.stop_discovery()
        return running, worst

    running, worst_gap = asyncio.run(_run())
    assert running is True
    assert worst_gap < 0.500, (
        f"sync-fallback start_discovery() must offload to executor and "
        f"keep loop responsive; worst gap was {worst_gap*1000:.0f}ms"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
