"""Tests for perception/somatic.py — vector population, cognitive load, circadian,
behavioral policy, context injection, and privacy audit."""
import logging
import time

import pytest

from perception.somatic import BehavioralPolicy, SomaticEngine, SomaticVector


# ── Health frame population ──────────────────────────────────────────────────

class TestVectorFromHealthFrame:
    """All 12 health-frame dimensions must be populated."""

    @pytest.fixture()
    def engine_with_frame(self):
        engine = SomaticEngine()
        sensors = {
            "vitals": {
                "ppg_heart_rate": 75,
                "hrv_ms": 55,
                "spo2_pct": 98,
                "skin_temperature_c": 36.5,
                "steps_today": 4200,
                "last_sleep_quality": 0.8,
            },
            "battery_pct": 72,
            "inferred_state": "walking",
            "environment": {"ambient_light_lux": 500},
        }
        engine.update_from_perception_frame("sess1", sensors)
        return engine.get_vector("sess1")

    def test_heart_rate(self, engine_with_frame):
        assert engine_with_frame.heart_rate == 75

    def test_hrv_ms(self, engine_with_frame):
        assert engine_with_frame.hrv_ms == 55

    def test_spo2_pct(self, engine_with_frame):
        assert engine_with_frame.spo2_pct == 98

    def test_skin_temp(self, engine_with_frame):
        assert engine_with_frame.skin_temp_c == 36.5

    def test_activity_level(self, engine_with_frame):
        assert engine_with_frame.activity_level == 0.5  # walking

    def test_steps_today(self, engine_with_frame):
        assert engine_with_frame.steps_today == 4200

    def test_stress_level(self, engine_with_frame):
        assert isinstance(engine_with_frame.stress_level, float)

    def test_cognitive_load(self, engine_with_frame):
        assert isinstance(engine_with_frame.cognitive_load, float)

    def test_fatigue_level(self, engine_with_frame):
        assert isinstance(engine_with_frame.fatigue_level, float)

    def test_battery_pct(self, engine_with_frame):
        assert engine_with_frame.battery_pct == 72

    def test_circadian_phase(self, engine_with_frame):
        assert 0 <= engine_with_frame.circadian_phase <= 1

    def test_last_sleep_quality(self, engine_with_frame):
        assert engine_with_frame.last_sleep_quality == 0.8


# ── Cognitive load calculation ───────────────────────────────────────────────

class TestCognitiveLoad:
    def test_low_hr_high_hrv_calm_means_low_load(self):
        engine = SomaticEngine()
        engine.update_biometrics("s", heart_rate=62, hrv_ms=90, activity_level=0.0)
        v = engine.get_vector("s")
        assert v.cognitive_load < 0.3

    def test_high_hr_low_hrv_means_high_load(self):
        engine = SomaticEngine()
        engine.update_biometrics("s", heart_rate=110, hrv_ms=20, activity_level=0.1)
        v = engine.get_vector("s")
        assert v.cognitive_load > 0.5


# ── Circadian phase labeling ────────────────────────────────────────────────

class TestCircadianPhase:
    def test_morning(self):
        v = SomaticVector(circadian_phase=9.0 / 24)  # 9 AM
        s = v.to_compact_string()
        assert "morning" in s.lower()

    def test_evening(self):
        v = SomaticVector(circadian_phase=20.0 / 24)  # 8 PM
        s = v.to_compact_string()
        assert "evening" in s.lower()

    def test_afternoon(self):
        v = SomaticVector(circadian_phase=14.0 / 24)  # 2 PM
        s = v.to_compact_string()
        assert "afternoon" in s.lower()


# ── BehavioralPolicy.from_vector ─────────────────────────────────────────────

class TestBehavioralPolicy:
    def test_high_cognitive_load(self):
        v = SomaticVector(cognitive_load=0.85, circadian_phase=0.5)
        policy = BehavioralPolicy.from_vector(v)
        assert "calm" in policy.suggestion.lower() or "shorter" in policy.suggestion.lower()
        assert policy.suppress_non_urgent is True
        assert policy.max_response_tokens is not None

    def test_low_cognitive_load(self):
        v = SomaticVector(cognitive_load=0.1, circadian_phase=0.5)
        policy = BehavioralPolicy.from_vector(v)
        assert policy.suggestion == "normal"
        assert policy.suppress_non_urgent is False


# ── build_context_injection ──────────────────────────────────────────────────

class TestBuildContextInjection:
    def test_returns_nonempty_with_metrics(self):
        engine = SomaticEngine()
        engine.update_biometrics("s", heart_rate=80, hrv_ms=50, spo2_pct=97)
        text = engine.build_context_injection("s")
        assert len(text) > 0
        assert "HR" in text or "Somatic" in text

    def test_empty_when_no_data(self):
        engine = SomaticEngine()
        text = engine.build_context_injection("empty")
        assert text == ""


# ── Privacy audit ────────────────────────────────────────────────────────────

class TestPrivacyAudit:
    """No logger output at INFO+ should contain raw biometric numbers."""

    def test_info_logs_no_raw_heart_rate(self, caplog):
        engine = SomaticEngine()
        with caplog.at_level(logging.INFO, logger="feral.perception.somatic"):
            engine.update_biometrics("s", heart_rate=72, hrv_ms=45, spo2_pct=98)
        for record in caplog.records:
            if record.levelno >= logging.INFO:
                assert "72" not in record.getMessage(), \
                    f"Raw HR value leaked at {record.levelname}: {record.getMessage()}"
                assert "45" not in record.getMessage(), \
                    f"Raw HRV value leaked at {record.levelname}: {record.getMessage()}"

    def test_debug_may_contain_biometrics(self, caplog):
        engine = SomaticEngine()
        with caplog.at_level(logging.DEBUG, logger="feral.perception.somatic"):
            engine.update_biometrics("s", heart_rate=72, hrv_ms=45, spo2_pct=98)
        debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("72" in m for m in debug_msgs), "Biometrics should be logged at DEBUG"
