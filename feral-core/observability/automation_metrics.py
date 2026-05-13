"""PR 12: thin facade over the Prometheus counters so call sites don't
have to import the registry directly.

The actual ``Counter`` objects live in ``observability/metrics.py``;
this module just exposes typed helpers. Every emission is no-op if the
Prometheus client isn't installed at the operator's site (FERAL ships
with it, but downstream consumers may strip it)."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("feral.automation.metrics")


try:
    from observability.metrics import (
        AUTOMATION_BLOCKED_TOTAL,
        AUTOMATION_FAILURE_TOTAL,
        AUTOMATION_PERMISSION_DENIED_TOTAL,
        AUTOMATION_REPAIR_LOOP_TOTAL,
    )
    _HAVE_METRICS = True
except Exception:  # pragma: no cover - prom not installed
    _HAVE_METRICS = False


def record_blocked(tool: str, reason: str) -> None:
    """Tool call blocked by the safety resolver / surface deny list."""
    if not _HAVE_METRICS:
        return
    try:
        AUTOMATION_BLOCKED_TOTAL.labels(tool=str(tool), reason=str(reason)).inc()
    except Exception as exc:
        logger.debug("metrics record_blocked failed: %s", exc)


def record_failure(subsystem: str, reason: str) -> None:
    """Automation action started but failed (browser, GUI, coding, voice)."""
    if not _HAVE_METRICS:
        return
    try:
        AUTOMATION_FAILURE_TOTAL.labels(subsystem=str(subsystem), reason=str(reason)).inc()
    except Exception as exc:
        logger.debug("metrics record_failure failed: %s", exc)


def record_permission_denied(permission: str) -> None:
    """OS-level permission denial (macOS TCC, sandbox grant, OAuth scope)."""
    if not _HAVE_METRICS:
        return
    try:
        AUTOMATION_PERMISSION_DENIED_TOTAL.labels(permission=str(permission)).inc()
    except Exception as exc:
        logger.debug("metrics record_permission_denied failed: %s", exc)


def record_repair_loop(outcome: str) -> None:
    """CodingRun / GoalChecker repair-iteration outcome.

    Pass ``"repaired"`` on a successful repair, ``"gave_up"`` when the
    planner returns no_progress, ``"max_iters"`` when the loop hits
    the budget."""
    if not _HAVE_METRICS:
        return
    try:
        AUTOMATION_REPAIR_LOOP_TOTAL.labels(outcome=str(outcome)).inc()
    except Exception as exc:
        logger.debug("metrics record_repair_loop failed: %s", exc)


__all__ = [
    "record_blocked",
    "record_failure",
    "record_permission_denied",
    "record_repair_loop",
]
