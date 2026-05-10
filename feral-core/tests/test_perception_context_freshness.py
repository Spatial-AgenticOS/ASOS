"""Pin freshness gating in ``PerceptionFrame.to_system_context``.

Operator report 2026-05-09 round 3 (with screenshot): the user asked
"What's my heart rate?" and the assistant replied with a markdown
table claiming ``Heart Rate: 115 bpm — ⚠️ Elevated, SpO2: 93% —
✓ Normal``. The numbers were real Apple HealthKit reads from earlier
in the day, NOT current. Root cause: ``to_system_context`` injected
``Sensors: HR=115bpm | SpO2=93%`` into the LLM prompt unconditionally.
The model treated those as live and fabricated the assessment.

Fix: ``to_system_context`` now consults the same freshness window
the proactive engine uses (``_CONTEXT_FRESH_S = 120s``):

  * Fresh readings (sample_ts within window) appear plain.
  * Stale readings (sample_ts older than window) appear with an
    explicit `(stale, Xs ago — do NOT report as current)` suffix
    so the model knows to qualify or omit.
  * Readings with `*_sample_ts == 0.0` (sender never plumbed
    freshness — same defensive default the proactive engine uses)
    are SUPPRESSED — they don't appear in the prompt at all.

Same docstring for the `Adaptive behavior hints` ("Heart rate
critically high…") block — those only fire on fresh HR.
"""

from __future__ import annotations

import time

import pytest

from perception.fusion import PerceptionFrame


def test_fresh_hr_appears_plain_in_context() -> None:
    frame = PerceptionFrame(
        heart_rate=72,
        heart_rate_sample_ts=time.time() - 5.0,  # fresh
    )
    ctx = frame.to_system_context()
    assert "HR=72bpm" in ctx
    assert "stale" not in ctx, "fresh reading must not carry a stale suffix"


def test_stale_hr_carries_stale_suffix_with_age() -> None:
    """The exact case from the operator screenshot."""
    age_s = 4 * 3600  # 4 hours
    frame = PerceptionFrame(
        heart_rate=115,
        heart_rate_sample_ts=time.time() - age_s,
    )
    ctx = frame.to_system_context()
    assert "HR=115bpm" in ctx
    assert "stale" in ctx, (
        "Stale HR (4h old) MUST appear with a `(stale, …)` suffix so "
        "the LLM does NOT treat it as current. The exact 2026-05-09 "
        "phantom 'Heart Rate: 115 bpm Elevated' table came from this "
        "context being unqualified."
    )
    assert "do NOT report as current" in ctx, (
        "The stale tag must include explicit instruction to the model. "
        "A bare timestamp isn't enough — the model still rendered the "
        "table when only an `age=14400s` field was present."
    )


def test_hr_with_no_sample_ts_is_suppressed_from_context() -> None:
    """Frames from old-build senders that don't plumb sample_ts must
    not leak HR into the prompt at all — defensive default treats
    missing freshness data as untrusted.
    """
    frame = PerceptionFrame(
        heart_rate=115,
        heart_rate_sample_ts=0.0,  # explicit "never seen"
    )
    ctx = frame.to_system_context()
    assert "HR=115bpm" not in ctx, (
        "HR must be SUPPRESSED from LLM context when sample_ts is unset. "
        "Otherwise an old-build iPhone sending HR without a timestamp "
        "would feed the model a ghost value."
    )


def test_stale_spo2_carries_stale_suffix() -> None:
    age_s = 2 * 3600  # 2 hours
    frame = PerceptionFrame(
        spo2_pct=93,
        spo2_sample_ts=time.time() - age_s,
    )
    ctx = frame.to_system_context()
    assert "SpO2=93%" in ctx
    assert "stale" in ctx
    assert "do NOT report as current" in ctx


def test_spo2_with_no_sample_ts_is_suppressed() -> None:
    frame = PerceptionFrame(
        spo2_pct=93,
        spo2_sample_ts=0.0,
    )
    ctx = frame.to_system_context()
    assert "SpO2=93%" not in ctx


def test_stale_hr_does_not_trigger_critical_alert_hint() -> None:
    """Adaptive hints must also gate on freshness — otherwise the
    model gets a stale-driven `USER ALERT: Heart rate critically high`
    nudge that biases every reply for the rest of the session.
    """
    frame = PerceptionFrame(
        heart_rate=160,  # would normally fire the critical hint
        heart_rate_sample_ts=time.time() - (3 * 3600),  # 3h old
    )
    ctx = frame.to_system_context()
    assert "USER ALERT" not in ctx
    assert "Heart rate critically high" not in ctx


def test_fresh_high_hr_does_trigger_critical_alert_hint() -> None:
    frame = PerceptionFrame(
        heart_rate=160,
        heart_rate_sample_ts=time.time() - 5.0,  # fresh
    )
    ctx = frame.to_system_context()
    assert "USER ALERT" in ctx
    assert "Heart rate critically high" in ctx


def test_fresh_elevated_hr_does_trigger_brevity_hint() -> None:
    frame = PerceptionFrame(
        heart_rate=110,
        heart_rate_sample_ts=time.time() - 5.0,
    )
    ctx = frame.to_system_context()
    assert "elevated" in ctx
    assert "brief" in ctx
