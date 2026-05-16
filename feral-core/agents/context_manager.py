"""
Context window management for the FERAL orchestrator.

Handles conversation history compaction and message truncation
to keep the LLM context within token budgets.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("feral.orchestrator.context")


class ContextManager:
    """Manages conversation history size and compaction."""

    def __init__(self, max_messages: int = 15):
        self.max_messages = max_messages

    def compact(self, history: list[dict]) -> list[dict]:
        """Trim history to the most recent *max_messages* entries.

        v2026.5.29 — tool-aware compaction. A naive ``history[-N:]``
        slice can land inside an assistant ``tool_calls`` round-trip
        and drop the announcing assistant turn while keeping the
        ``role:"tool"`` rows that follow it. The Responses API then
        rejects the next request with
        ``400 No tool call found for function call output``.

        We expand the window backwards whenever the cut point would
        produce an orphan tool row, until either the announcing
        assistant turn is included or we hit a safe (user / plain
        assistant / system) boundary. If no safe boundary is found we
        drop the leading orphan tool rows instead — the translator
        guard then makes the request well-formed.
        """
        if len(history) <= self.max_messages:
            return history
        start = len(history) - self.max_messages
        # Expand the window backwards until the row at ``start`` is no
        # longer an orphan ``tool``. We pull in the preceding assistant
        # turn(s) so any matching ``function_call`` is in the same
        # window as its output.
        while start > 0 and _is_orphan_tool_boundary(history, start):
            start -= 1
        compacted = history[start:]
        # If the tail still begins with one or more orphan tool rows
        # (no assistant within reach), strip them: there is no
        # ``function_call`` to pair with and OpenAI will 400 if we
        # send them.
        compacted = _drop_leading_orphan_tools(compacted)
        logger.info(
            "Compacting context window from %d to %d (tool-aware)",
            len(history),
            len(compacted),
        )
        return compacted


def _is_orphan_tool_boundary(history: list[dict], idx: int) -> bool:
    """Return True when the row at ``idx`` is a ``tool`` result and
    the preceding row in the full history is *also* part of the same
    tool round-trip (so the window starts mid-call)."""
    if idx <= 0 or idx >= len(history):
        return False
    row = history[idx]
    if not isinstance(row, dict) or row.get("role") != "tool":
        return False
    prev = history[idx - 1]
    if not isinstance(prev, dict):
        return False
    prev_role = prev.get("role")
    if prev_role == "tool":
        return True
    if prev_role == "assistant" and prev.get("tool_calls"):
        # The announcing assistant turn is immediately before; pull it
        # into the window.
        return True
    return False


def _drop_leading_orphan_tools(history: list[dict]) -> list[dict]:
    """Strip any leading ``role:"tool"`` rows whose announcing
    assistant turn is missing from the window."""
    if not history:
        return history
    announced: set[str] = set()
    for row in history:
        if not isinstance(row, dict):
            continue
        if row.get("role") == "assistant" and row.get("tool_calls"):
            for tc in row["tool_calls"]:
                if isinstance(tc, dict):
                    cid = tc.get("id")
                    if isinstance(cid, str) and cid:
                        announced.add(cid)
    # Only drop *leading* orphans to preserve the chronological
    # interior; the translator drops mid-list orphans defensively.
    drop_until = 0
    for i, row in enumerate(history):
        if not isinstance(row, dict) or row.get("role") != "tool":
            break
        cid = row.get("tool_call_id") or row.get("call_id") or ""
        if cid and cid in announced:
            break
        drop_until = i + 1
    if drop_until == 0:
        return history
    return history[drop_until:]
