"""Somatic Context Layer — real-time body vector injected into every LLM call.

The 12-dimensional body vector fuses biometric, behavioral, and environmental
signals to let the AI adapt its cognition to the user's physical state.
"""
from __future__ import annotations
import math
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("feral.perception.somatic")


@dataclass
class SomaticVector:
    """12-dimensional body state vector updated every 5 seconds."""
    timestamp: float = field(default_factory=time.time)

    # Biometric (from wearable sensors)
    heart_rate: float = 0.0         # bpm
    hrv_ms: float = 0.0             # heart rate variability in ms (RMSSD)
    skin_temp_c: float = 0.0        # skin temperature
    spo2_pct: float = 0.0           # blood oxygen saturation
    activity_level: float = 0.0     # 0=sedentary, 0.5=walking, 1.0=running
    steps_today: int = 0            # step count since midnight
    battery_pct: float = 0.0        # wearable battery percentage

    # Behavioral (from interaction telemetry)
    typing_speed_wpm: float = 0.0   # words per minute
    interaction_gap_s: float = 0.0  # seconds since last interaction

    # Environmental
    ambient_light_lux: float = 0.0
    noise_level_db: float = 0.0

    # Computed
    circadian_phase: float = 0.0    # 0-1 where 0=midnight, 0.5=noon
    sleep_debt_hours: float = 0.0   # estimated accumulated sleep debt
    cognitive_load: float = 0.0     # 0-1 composite cognitive load index
    stress_level: float = 0.0       # 0-1 composite stress index
    fatigue_level: float = 0.0      # 0-1 estimated fatigue
    last_sleep_quality: float = 0.0 # 0-1 last night's sleep quality

    def to_compact_string(self) -> str:
        """Serialize to a compact token-efficient string for LLM context."""
        parts = []
        if self.heart_rate > 0:
            parts.append(f"HR:{self.heart_rate:.0f}bpm")
        if self.hrv_ms > 0:
            parts.append(f"HRV:{self.hrv_ms:.0f}ms")
        if self.spo2_pct > 0:
            parts.append(f"SpO2:{self.spo2_pct:.0f}%")
        if self.skin_temp_c > 0:
            parts.append(f"Temp:{self.skin_temp_c:.1f}\u00b0C")
        if self.activity_level > 0:
            activity_label = "sedentary" if self.activity_level < 0.3 else "active" if self.activity_level < 0.7 else "intense"
            parts.append(f"Activity:{activity_label}")
        if self.cognitive_load > 0:
            parts.append(f"CogLoad:{self.cognitive_load:.2f}")
        if self.circadian_phase > 0:
            hour = self.circadian_phase * 24
            phase = "morning" if 6 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening" if 18 <= hour < 22 else "night"
            parts.append(f"Phase:{phase}")
        if self.sleep_debt_hours > 1:
            parts.append(f"SleepDebt:{self.sleep_debt_hours:.1f}h")
        return " | ".join(parts) if parts else "No biometric data"

    def to_dict(self) -> dict:
        return {
            "heart_rate": self.heart_rate,
            "hrv_ms": self.hrv_ms,
            "skin_temp_c": self.skin_temp_c,
            "spo2_pct": self.spo2_pct,
            "activity_level": self.activity_level,
            "steps_today": self.steps_today,
            "battery_pct": self.battery_pct,
            "typing_speed_wpm": self.typing_speed_wpm,
            "interaction_gap_s": self.interaction_gap_s,
            "ambient_light_lux": self.ambient_light_lux,
            "noise_level_db": self.noise_level_db,
            "circadian_phase": self.circadian_phase,
            "sleep_debt_hours": self.sleep_debt_hours,
            "cognitive_load": self.cognitive_load,
            "stress_level": self.stress_level,
            "fatigue_level": self.fatigue_level,
            "last_sleep_quality": self.last_sleep_quality,
        }


@dataclass
class BehavioralPolicy:
    """Behavioral modification policy based on somatic state."""
    max_response_tokens: Optional[int] = None
    suppress_non_urgent: bool = False
    tone: str = "normal"  # "calm", "energetic", "concise", "normal"
    proactive_level: str = "normal"  # "silent", "reduced", "normal", "active"
    tool_restrictions: list[str] = field(default_factory=list)
    suggestion: str = "normal"

    @classmethod
    def from_vector(cls, v: "SomaticVector") -> "BehavioralPolicy":
        """Derive a behavioral policy directly from a somatic vector."""
        policy = cls()
        if v.cognitive_load > 0.7:
            policy.max_response_tokens = 150
            policy.suppress_non_urgent = True
            policy.tone = "calm"
            policy.proactive_level = "reduced"
            policy.suggestion = "calm voice, shorter responses"
            policy.tool_restrictions = ["financial", "delete", "send_email"]
        elif v.cognitive_load > 0.4:
            policy.tone = "normal"
            policy.suggestion = "normal"
        else:
            policy.tone = "normal"
            policy.proactive_level = "active"
            policy.suggestion = "normal"

        if 0 < v.spo2_pct < 94:
            policy.tone = "calm"
            policy.suppress_non_urgent = True

        hour = v.circadian_phase * 24
        if hour < 5 or hour > 23:
            policy.tone = "calm"
            policy.suppress_non_urgent = True
        return policy


class SomaticEngine:
    """Maintains per-session somatic state and generates behavioral policies."""

    def __init__(self):
        self._vectors: dict[str, SomaticVector] = {}
        self._last_interaction: dict[str, float] = {}
        self._typing_samples: dict[str, list[float]] = {}

    def get_vector(self, session_id: str) -> SomaticVector:
        if session_id not in self._vectors:
            self._vectors[session_id] = SomaticVector()
        return self._vectors[session_id]

    def update_biometrics(self, session_id: str, heart_rate: float = 0, hrv_ms: float = 0,
                          spo2_pct: float = 0, skin_temp_c: float = 0, activity_level: float = 0,
                          steps_today: int = 0, battery_pct: float = 0,
                          last_sleep_quality: float = 0):
        v = self.get_vector(session_id)
        if heart_rate > 0:
            v.heart_rate = heart_rate
        if hrv_ms > 0:
            v.hrv_ms = hrv_ms
        if spo2_pct > 0:
            v.spo2_pct = spo2_pct
        if skin_temp_c > 0:
            v.skin_temp_c = skin_temp_c
        if activity_level >= 0:
            v.activity_level = activity_level
        if steps_today > 0:
            v.steps_today = steps_today
        if battery_pct > 0:
            v.battery_pct = battery_pct
        if last_sleep_quality > 0:
            v.last_sleep_quality = last_sleep_quality
        v.timestamp = time.time()
        logger.debug(
            "Biometrics updated session=%s HR=%.0f HRV=%.0f SpO2=%.0f",
            session_id[:8], v.heart_rate, v.hrv_ms, v.spo2_pct,
        )
        logger.info("Somatic context updated for session %s", session_id[:8])
        self._recompute_cognitive_load(session_id)

    def update_interaction(self, session_id: str, text_length: int = 0):
        now = time.time()
        v = self.get_vector(session_id)

        last = self._last_interaction.get(session_id, now)
        v.interaction_gap_s = now - last
        self._last_interaction[session_id] = now

        if text_length > 0 and v.interaction_gap_s > 0:
            words = text_length / 5.0
            minutes = v.interaction_gap_s / 60.0
            if minutes > 0:
                wpm = words / minutes
                samples = self._typing_samples.setdefault(session_id, [])
                samples.append(min(wpm, 200))
                if len(samples) > 20:
                    samples[:] = samples[-20:]
                v.typing_speed_wpm = sum(samples) / len(samples)

        self._update_circadian(session_id)
        self._recompute_cognitive_load(session_id)

    def update_environment(self, session_id: str, ambient_light_lux: float = 0, noise_level_db: float = 0):
        v = self.get_vector(session_id)
        if ambient_light_lux > 0:
            v.ambient_light_lux = ambient_light_lux
        if noise_level_db > 0:
            v.noise_level_db = noise_level_db

    def _update_circadian(self, session_id: str):
        v = self.get_vector(session_id)
        t = time.localtime()
        v.circadian_phase = (t.tm_hour * 60 + t.tm_min) / 1440.0

    def _recompute_cognitive_load(self, session_id: str):
        """Compute cognitive load index (0-1) from available signals."""
        v = self.get_vector(session_id)
        signals = []

        if v.hrv_ms > 0:
            hrv_load = max(0, 1.0 - (v.hrv_ms / 100.0))
            signals.append(("hrv", hrv_load, 0.3))

        if v.heart_rate > 0 and v.activity_level < 0.3:
            hr_load = max(0, min(1, (v.heart_rate - 60) / 60.0))
            signals.append(("hr", hr_load, 0.2))

        if v.typing_speed_wpm > 0:
            typing_load = max(0, 1.0 - (v.typing_speed_wpm / 80.0))
            signals.append(("typing", typing_load, 0.15))

        if v.interaction_gap_s > 30:
            gap_load = min(1, v.interaction_gap_s / 300.0)
            signals.append(("gap", gap_load, 0.1))

        circadian_load = 0.0
        hour = v.circadian_phase * 24
        if hour < 6 or hour > 22:
            circadian_load = 0.3
        elif 13 <= hour <= 15:
            circadian_load = 0.15  # post-lunch dip
        signals.append(("circadian", circadian_load, 0.15))

        if v.sleep_debt_hours > 0:
            sleep_load = min(1, v.sleep_debt_hours / 8.0)
            signals.append(("sleep", sleep_load, 0.1))

        if not signals:
            v.cognitive_load = 0.0
            return

        total_weight = sum(w for _, _, w in signals)
        v.cognitive_load = sum(val * w for _, val, w in signals) / total_weight if total_weight > 0 else 0.0
        self._recompute_stress(session_id)
        self._recompute_fatigue(session_id)

    def _recompute_stress(self, session_id: str):
        """Compute stress index from HR and HRV: high HR + low HRV = high stress."""
        v = self.get_vector(session_id)
        signals = []
        if v.heart_rate > 0 and v.activity_level < 0.3:
            hr_stress = max(0, min(1, (v.heart_rate - 60) / 60.0))
            signals.append(hr_stress * 0.5)
        if v.hrv_ms > 0:
            hrv_stress = max(0, 1.0 - (v.hrv_ms / 100.0))
            signals.append(hrv_stress * 0.5)
        v.stress_level = sum(signals) if signals else 0.0

    def _recompute_fatigue(self, session_id: str):
        """Compute fatigue from sleep debt + circadian dip + low sleep quality."""
        v = self.get_vector(session_id)
        fatigue = 0.0
        if v.sleep_debt_hours > 0:
            fatigue += min(0.5, v.sleep_debt_hours / 8.0)
        hour = v.circadian_phase * 24
        if hour < 6 or hour > 22:
            fatigue += 0.2
        elif 13 <= hour <= 15:
            fatigue += 0.1
        if 0 < v.last_sleep_quality < 0.5:
            fatigue += 0.2
        v.fatigue_level = min(1.0, fatigue)

    def get_behavioral_policy(self, session_id: str) -> BehavioralPolicy:
        """Generate behavioral policy based on current somatic state."""
        v = self.get_vector(session_id)
        policy = BehavioralPolicy()

        if v.cognitive_load > 0.7:
            policy.max_response_tokens = 150
            policy.suppress_non_urgent = True
            policy.tone = "concise"
            policy.proactive_level = "reduced"
            policy.tool_restrictions = ["financial", "delete", "send_email"]
        elif v.cognitive_load > 0.4:
            policy.tone = "normal"
            policy.proactive_level = "normal"
        else:
            policy.tone = "normal"
            policy.proactive_level = "active"

        if 0 < v.spo2_pct < 94:
            policy.tone = "calm"
            policy.suppress_non_urgent = True

        hour = v.circadian_phase * 24
        if hour < 5 or hour > 23:
            policy.tone = "calm"
            policy.suppress_non_urgent = True

        return policy

    def build_system_prompt_section(self, session_id: str) -> str:
        """Build the somatic context section for the LLM system prompt."""
        v = self.get_vector(session_id)
        policy = self.get_behavioral_policy(session_id)

        compact = v.to_compact_string()
        if compact == "No biometric data":
            return ""

        lines = [f"## Somatic Context\n{compact}"]

        if policy.tone == "concise":
            lines.append("BEHAVIOR: User is under high cognitive load. Be extremely concise (2-3 sentences max). Avoid lists unless asked.")
        elif policy.tone == "calm":
            lines.append("BEHAVIOR: User needs calm interaction. Use gentle, unhurried language. Prioritize wellbeing.")

        if policy.suppress_non_urgent:
            lines.append("BEHAVIOR: Suppress non-urgent notifications and suggestions.")

        if policy.tool_restrictions:
            lines.append(f"RESTRICTION: Do NOT use these tool categories without explicit confirmation: {', '.join(policy.tool_restrictions)}")

        return "\n".join(lines)

    def build_context_injection(self, session_id: str) -> str:
        """Build a context injection string summarizing the somatic state."""
        return self.build_system_prompt_section(session_id)

    def update_from_perception_frame(self, session_id: str, sensors: dict):
        """Bridge: extract biometric fields from a perception sensor dict and
        forward them to the somatic vector."""
        vitals = sensors.get("vitals", {})
        hr = vitals.get("ppg_heart_rate") or sensors.get("ppg_heart_rate") or sensors.get("heart_rate_bpm") or 0
        hrv = vitals.get("hrv_ms") or sensors.get("hrv_ms") or 0
        spo2 = vitals.get("spo2_pct") or sensors.get("spo2_pct") or 0
        temp = vitals.get("skin_temperature_c") or 0
        steps = vitals.get("steps_today") or sensors.get("steps_today") or 0
        battery = sensors.get("battery_pct") or sensors.get("device", {}).get("battery_pct") or 0
        sleep_q = sensors.get("last_sleep_quality") or vitals.get("last_sleep_quality") or 0
        env = sensors.get("environment", {})
        lux = env.get("ambient_light_lux") or 0

        activity_map = {"resting": 0.0, "sedentary": 0.0, "walking": 0.5, "running": 1.0, "stressed": 0.6}
        inferred = sensors.get("inferred_state", "")
        activity = activity_map.get(inferred, 0.0)

        self.update_biometrics(
            session_id,
            heart_rate=float(hr),
            hrv_ms=float(hrv),
            spo2_pct=float(spo2),
            skin_temp_c=float(temp),
            activity_level=activity,
            steps_today=int(steps),
            battery_pct=float(battery),
            last_sleep_quality=float(sleep_q),
        )
        if lux:
            self.update_environment(session_id, ambient_light_lux=float(lux))
