"""Test conftest: make ``feral_node_sdk`` importable without installation."""

from __future__ import annotations

import sys
from pathlib import Path

_SDK_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))
