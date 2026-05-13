"""PR 12: automation truthfulness counters are wired and incrementable.

These metrics back the new Grafana panel and the "is the agent
silently failing?" question. They MUST be present in REGISTRY (so
``/metrics`` exposes them), MUST be referenced by the dashboard (so
operators see them), and MUST increment when the call sites fire."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from observability import automation_metrics  # noqa: E402
from observability.metrics import (  # noqa: E402
    AUTOMATION_BLOCKED_TOTAL,
    AUTOMATION_FAILURE_TOTAL,
    AUTOMATION_PERMISSION_DENIED_TOTAL,
    AUTOMATION_REPAIR_LOOP_TOTAL,
    REGISTRY,
    registered_metric_names,
)


def _sample(counter, **labels) -> float:
    metric = counter.labels(**labels)
    return metric._value.get()


def test_all_pr12_counters_registered():
    names = registered_metric_names()
    for name in (
        "feral_automation_blocked_total",
        "feral_automation_failure_total",
        "feral_automation_permission_denied_total",
        "feral_automation_repair_loop_total",
    ):
        assert name in names, f"PR 12 counter {name} missing from REGISTRY"


def test_record_blocked_increments():
    before = _sample(AUTOMATION_BLOCKED_TOTAL, tool="t", reason="r")
    automation_metrics.record_blocked("t", "r")
    after = _sample(AUTOMATION_BLOCKED_TOTAL, tool="t", reason="r")
    assert after == before + 1


def test_record_failure_increments():
    before = _sample(AUTOMATION_FAILURE_TOTAL, subsystem="browser", reason="timeout")
    automation_metrics.record_failure("browser", "timeout")
    after = _sample(AUTOMATION_FAILURE_TOTAL, subsystem="browser", reason="timeout")
    assert after == before + 1


def test_record_permission_denied_increments():
    before = _sample(AUTOMATION_PERMISSION_DENIED_TOTAL, permission="accessibility")
    automation_metrics.record_permission_denied("accessibility")
    after = _sample(AUTOMATION_PERMISSION_DENIED_TOTAL, permission="accessibility")
    assert after == before + 1


def test_record_repair_loop_outcomes():
    """Three canonical outcomes are surfaced; each is a separate label."""
    counts = {}
    for outcome in ("repaired", "gave_up", "max_iters"):
        before = _sample(AUTOMATION_REPAIR_LOOP_TOTAL, outcome=outcome)
        automation_metrics.record_repair_loop(outcome)
        after = _sample(AUTOMATION_REPAIR_LOOP_TOTAL, outcome=outcome)
        counts[outcome] = after - before
    assert all(v == 1 for v in counts.values()), counts


def test_metrics_exposable_via_registry():
    """Belt-and-braces: the Prometheus exposition string includes the
    PR 12 counter names — operators will scrape this."""
    from prometheus_client import generate_latest

    blob = generate_latest(REGISTRY).decode("utf-8")
    for name in (
        "feral_automation_blocked_total",
        "feral_automation_failure_total",
        "feral_automation_permission_denied_total",
        "feral_automation_repair_loop_total",
    ):
        assert name in blob, f"{name} not exposed via /metrics"
