"""
Unit tests for THEORA browser automation (`skills.impl.browser_use`).

Covers CDP defaults, controller state, ARIA text building, image compression,
selector resolution, and the browser skill manifest.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from skills.impl.browser_use import (
    CDPConnection,
    CDP_PORT,
    BrowserController,
    get_browser_skill_manifest,
)


class TestCDPConnection:
    """Tests for `CDPConnection` construction."""

    def test_init_sets_default_port(self) -> None:
        """Default constructor uses the module-level CDP port constant."""
        conn = CDPConnection()
        assert conn._port == CDP_PORT
        assert conn._connected is False


class TestBrowserController:
    """Tests for `BrowserController` lifecycle and helpers."""

    def test_init_creates_instance_not_connected(self) -> None:
        """Fresh controller has a CDP handle and is not connected."""
        ctrl = BrowserController()
        assert ctrl._cdp is not None
        assert ctrl._playwright is None

    def test_connected_false_initially(self) -> None:
        """`connected` reflects CDP state before `initialize`."""
        ctrl = BrowserController()
        assert ctrl.connected is False

    def test_build_aria_text_with_mock_nodes(self) -> None:
        """AX nodes produce labeled lines with refs and stored metadata."""
        ctrl = BrowserController()
        nodes = [
            {
                "role": {"value": "button"},
                "name": {"value": "Submit"},
                "depth": 0,
                "backendDOMNodeId": 42,
                "nodeId": 7,
                "properties": [{"name": "disabled", "value": {"value": "true"}}],
            },
            {
                "role": {"value": "link"},
                "name": {"value": "Home"},
                "depth": 1,
                "backendDOMNodeId": 43,
            },
        ]
        text = ctrl._build_aria_text(nodes)
        assert "[ax0]" in text
        assert "button" in text
        assert "Submit" in text
        assert "(disabled=true)" in text
        assert "[ax1]" in text
        assert "link" in text
        assert "ax0" in ctrl._aria_refs
        assert ctrl._aria_refs["ax0"]["backend_id"] == 42

    def test_compress_image_returns_base64_mock_pil(self) -> None:
        """JPEG pipeline returns a base64 string when PIL is mocked."""
        ctrl = BrowserController()
        mock_img = MagicMock()
        mock_img.width = 800
        mock_img.height = 600

        def _save(buf, **kwargs):
            buf.write(b"encoded")

        mock_img.resize = MagicMock(return_value=mock_img)
        mock_img.save = MagicMock(side_effect=_save)

        with patch("PIL.Image.open", return_value=mock_img):
            out = ctrl._compress_image(b"fakejpegbytes")
        assert isinstance(out, str)
        assert out == base64.b64encode(b"encoded").decode()

    def test_resolve_selector_ax_ref_and_css(self) -> None:
        """ARIA refs map to stored selectors; plain CSS passes through."""
        ctrl = BrowserController()
        ctrl._aria_refs["ax0"] = {"selector": "#primary-btn"}
        assert ctrl._resolve_selector("ax0") == "#primary-btn"
        assert ctrl._resolve_selector(".sidebar a") == ".sidebar a"


class TestBrowserSkillManifest:
    """Tests for the exported manifest helper."""

    def test_get_browser_skill_manifest_shape(self) -> None:
        """Manifest exposes stable identifiers and endpoint metadata."""
        m = get_browser_skill_manifest()
        assert isinstance(m, dict)
        assert m.get("skill_id") == "browser"
        assert "name" in m and m["name"]
        assert "description" in m
        assert m.get("safety_level") == "WARN"
        assert isinstance(m.get("endpoints"), list)
        endpoint_ids = {e["id"] for e in m["endpoints"]}
        assert {"navigate", "screenshot", "snapshot", "click"}.issubset(endpoint_ids)
