"""v2 (feral-client-v2) is the default UI.

When ``feral-core/webui_v2/index.html`` is present on disk the Brain must
serve that bundle at ``/`` and keep a ``/v2/`` alias working. Legacy
``feral-core/webui/`` stays in the tree for history but is never reached
as long as webui_v2/ is built.

These tests lock in the expected defaults so nobody accidentally
regresses to serving v1 at /.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.no_auto_feral_home


def _reload_server_module():
    if "api.server" in sys.modules:
        del sys.modules["api.server"]
    import api.server as module
    return importlib.reload(sys.modules["api.server"])


def test_default_webui_variant_prefers_v2_when_built():
    """_webui_dir must point at webui_v2/ when its index.html exists."""
    module = _reload_server_module()

    webui_v2_dir = Path(__file__).parent.parent / "webui_v2"
    if not (webui_v2_dir / "index.html").exists():
        pytest.skip("feral-core/webui_v2 has not been built in this tree")

    assert module._webui_v2_ready is True
    assert module._webui_dir == module._webui_v2_dir
    assert module._webui_variant == "v2"


def test_root_serves_v2_index_when_built():
    """GET / returns v2's index.html — content includes the v2 title + relative assets."""
    webui_v2_dir = Path(__file__).parent.parent / "webui_v2"
    if not (webui_v2_dir / "index.html").exists():
        pytest.skip("feral-core/webui_v2 has not been built in this tree")

    module = _reload_server_module()
    client = TestClient(module.app, raise_server_exceptions=False)

    r = client.get("/")
    assert r.status_code == 200
    assert "FERAL" in r.text
    # v2's vite config uses base: './' so assets are relative.
    assert "./assets/" in r.text or "assets/" in r.text
    # v2 ships with the v2 title — guards against accidentally serving v1.
    assert "v2" in r.text.lower()


def test_v2_alias_still_works_when_default():
    """/v2/ stays reachable even though / already serves v2."""
    webui_v2_dir = Path(__file__).parent.parent / "webui_v2"
    if not (webui_v2_dir / "index.html").exists():
        pytest.skip("feral-core/webui_v2 has not been built in this tree")

    module = _reload_server_module()
    client = TestClient(module.app, raise_server_exceptions=False)

    r = client.get("/v2/")
    assert r.status_code == 200
    assert "FERAL" in r.text


def test_brain_still_imports_without_webui_v2(monkeypatch, tmp_path):
    """If webui_v2/ is absent, the Brain still imports + falls back."""
    module = _reload_server_module()
    monkeypatch.setattr(module, "_webui_v2_dir", tmp_path / "missing-v2")
    monkeypatch.setattr(module, "_webui_v2_ready", False)

    client = TestClient(module.app, raise_server_exceptions=False)
    r = client.get("/health")
    assert r.status_code == 200
