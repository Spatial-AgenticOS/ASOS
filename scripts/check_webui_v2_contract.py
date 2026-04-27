#!/usr/bin/env python3
"""Guardrails for the bundled v2 web UI.

Fails when the checked-in `feral-core/webui_v2` bundle is missing the
provider-model filter contract expected by the backend:

  - recommended=true
  - model_class=chat

This catches stale bundle shipping where source code is updated but
`webui_v2` assets were not rebuilt/synced before release.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEBUI_V2 = ROOT / "feral-core" / "webui_v2"
INDEX = WEBUI_V2 / "index.html"


def _fail(message: str) -> int:
    print(f"ERROR: {message}")
    print("Hint: run `scripts/build_webui_v2.sh` and commit updated bundles.")
    return 1


def _script_assets(index_html: str) -> list[Path]:
    # Extract src="...js" values from index.html.
    srcs = re.findall(r'<script[^>]+src="([^"]+\.js)"', index_html)
    files: list[Path] = []
    for src in srcs:
        rel = src[1:] if src.startswith("/") else src
        path = WEBUI_V2 / rel
        if path.exists():
            files.append(path)
    return files


def main() -> int:
    if not INDEX.exists():
        return _fail(f"Missing bundled index: {INDEX}")

    index_html = INDEX.read_text(encoding="utf-8")
    scripts = _script_assets(index_html)
    if not scripts:
        return _fail("No JS bundle assets referenced by webui_v2/index.html")

    expected_tokens = ("recommended=true", "model_class=chat")
    found = {token: False for token in expected_tokens}

    for asset in scripts:
        text = asset.read_text(encoding="utf-8", errors="ignore")
        for token in expected_tokens:
            if token in text:
                found[token] = True

    missing = [token for token, present in found.items() if not present]
    if missing:
        missing_str = ", ".join(missing)
        return _fail(
            "Bundled v2 assets are missing model-picker contract token(s): "
            f"{missing_str}"
        )

    print("OK: webui_v2 bundle includes model-picker filter contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
