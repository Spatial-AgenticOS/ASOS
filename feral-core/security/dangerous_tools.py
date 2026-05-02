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

Naming compatibility
--------------------
Two naming conventions coexist in the codebase:

* Legacy / external (MCP, providers): dotted ``skill.endpoint`` (e.g. ``shell.exec``).
* Internal skills / LLM tool ids: double-underscore ``skill__endpoint``
  (e.g. ``desktop_control__shell_command``).

Deny-list matching normalises a tool name into multiple candidate forms so a
single policy entry catches both shapes — adding ``shell.exec`` denies
``shell__exec`` too, and vice versa. Bare endpoint names are NOT auto-matched
to keep the policy explicit; if you need that you must add the bare name.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Iterable, Mapping, Optional


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
    # Modern skill__endpoint equivalents — explicit so danger level reads true
    # even when caller passes the LLM-facing tool id directly.
    "desktop_control__shell_command": DangerLevel.CRITICAL,
    "desktop_control__shell": DangerLevel.CRITICAL,
    "computer_use__bash": DangerLevel.CRITICAL,
    "code_interpreter__execute": DangerLevel.CRITICAL,
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
        # Legacy dotted form — kept for backward-compat with external/MCP callers.
        "system.run",
        "docker.exec",
        "browser.evaluate",
        "shell.exec",
        "process.spawn",
        "fs.delete",
        "fs.remove",
        "filesystem.delete",
        "file.delete",
        # Modern internal tool ids that bypass the dotted lookup. Listing these
        # explicitly means matching does not depend on the candidate-form
        # transform alone — defence in depth against future renames.
        "desktop_control__shell_command",
        "desktop_control__shell",
        "computer_use__bash",
        "code_interpreter__execute",
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


# Map ``handle_command`` context["source"] values to the matching execution
# surface. Anything unknown / missing is conservatively treated as websocket
# (interactive operator channel) which preserves the prior default behaviour.
_SOURCE_TO_SURFACE: dict[str, str] = {
    "webhook": "http_api",
    "phone_surface": "http_api",
    "channel": "http_api",
    "cron": "http_api",
    "proactive": "http_api",
    "http_api": "http_api",
    "rest": "http_api",
    "voice": "websocket",
    "voice_text": "websocket",
    "voice_chained": "websocket",
    "voice_realtime": "websocket",
    "node_text": "websocket",
    "gesture": "websocket",
    "vision_ask": "websocket",
    "websocket": "websocket",
    "ws": "websocket",
    "cli": "local_cli",
    "local_cli": "local_cli",
    "operator_cli": "local_cli",
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


def _candidate_forms(tool_name: str) -> set[str]:
    """Return every form of ``tool_name`` that should hit the same policy.

    Modern internal LLM tools use ``skill__endpoint``; legacy/external (MCP,
    providers) use dotted ``skill.endpoint``. Tests and gateway code already
    pass either shape, so deny-list matching needs to recognise both for the
    same logical tool.

    Bare endpoint names are intentionally NOT generated here — promoting
    ``foo`` from ``svc__foo`` would broaden enforcement across unrelated
    skills.
    """
    if not tool_name:
        return set()
    cands = {tool_name}
    if "__" in tool_name:
        skill, _, endpoint = tool_name.partition("__")
        if skill and endpoint:
            cands.add(f"{skill}.{endpoint}")
    elif "." in tool_name:
        skill, _, endpoint = tool_name.partition(".")
        if skill and endpoint:
            cands.add(f"{skill}__{endpoint}")
    return cands


def get_danger_level(tool_name: str) -> DangerLevel:
    """Return configured danger level, defaulting to SAFE for unknown tools.

    Honours both naming conventions: ``shell.exec`` and ``shell__exec``
    resolve to the same entry.
    """
    for cand in _candidate_forms(tool_name):
        level = TOOL_DANGER_MAP.get(cand)
        if level is not None:
            return level
    return DangerLevel.SAFE


def requires_approval(tool_name: str) -> bool:
    """True when the tool is WARN or CRITICAL (needs explicit approval flow)."""
    level = get_danger_level(tool_name)
    return level in (DangerLevel.WARN, DangerLevel.CRITICAL)


def is_tool_allowed(tool_name: str, surface: str) -> bool:
    """
    False if the tool is denied on this surface; True otherwise.

    Unknown surfaces are treated as unrestricted (no deny list entry). The
    matcher tests both ``skill.endpoint`` and ``skill__endpoint`` candidate
    forms so policy stays naming-agnostic.
    """
    denied = SURFACE_DENY_LISTS.get(surface)
    if denied is None:
        return True
    if not denied:
        return True
    candidates = _candidate_forms(tool_name)
    return candidates.isdisjoint(denied)


def resolve_surface_from_context(
    context: Optional[Mapping[str, object]],
    *,
    default: str = "websocket",
) -> str:
    """Map a ``handle_command`` context dict to an execution surface.

    Looks up ``context["source"]`` (lowercased) in the source→surface table
    and falls back to ``context["surface"]`` if the caller already supplied
    one explicitly. Returns ``default`` (websocket — the historical default)
    when neither key is present or recognised.
    """
    if not context:
        return default
    surface = context.get("surface") if isinstance(context, Mapping) else None
    if isinstance(surface, str) and surface:
        return surface
    source = context.get("source") if isinstance(context, Mapping) else None
    if isinstance(source, str) and source:
        mapped = _SOURCE_TO_SURFACE.get(source.strip().lower())
        if mapped:
            return mapped
    return default


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
    "resolve_surface_from_context",
]
