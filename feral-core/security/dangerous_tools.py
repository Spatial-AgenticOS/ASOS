"""
FERAL Dangerous Tool Registry
Centralized policy for which tools are restricted on which surfaces.

Pattern: central deny lists per execution surface.

Usage
-----
1. Gate execution: call ``is_tool_allowed(name, surface)`` before dispatch; if False, refuse.
2. UX / policy: ``get_danger_level`` and ``requires_approval`` drive prompts and exec-approval
   flows (see ``security.exec_approvals``).
3. Extend ``TOOL_DANGER_MAP`` when new tools ship; keep names aligned with MCP / internal registry
   strings so policy stays a single source of truth.

Surfaces
--------
- ``http_api``: remote, minimally trusted — block shell, Docker, and arbitrary JS in browser.
- ``websocket``: interactive channel — still block host-level Docker exec.
- ``local_cli``: operator-controlled — no static denies (policy can still require approval).
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Iterable


class DangerLevel(str, Enum):
    """Relative risk of invoking a tool or endpoint."""

    SAFE = "safe"
    WARN = "warn"
    CRITICAL = "critical"


# Explicit map for known tools; anything not listed is treated as SAFE.
TOOL_DANGER_MAP: dict[str, DangerLevel] = {
    # CRITICAL — arbitrary code, container escape surface, or destructive FS
    "system.run": DangerLevel.CRITICAL,
    "browser.evaluate": DangerLevel.CRITICAL,
    "docker.exec": DangerLevel.CRITICAL,
    "fs.delete": DangerLevel.CRITICAL,
    "fs.remove": DangerLevel.CRITICAL,
    "filesystem.delete": DangerLevel.CRITICAL,
    "file.delete": DangerLevel.CRITICAL,
    "shell.exec": DangerLevel.CRITICAL,
    "process.spawn": DangerLevel.CRITICAL,
    # WARN — sensitive automation / network / generation
    "browser.navigate": DangerLevel.WARN,
    "browser.click": DangerLevel.WARN,
    "web_fetch": DangerLevel.WARN,
    "mcp.web_fetch": DangerLevel.WARN,
    "image.generate": DangerLevel.WARN,
    "images.generate": DangerLevel.WARN,
    "generate_image": DangerLevel.WARN,
}

# Per-surface deny: if a tool appears here, it must not run on that surface
# regardless of danger level handling elsewhere.
SURFACE_DENY_LISTS: dict[str, set[str]] = {
    "http_api": {
        "system.run",
        "docker.exec",
        "browser.evaluate",
    },
    "websocket": {
        "docker.exec",
    },
    "local_cli": set(),
}

# Frozen snapshots for introspection / tests (optional).
SURFACE_DENY_LISTS_FROZEN: dict[str, FrozenSet[str]] = {
    k: frozenset(v) for k, v in SURFACE_DENY_LISTS.items()
}


def known_surfaces() -> tuple[str, ...]:
    """Registered execution surfaces that may have deny lists."""
    return tuple(sorted(SURFACE_DENY_LISTS.keys()))


def denied_tools_for_surface(surface: str) -> FrozenSet[str]:
    """Return the deny set for ``surface``, or empty if unknown."""
    return SURFACE_DENY_LISTS_FROZEN.get(surface, frozenset())


def iter_tools_by_level(level: DangerLevel) -> Iterable[str]:
    """Yield tool names registered at the given danger level."""
    for name, lv in TOOL_DANGER_MAP.items():
        if lv == level:
            yield name


def summarize_policy() -> dict[str, object]:
    """Compact dict for logging or admin UI (counts only, not full lists)."""
    return {
        "surfaces": list(SURFACE_DENY_LISTS.keys()),
        "critical_count": sum(
            1 for v in TOOL_DANGER_MAP.values() if v == DangerLevel.CRITICAL
        ),
        "warn_count": sum(1 for v in TOOL_DANGER_MAP.values() if v == DangerLevel.WARN),
        "mapped_tools": len(TOOL_DANGER_MAP),
    }


def get_danger_level(tool_name: str) -> DangerLevel:
    """Return configured danger level, defaulting to SAFE for unknown tools."""
    return TOOL_DANGER_MAP.get(tool_name, DangerLevel.SAFE)


def requires_approval(tool_name: str) -> bool:
    """True when the tool is WARN or CRITICAL (needs explicit approval flow)."""
    level = get_danger_level(tool_name)
    return level in (DangerLevel.WARN, DangerLevel.CRITICAL)


def is_tool_allowed(tool_name: str, surface: str) -> bool:
    """
    False if the tool is denied on this surface; True otherwise.
    Unknown surfaces are treated as unrestricted (no deny list entry).
    """
    denied = SURFACE_DENY_LISTS.get(surface)
    if denied is None:
        return True
    return tool_name not in denied


__all__ = [
    "DangerLevel",
    "TOOL_DANGER_MAP",
    "SURFACE_DENY_LISTS",
    "SURFACE_DENY_LISTS_FROZEN",
    "known_surfaces",
    "denied_tools_for_surface",
    "iter_tools_by_level",
    "summarize_policy",
    "get_danger_level",
    "requires_approval",
    "is_tool_allowed",
]
