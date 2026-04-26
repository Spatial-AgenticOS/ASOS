"""W16 — cross-process OAuth refresh lock tests.

Two simulated agents (subprocesses sharing one ``$FERAL_HOME``) attempt
to refresh the same OAuth profile against a fake refresh server. We
assert:

* Exactly one HTTP refresh fires.
* The second waiter blocks on the file lock until the first releases it.
* Both processes wind up with the rotated access/refresh tokens written
  to the per-agent store.

The fake refresh server is a stdlib :mod:`http.server` running on
``127.0.0.1:<random>``; each ``POST /token`` increments a hit counter
and returns a fresh ``access`` + ``refresh`` pair so any double-refresh
is unambiguous in the assertions below.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

# Module-level marker: this file owns its own FERAL_HOME because the
# subprocesses must share it. The autouse isolate_feral_home fixture in
# conftest sets a per-test FERAL_HOME; we set it ourselves explicitly.
pytestmark = pytest.mark.no_auto_feral_home


class _RefreshHandler(BaseHTTPRequestHandler):
    server_hits: int = 0
    sleep_during_refresh: float = 0.0

    def log_message(self, format, *args):
        return

    def do_POST(self):  # noqa: N802 — http.server name
        type(self).server_hits += 1
        time.sleep(type(self).sleep_during_refresh)
        body = json.dumps({
            "access": f"access-{type(self).server_hits}",
            "refresh": f"refresh-{type(self).server_hits}",
            "expires": 9999999999000,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_refresh_server():
    _RefreshHandler.server_hits = 0
    _RefreshHandler.sleep_during_refresh = 0.5
    httpd = HTTPServer(("127.0.0.1", 0), _RefreshHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    thread.join(timeout=2.0)


@pytest.fixture
def shared_feral_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "shared-feral"
    home.mkdir()
    monkeypatch.setenv("FERAL_HOME", str(home))
    return home


def _agent_script(feral_core: Path) -> str:
    """Inline Python the subprocesses run.

    The script:
      1. seeds an OAuthCredential for ``test:agent`` if missing,
      2. acquires the W16 OAuth refresh lock,
      3. POSTs to the fake refresh server,
      4. writes the rotated credential back to the per-agent store,
      5. prints a JSON line so the parent can correlate.

    Run via ``python -c "<script>"`` so we exercise the real cross-process
    fcntl lock — not a same-process recursive acquisition. The helper
    quotes the feral-core path verbatim so test debugging stays simple.
    """
    return textwrap.dedent(f"""
        import json, sys, time, urllib.request

        sys.path.insert(0, {str(feral_core)!r})

        from security.auth_profiles import (
            AuthProfileFileStore,
            OAuthCredential,
            acquire_oauth_refresh_lock,
        )

        URL = sys.argv[1]
        AGENT = "default"
        PROVIDER = "test"
        PROFILE = "test:agent"

        store = AuthProfileFileStore(AGENT)
        if store.get(PROFILE) is None:
            store.upsert(PROFILE, OAuthCredential(
                provider=PROVIDER, access="seed-access",
                refresh="seed-refresh", expires=0,
            ))

        t0 = time.monotonic()
        with acquire_oauth_refresh_lock(PROVIDER, PROFILE, timeout=30.0):
            current = store.get(PROFILE)
            if current.access != "seed-access":
                # Another worker already rotated; we adopt without
                # firing our own HTTP refresh.
                print(json.dumps({{
                    "fired_refresh": False,
                    "access": current.access,
                    "refresh": current.refresh,
                    "wait_seconds": time.monotonic() - t0,
                }}))
                sys.exit(0)
            req = urllib.request.Request(URL, data=b"{{}}", method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rotated = OAuthCredential(
                provider=PROVIDER,
                access=payload["access"],
                refresh=payload["refresh"],
                expires=payload["expires"],
            )
            store.upsert(PROFILE, rotated)
            print(json.dumps({{
                "fired_refresh": True,
                "access": rotated.access,
                "refresh": rotated.refresh,
                "wait_seconds": time.monotonic() - t0,
            }}))
    """).strip()


def _spawn_agent(script: str, url: str, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", script, url],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait(proc: subprocess.Popen) -> dict:
    out, err = proc.communicate(timeout=60)
    if proc.returncode != 0:
        raise AssertionError(
            f"agent subprocess failed rc={proc.returncode}\n"
            f"stdout: {out.decode('utf-8', 'replace')}\n"
            f"stderr: {err.decode('utf-8', 'replace')}"
        )
    last_line = out.decode("utf-8").strip().splitlines()[-1]
    return json.loads(last_line)


def test_two_agents_share_one_refresh(fake_refresh_server, shared_feral_home, monkeypatch):
    """Two concurrent agents must produce exactly one HTTP refresh.

    The second agent blocks on the lock, observes that the credential
    was rotated, and adopts the new tokens without firing its own HTTP
    refresh — exactly the rule preventing ``refresh_token_reused``
    storms (see ``docs/OPENCLAW_LESSONS.md`` §1 for the comparative
    walk-through).
    """
    feral_core = Path(__file__).resolve().parents[1]
    script = _agent_script(feral_core)
    host, port = fake_refresh_server.server_address
    url = f"http://{host}:{port}/token"

    env = os.environ.copy()
    env["FERAL_HOME"] = str(shared_feral_home)
    env["PYTHONPATH"] = str(feral_core)

    a = _spawn_agent(script, url, env)
    time.sleep(0.05)  # give A a head start on lock acquisition
    b = _spawn_agent(script, url, env)

    result_a = _wait(a)
    result_b = _wait(b)

    fired = sum(int(r["fired_refresh"]) for r in (result_a, result_b))
    assert fired == 1, (
        f"expected exactly ONE HTTP refresh across both agents, got {fired}: "
        f"a={result_a} b={result_b}"
    )
    assert _RefreshHandler.server_hits == 1, (
        f"fake server hit count mismatch: {_RefreshHandler.server_hits}"
    )

    # Both winners + losers see the same rotated credential.
    assert result_a["access"] == result_b["access"] == "access-1"
    assert result_a["refresh"] == result_b["refresh"] == "refresh-1"

    # The waiter actually waited — it observed at least the
    # ``sleep_during_refresh`` window the holder spent inside the lock.
    waiter = result_a if not result_a["fired_refresh"] else result_b
    assert waiter["wait_seconds"] >= 0.4, waiter


def test_lock_path_hashes_with_nul_separator():
    """The lock filename must hash ``provider \\0 profile_id`` so two
    pairs that would collide under string concatenation hash distinctly.
    """
    from security.auth_profiles import resolve_oauth_refresh_lock_path

    a = resolve_oauth_refresh_lock_path("a", "b:c")
    b = resolve_oauth_refresh_lock_path("a:b", "c")
    assert a != b, "NUL separator must prevent the (a, b:c) ↔ (a:b, c) collision"

    # Same pair → same path (deterministic).
    a2 = resolve_oauth_refresh_lock_path("a", "b:c")
    assert a == a2

    assert a.name.startswith("sha256-")
    assert len(a.name) == len("sha256-") + 64


def test_lock_timeout_is_explicit(shared_feral_home):
    """A second acquirer that exceeds ``timeout`` raises
    :class:`OAuthRefreshLockTimeout` instead of hanging."""
    from security.auth_profiles import (
        OAuthRefreshLockTimeout,
        acquire_oauth_refresh_lock,
    )

    with acquire_oauth_refresh_lock("p", "id", timeout=5.0):
        with pytest.raises(OAuthRefreshLockTimeout):
            with acquire_oauth_refresh_lock("p", "id", timeout=0.2):
                pass
