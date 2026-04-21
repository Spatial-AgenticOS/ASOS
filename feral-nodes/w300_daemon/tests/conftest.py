"""Make w300_daemon + feral_node_sdk importable without install."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[3]  # ASOS/

for rel in (
    _ROOT / "feral-nodes" / "python-node-sdk" / "src",
    _ROOT / "feral-nodes" / "w300_daemon" / "src",
):
    rel_s = str(rel)
    if rel_s not in sys.path:
        sys.path.insert(0, rel_s)
