"""REPL + brain-lifecycle regression tests.

Guards against the v2026.4.31 incident: ``feral start`` ran the brain
in a daemon thread, the REPL crashed because of a ``websockets>=11``
API change (``async with await connect(...)`` is invalid on modern
websockets), the REPL called ``sys.exit(1)``, Python interpreter
teardown began, and the daemon thread holding the brain was killed
mid-flight. The user perceived "clicking a button kills the system".

The tests in this module pin three contracts:

  1. ``cli.main.repl`` uses the ``async with websockets.connect(uri)``
     form — the only one that works on websockets 11/12/13/14.
  2. When ``websockets.connect`` raises an unexpected error (e.g. an
     API mismatch), ``repl`` prints a friendly message and ``return``s.
     It MUST NOT raise ``SystemExit``; doing so would kill any
     colocated brain thread.
  3. ``cli.main.cmd_start`` runs the brain in a NON-daemon thread and,
     when the REPL returns, sets ``server.should_exit`` + joins
     instead of relying on interpreter teardown.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from cli import main as cli_main


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeWS:
    """Minimal WebSocketClientProtocol stand-in.

    ``recv`` yields a scripted queue of frames; once the queue is empty,
    further ``recv`` calls block forever. ``send`` is recorded.
    """

    def __init__(self, frames=None):
        self._frames = list(frames or [])
        self.sent = []
        self.closed = False

    async def recv(self):
        if self._frames:
            return self._frames.pop(0)
        # Block "forever" — the test harness drives termination via
        # /quit on the input prompt or by raising on the executor.
        await asyncio.sleep(60)
        raise AssertionError("ws.recv() unblocked unexpectedly")

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


def _v13_connect_factory(ws: _FakeWS):
    """Returns a ``connect`` callable that mimics websockets >= 11.

    The callable returns a ``Connect`` object that IS itself the async
    context manager. ``async with connect(uri) as ws`` works. Awaiting
    the call would yield the inner ws (kept for completeness, not
    relied on by the REPL fix).
    """

    class _V13Connect:
        def __init__(self, *_a, **_kw):
            self._ws = ws

        async def __aenter__(self):
            return self._ws

        async def __aexit__(self, exc_type, exc, tb):
            await self._ws.close()
            return False

        def __await__(self):
            async def _coro():
                return self._ws
            return _coro().__await__()

    def _connect(*args, **kwargs):
        return _V13Connect(*args, **kwargs)

    return _connect


def _broken_connect_factory():
    """Returns a ``connect`` callable that mimics the historical bug.

    It returns a bare object that is NOT an async context manager.
    ``async with connect(uri) as ws:`` raises ``TypeError`` — exactly
    the failure mode that nuked the brain in v2026.4.31.
    """

    def _connect(*_args, **_kwargs):
        return SimpleNamespace()

    return _connect


# ---------------------------------------------------------------------------
# repl() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repl_uses_v13_connect_pattern_and_quits_cleanly(monkeypatch):
    """The REPL connects via ``async with websockets.connect(...)``,
    receives a greeting, processes ``/quit``, and returns ``None``
    without ``SystemExit``."""
    greeting = json.dumps({"type": "hello", "payload": {"text": "hi"}})
    fake_ws = _FakeWS(frames=[greeting])

    fake_ws_mod = SimpleNamespace(connect=_v13_connect_factory(fake_ws))
    monkeypatch.setattr(cli_main, "websockets", fake_ws_mod)

    inputs = iter(["/quit"])

    def fake_input(_prompt):
        return next(inputs)

    monkeypatch.setattr("builtins.input", fake_input)

    result = await cli_main.repl()
    assert result is None
    assert fake_ws.sent == [], "no user text was sent — only /quit"


@pytest.mark.asyncio
async def test_repl_routes_text_through_websocket(monkeypatch):
    """A typed message is sent over ``ws.send`` and the streamed
    response is consumed."""
    greeting = json.dumps({"type": "hello", "payload": {"text": "ready"}})
    delta = json.dumps({"type": "stream_delta", "payload": {"delta": "ok "}})
    end = json.dumps({"type": "stream_end", "payload": {}})
    fake_ws = _FakeWS(frames=[greeting, delta, end])

    fake_ws_mod = SimpleNamespace(connect=_v13_connect_factory(fake_ws))
    monkeypatch.setattr(cli_main, "websockets", fake_ws_mod)

    inputs = iter(["hello brain", "/quit"])

    def fake_input(_prompt):
        return next(inputs)

    monkeypatch.setattr("builtins.input", fake_input)

    await cli_main.repl()

    assert len(fake_ws.sent) == 1
    payload = json.loads(fake_ws.sent[0])
    assert payload["type"] == "text_command"
    assert payload["payload"]["text"] == "hello brain"


# ---------------------------------------------------------------------------
# repl() — broken-protocol path (the v2026.4.31 regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repl_does_not_systemexit_when_connect_returns_non_context_manager(monkeypatch):
    """The historical bug: ``await connect()`` returned a bare protocol
    object, then ``async with _ws as ws:`` raised ``TypeError``, and
    the old REPL caught it with ``sys.exit(1)`` — taking the brain
    thread down. The new REPL must catch the error, print a friendly
    message, and ``return``."""
    fake_ws_mod = SimpleNamespace(connect=_broken_connect_factory())
    monkeypatch.setattr(cli_main, "websockets", fake_ws_mod)

    inputs = iter(["/quit"])

    def fake_input(_prompt):
        return next(inputs)

    monkeypatch.setattr("builtins.input", fake_input)

    try:
        result = await cli_main.repl()
    except SystemExit as exc:
        pytest.fail(
            f"repl() raised SystemExit({exc.code}) — that would kill any "
            f"colocated brain thread. It must return cleanly instead."
        )
    assert result is None


@pytest.mark.asyncio
async def test_repl_does_not_systemexit_when_brain_unreachable(monkeypatch):
    """``ConnectionRefusedError`` used to call ``sys.exit(1)``. It must
    now back off and the user can break with Ctrl+C (here simulated by
    making sleep raise ``KeyboardInterrupt``)."""

    def _connect(*_a, **_kw):
        raise ConnectionRefusedError("simulated: brain down")

    fake_ws_mod = SimpleNamespace(connect=_connect)
    monkeypatch.setattr(cli_main, "websockets", fake_ws_mod)

    # First sleep call -> raise KeyboardInterrupt to break the retry
    # loop. We assert repl returns cleanly.
    real_sleep = asyncio.sleep
    sleep_calls = {"n": 0}

    async def fake_sleep(seconds):
        sleep_calls["n"] += 1
        if sleep_calls["n"] == 1:
            raise KeyboardInterrupt()
        await real_sleep(0)

    monkeypatch.setattr(cli_main.asyncio, "sleep", fake_sleep)

    try:
        await cli_main.repl()
    except SystemExit as exc:
        pytest.fail(f"repl() raised SystemExit({exc.code}) on connection refused — must return cleanly.")
    assert sleep_calls["n"] >= 1, "expected the retry-with-backoff path"


# ---------------------------------------------------------------------------
# cmd_start() — brain lifecycle
# ---------------------------------------------------------------------------


def _install_uvicorn_stub(monkeypatch, port_running_event: threading.Event,
                          server_holder: dict):
    """Replace ``uvicorn`` in ``sys.modules`` with a stub whose
    ``Server.run`` blocks on ``should_exit`` so the test can drive
    the brain's lifecycle deterministically."""

    class _StubServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            self.started = threading.Event()

        def run(self):
            self.started.set()
            port_running_event.set()
            while not self.should_exit:
                time.sleep(0.01)

    class _StubConfig:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    stub = SimpleNamespace(Config=_StubConfig, Server=_StubServer)
    monkeypatch.setitem(sys.modules, "uvicorn", stub)
    return _StubServer


def _install_cmd_start_mocks(monkeypatch, port: int):
    """Common monkeypatching for cmd_start lifecycle tests."""
    state = {"phase": "preflight"}

    class _OkResp:
        status_code = 200

        def json(self):
            return {"skills_count": 0, "llm_available": True, "memory": {"notes": 0}}

    def staged_get(url, **kwargs):
        if state["phase"] == "preflight":
            state["phase"] = "boot"
            raise ConnectionRefusedError()
        return _OkResp()

    monkeypatch.setattr(cli_main.httpx, "get", staged_get)
    monkeypatch.setattr(cli_main, "_http_get", lambda _path: {
        "skills_count": 0,
        "llm_available": True,
        "memory": {"notes": 0},
    })
    monkeypatch.setattr(cli_main, "_open_browser", lambda _p: None)
    monkeypatch.setattr(cli_main, "_is_first_run", lambda: False)
    monkeypatch.setattr(cli_main, "brain_tls_enabled", lambda: False)
    monkeypatch.setattr(cli_main, "brain_port", lambda: port)
    monkeypatch.setattr(cli_main, "brain_bind_host", lambda: "127.0.0.1")


def test_cmd_start_brain_shuts_down_cleanly_on_keyboard_interrupt(monkeypatch):
    """Ctrl+C path: REPL raises ``KeyboardInterrupt`` → ``cmd_start``
    sets ``server.should_exit`` and joins the brain thread. The
    historical bug had this path on ``sys.exit(1)`` instead, which
    killed the daemon brain mid-flight. We pin both:

      1. ``cmd_start`` returns within the timeout (no hang).
      2. The brain thread terminated cleanly via ``should_exit``.
    """
    port_running = threading.Event()
    captured_servers: list = []
    StubServerCls = _install_uvicorn_stub(monkeypatch, port_running, {})

    # Track every server instance so we can assert ``should_exit`` was
    # flipped on the active one.
    real_init = StubServerCls.__init__

    def init_spy(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        captured_servers.append(self)

    monkeypatch.setattr(StubServerCls, "__init__", init_spy)

    _install_cmd_start_mocks(monkeypatch, port=51777)

    repl_called = {"n": 0}

    async def repl_ctrl_c():
        repl_called["n"] += 1
        # Give the brain thread time to be running before we trigger
        # shutdown — otherwise we race the test.
        await asyncio.sleep(0.05)
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli_main, "repl", repl_ctrl_c)

    done = threading.Event()
    err: dict = {"exc": None}

    def run_cmd():
        try:
            cli_main.cmd_start(port=51777, no_browser=True)
        except SystemExit:
            pass
        except Exception as exc:
            err["exc"] = exc
        finally:
            done.set()

    t = threading.Thread(target=run_cmd, daemon=True)
    t.start()

    done.wait(timeout=20)
    assert done.is_set(), (
        "cmd_start hung after KeyboardInterrupt — Ctrl+C must trigger "
        "should_exit + join(). REGRESSION: the brain thread never gets "
        "the shutdown signal."
    )
    assert err["exc"] is None, f"cmd_start raised: {err['exc']!r}"
    assert repl_called["n"] == 1, "repl() was not invoked"
    assert captured_servers, "uvicorn.Server was never instantiated"
    # The active server must have had should_exit flipped.
    assert captured_servers[0].should_exit, (
        "REGRESSION: brain server.should_exit was never set during "
        "Ctrl+C teardown — the brain stays running orphaned."
    )


def test_cmd_start_keeps_brain_alive_when_repl_returns_cleanly(monkeypatch):
    """REPL returns ``None`` (clean ``/quit``) → ``cmd_start`` prints
    "Brain still running" and waits for Ctrl+C. We simulate the user's
    Ctrl+C from a second thread by directly setting the brain's
    ``should_exit`` after observing the join loop.

    The historical bug never reached this branch — ``sys.exit`` skipped
    straight to interpreter teardown. We now MUST get here first; if a
    future change re-introduces ``sys.exit`` from ``repl``, this test
    will time out.
    """
    port_running = threading.Event()
    captured_servers: list = []
    StubServerCls = _install_uvicorn_stub(monkeypatch, port_running, {})

    real_init = StubServerCls.__init__

    def init_spy(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        captured_servers.append(self)

    monkeypatch.setattr(StubServerCls, "__init__", init_spy)

    _install_cmd_start_mocks(monkeypatch, port=51779)

    async def repl_quit():
        await asyncio.sleep(0.05)
        return None  # Clean /quit

    monkeypatch.setattr(cli_main, "repl", repl_quit)

    done = threading.Event()

    def run_cmd():
        try:
            cli_main.cmd_start(port=51779, no_browser=True)
        finally:
            done.set()

    t = threading.Thread(target=run_cmd, daemon=True)
    t.start()

    # Wait for the brain to be running, then for cmd_start to enter the
    # "wait for Ctrl+C" join loop. Once we see the server is alive and
    # should_exit is False, simulate the user's Ctrl+C by flipping
    # should_exit ourselves (the real mechanism is the SIGINT handler
    # in the main thread, which we can't trigger from a worker thread).
    deadline = time.time() + 10
    while time.time() < deadline and not captured_servers:
        time.sleep(0.05)
    assert captured_servers, "brain never started"
    server = captured_servers[0]
    # Wait for repl to have returned (server still running, joined).
    time.sleep(0.5)
    assert not done.is_set(), (
        "cmd_start exited prematurely — the brain did NOT outlive the "
        "REPL. REGRESSION: clean /quit shut down the brain."
    )
    assert server.started.is_set(), "server.run() never started"
    # Now simulate Ctrl+C by signalling the stub server to exit.
    server.should_exit = True
    done.wait(timeout=15)
    assert done.is_set(), "cmd_start hung after should_exit was set"


def test_cmd_start_brain_thread_is_not_daemon(monkeypatch):
    """Sanity check: any future refactor that re-introduces
    ``daemon=True`` on the brain thread will break this assertion.
    The whole bug class returns the moment the brain becomes a daemon
    thread again."""
    captured: dict = {"thread": None}

    real_thread_init = threading.Thread.__init__

    def init_spy(self, *args, **kwargs):
        real_thread_init(self, *args, **kwargs)
        if kwargs.get("name") == "feral-brain":
            captured["thread"] = self

    monkeypatch.setattr(threading.Thread, "__init__", init_spy)

    port_running = threading.Event()
    captured_servers: list = []
    StubServerCls = _install_uvicorn_stub(monkeypatch, port_running, {})
    real_init = StubServerCls.__init__

    def server_init_spy(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        captured_servers.append(self)

    monkeypatch.setattr(StubServerCls, "__init__", server_init_spy)

    _install_cmd_start_mocks(monkeypatch, port=51778)

    # Ctrl+C path so cmd_start exits without waiting for external
    # signalling.
    async def repl_ctrl_c():
        await asyncio.sleep(0.05)
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli_main, "repl", repl_ctrl_c)

    done = threading.Event()

    def run_cmd():
        try:
            cli_main.cmd_start(port=51778, no_browser=True)
        finally:
            done.set()

    t = threading.Thread(target=run_cmd, daemon=True)
    t.start()
    done.wait(timeout=20)
    assert done.is_set(), "cmd_start hung — likely a regression"

    brain_thread = captured["thread"]
    assert brain_thread is not None, "brain thread was never spawned"
    assert brain_thread.daemon is False, (
        "REGRESSION: brain thread is daemon=True — Python interpreter "
        "teardown will kill it the moment SystemExit is raised in any "
        "sibling code path. Set daemon=False in cmd_start::_run_server."
    )


# ---------------------------------------------------------------------------
# canary
# ---------------------------------------------------------------------------


def test_websockets_connect_supports_async_context_manager_protocol():
    """Tiny canary: if someone downgrades ``websockets`` below the
    version where ``connect()`` returns a Connect-shaped object, this
    fires before any user-facing code does."""
    import websockets

    # websockets >= 13 is the floor we ship in pyproject.toml.
    version = getattr(websockets, "__version__", "0.0.0")
    parts = version.split(".")
    try:
        major = int(parts[0])
    except (ValueError, IndexError):
        pytest.fail(f"unparseable websockets version: {version!r}")
    assert major >= 13, (
        f"websockets {version} is below the supported floor (>=13). "
        f"Update pyproject.toml or pin a compatible version."
    )

    # The actual Connect object returned by ``connect()`` must expose
    # ``__aenter__`` so ``async with websockets.connect(uri) as ws:``
    # works. We don't attempt the connect (no live server) — we just
    # verify the attribute on the unbound result.
    cm = websockets.connect("ws://127.0.0.1:1/never-resolved")
    try:
        assert hasattr(cm, "__aenter__"), (
            "websockets.connect() returned an object without __aenter__. "
            "Modern code does `async with websockets.connect(uri) as ws:` — "
            "if this attribute disappears, the REPL + Slack channel will "
            "raise TypeError on every connect."
        )
        assert hasattr(cm, "__aexit__")
    finally:
        # The Connect object owns a coroutine we never awaited; close
        # it to silence asyncio warnings.
        try:
            cm.__await__().close()  # type: ignore[attr-defined]
        except Exception:
            pass
