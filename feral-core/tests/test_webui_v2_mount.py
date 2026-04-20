"""Conditional /v2 StaticFiles mount for feral-client-v2.

The mount must be optional so CI / install environments that haven't built
the v2 bundle keep working. These tests verify the guard is a real bool and
that when a v2 bundle is present the Brain serves it, without starting the
full Brain.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.no_auto_feral_home


def _reload_server_module():
    """Force-reload api.server so the module-level mount code re-runs."""
    if "api.server" in sys.modules:
        del sys.modules["api.server"]
    import api.server as server_module
    return importlib.reload(sys.modules["api.server"])


def test_v2_mount_guard_types():
    """The module-level guard must expose a bool + a Path, regardless of
    whether the bundle has been built in this checkout."""
    module = _reload_server_module()
    assert isinstance(module._webui_v2_ready, bool)
    assert isinstance(module._webui_v2_dir, Path)


def test_v2_index_served_when_bundle_is_present():
    """When ``feral-core/webui-v2/index.html`` exists on disk, hitting
    ``/v2/`` must return the v2 index (HTML containing ``FERAL`` + ``v2``).
    Skipped when the bundle hasn't been built yet — that path is exercised
    by ``test_brain_still_starts_without_v2_bundle``.
    """
    v2_dir = Path(__file__).parent.parent / "webui-v2"
    if not (v2_dir / "index.html").exists():
        pytest.skip("feral-core/webui-v2 has not been built in this tree")

    module = _reload_server_module()
    assert module._webui_v2_ready is True, "v2 bundle exists but guard is False"

    client = TestClient(module.app, raise_server_exceptions=False)
    r = client.get("/v2/")
    assert r.status_code == 200, r.text
    # The v2 index.html has <title>FERAL · v2</title>.
    assert "FERAL" in r.text
    assert "v2" in r.text.lower()


def test_brain_still_starts_without_v2_bundle(monkeypatch, tmp_path):
    """If webui-v2 is absent, the Brain imports and /health still works.
    Simulates a fresh clone where the v2 client hasn't been built yet."""
    module = _reload_server_module()
    monkeypatch.setattr(module, "_webui_v2_dir", tmp_path / "missing")
    monkeypatch.setattr(module, "_webui_v2_ready", False)

    client = TestClient(module.app, raise_server_exceptions=False)
    r = client.get("/health")
    assert r.status_code == 200
