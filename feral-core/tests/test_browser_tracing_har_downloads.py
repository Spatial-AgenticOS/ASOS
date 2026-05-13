"""PR 7 gap-fill (browser): tracing / HAR / download primitives on
BrowserController.

We can't realistically spin up Playwright in CI — but we can pin:

* Methods exist and have stable signatures.
* When Playwright isn't connected, the API returns a *truthful* error
  string with a remediation hint (instead of pretending success).
* The brain's manifest alias map exposes the new endpoint ids.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_controller_exposes_tracing_har_download_methods():
    from skills.impl.browser_use import BrowserController

    bc = BrowserController()
    for name in ("start_tracing", "stop_tracing", "start_har", "stop_har", "wait_for_download"):
        assert callable(getattr(bc, name, None)), f"BrowserController missing {name}"


def test_methods_report_truthfully_when_playwright_not_connected():
    from skills.impl.browser_use import BrowserController

    bc = BrowserController()
    # No Playwright initialise() ran, so _page / _browser are None.
    out = _run(bc.start_tracing())
    assert out["success"] is False
    assert "Playwright" in out["error"]

    out = _run(bc.start_har())
    assert out["success"] is False
    assert "Playwright" in out["error"]

    out = _run(bc.wait_for_download(timeout_ms=50))
    assert out["success"] is False
    assert "Playwright" in out["error"]


def test_stop_tracing_without_start_returns_error():
    from skills.impl.browser_use import BrowserController

    bc = BrowserController()
    out = _run(bc.stop_tracing())
    assert out["success"] is False
    assert "No active tracing" in out["error"]


def test_brain_alias_map_advertises_new_endpoints():
    """The agent surface must expose the new ids so model + manifests
    can call them. The alias map is a class attribute on BrainState,
    we read it from source to avoid spinning up the brain."""
    from api import state as state_mod

    src = inspect.getsource(state_mod)
    for alias in ("trace_start", "trace_stop", "har_start", "har_stop", "download_next"):
        assert f'"{alias}"' in src, (
            f"Alias '{alias}' missing from BrainState._BROWSER_ENDPOINT_ALIASES — "
            "browser tracing/HAR/download surface not wired."
        )


def test_artifacts_directory_is_namespaced_under_feral_home():
    """Tracing/HAR/download artefacts must live under
    ~/.feral/browser/artifacts so the user has a single place to look."""
    from skills.impl.browser_use import BrowserController

    bc = BrowserController()
    p = bc._artifacts_root
    assert str(p).endswith("/.feral/browser/artifacts")
    assert p.exists() and p.is_dir()
