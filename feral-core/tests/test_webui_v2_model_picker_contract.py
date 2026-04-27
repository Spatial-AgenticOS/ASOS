"""Guardrails for the bundled v2 provider model-picker contract.

Regression target: v2 source requested chat/recommended model filters
but stale bundled assets in ``feral-core/webui_v2`` shipped without
those query parameters, exposing legacy completion-only IDs.
"""

from __future__ import annotations

import re
from pathlib import Path


def test_v2_bundle_contains_chat_model_filter_tokens():
    root = Path(__file__).parent.parent / "webui_v2"
    index = root / "index.html"
    assert index.exists(), "webui_v2/index.html missing from repo bundle"

    html = index.read_text(encoding="utf-8")
    script_srcs = re.findall(r'<script[^>]+src="([^"]+\.js)"', html)
    assert script_srcs, "No JS bundle assets referenced by webui_v2/index.html"

    bundle_text = ""
    for src in script_srcs:
        rel = src[1:] if src.startswith("/") else src
        path = root / rel
        assert path.exists(), f"Missing webui_v2 bundle asset: {path}"
        bundle_text += path.read_text(encoding="utf-8", errors="ignore")

    assert "recommended=true" in bundle_text
    assert "model_class=chat" in bundle_text
