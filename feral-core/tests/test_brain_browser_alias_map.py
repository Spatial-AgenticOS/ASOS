"""PR 11 wiring pin: BrainState._BROWSER_ENDPOINT_ALIASES exposes the
PR 3 controller methods (tracing / HAR / downloads) under stable agent-
visible ids so the model + manifests can call them.

This test is intentionally hosted in PR 11 (not PR 3) because the alias
map lives in api/state.py whose changes ship with the integration /
MCP wiring that PR 11 introduces. PR 3 keeps the controller methods +
truthful-error tests; PR 11 owns the wiring + this contract.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_brain_alias_map_advertises_browser_artifact_endpoints():
    from api import state as state_mod

    src = inspect.getsource(state_mod)
    for alias in ("trace_start", "trace_stop", "har_start", "har_stop", "download_next"):
        assert f'"{alias}"' in src, (
            f"Alias '{alias}' missing from BrainState._BROWSER_ENDPOINT_ALIASES — "
            "browser tracing/HAR/download surface not wired."
        )
