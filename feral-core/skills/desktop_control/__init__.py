"""Phase 11 (audit-r10 overhaul) — brain-on-Mac desktop control.

The brain runs on the operator's Mac. Phase 11 gives the orchestrator
a first-class way to actually drive that Mac: AppleScript invocation
gated by macOS Automation permissions, plus high-level facades for
the operations the operator's complaint #8 named explicitly
("call my friend on my Mac and use FaceTime").

Module layout::

    desktop_control/
        __init__.py    — public surface + manifest builder
        applescript.py — osascript runner with TCC error detection
        facade.py      — facetime_call / music_play / message_send /
                         app_activate / app_launch / open_url / notify

These map 1:1 to brain-host capability manifest actions
(`desktop.*`) registered in `BrainState.init` with the Phase 5
capability registry — so the iOS Brain Network section, the
`/api/capabilities` REST surface, and the orchestrator's
capability-aware routing all see them alongside iPhone skills.
"""
from __future__ import annotations

from .applescript import (
    AppleScriptResult,
    AppleScriptUnsupportedPlatform,
    run_applescript,
)
from .facade import (
    BRAIN_HOST_MANIFESTS,
    dispatch_desktop_action,
)

__all__ = [
    "AppleScriptResult",
    "AppleScriptUnsupportedPlatform",
    "BRAIN_HOST_MANIFESTS",
    "dispatch_desktop_action",
    "run_applescript",
]
