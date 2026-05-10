"""Audit-r8 brief #08 HIGH regression test.

The morning briefing used to verbalise `frame.heart_rate` /
`frame.spo2_pct` from the first available `PerceptionFrame` regardless
of the sample timestamp. So a stale Apple HealthKit reading from hours
ago would be spoken aloud as "your resting heart rate is …" — the
same hallucination class the chat path fixed in 2026.5.18 but missed
in `_build_morning_briefing`.

These tests pin the freshness gate.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agents.proactive_engine import ProactiveEngine, _FRESH_WINDOW_S
from perception.fusion import PerceptionFrame


def _frame(*, hr_age: float | None = 5.0, spo2_age: float | None = 5.0) -> PerceptionFrame:
    """Build a frame with HR=72 / SpO2=98 and the given sample ages."""
    now = time.time()
    f = PerceptionFrame()
    f.heart_rate = 72
    f.spo2_pct = 98
    if hr_age is not None:
        f.heart_rate_sample_ts = now - hr_age
    if spo2_age is not None:
        f.spo2_sample_ts = now - spo2_age
    return f


def _engine_with_frame(frame: PerceptionFrame) -> ProactiveEngine:
    perception = MagicMock()
    perception._frames = {"test": frame}
    perception.get_frame = lambda sid: frame if sid == "test" else None
    eng = ProactiveEngine(perception=perception, memory=None)
    return eng


def _spoken(msg) -> str:
    """ProactiveMessage stores the briefing in `body` + optional
    `voice_text`. Return whichever has content for assertions."""
    if msg is None:
        return ""
    return f"{msg.body}\n{msg.voice_text}"


@pytest.mark.asyncio
async def test_fresh_vitals_are_verbalised():
    eng = _engine_with_frame(_frame(hr_age=10.0, spo2_age=10.0))
    msg = await eng._build_morning_briefing()
    assert msg is not None
    text = _spoken(msg)
    assert "72" in text
    assert "98" in text


@pytest.mark.asyncio
async def test_stale_vitals_are_suppressed():
    """Vitals older than _FRESH_WINDOW_S must not be verbalised — the
    operator caught a phantom HR=115 line in the early build."""
    age = _FRESH_WINDOW_S + 60.0
    eng = _engine_with_frame(_frame(hr_age=age, spo2_age=age))
    msg = await eng._build_morning_briefing()
    text = _spoken(msg)
    assert "72" not in text
    assert "98" not in text


@pytest.mark.asyncio
async def test_partial_freshness_only_speaks_fresh_metric():
    """HR fresh, SpO2 stale → speak HR alone."""
    eng = _engine_with_frame(_frame(hr_age=10.0, spo2_age=_FRESH_WINDOW_S + 60.0))
    msg = await eng._build_morning_briefing()
    assert msg is not None
    text = _spoken(msg)
    assert "72" in text
    assert "98" not in text


@pytest.mark.asyncio
async def test_missing_sample_ts_is_treated_as_stale():
    """Pre-2026.5.18 clients omit `*_sample_ts`. The briefing must not
    fabricate freshness from that omission."""
    eng = _engine_with_frame(_frame(hr_age=None, spo2_age=None))
    msg = await eng._build_morning_briefing()
    text = _spoken(msg)
    assert "72" not in text
