"""
FERAL Demo Hardware Simulator
===============================
Generates realistic physiological and device telemetry for demo recordings.
Patterns mimic real human data — not random noise.
"""

from __future__ import annotations
import asyncio
import logging
import math
import random
import time
from typing import Callable, Awaitable

logger = logging.getLogger("feral.demo")


class WristbandSimulator:
    """Generates realistic heart-rate, SpO2, and skin-temp patterns.

    Uses circadian rhythm + activity state + noise to produce data
    that looks convincing in a live demo.
    """

    def __init__(self):
        self._start = time.time()
        self._activity = "resting"
        self._stress_event_at: float | None = None

    def set_activity(self, state: str):
        self._activity = state

    def trigger_stress_spike(self, duration_s: float = 30):
        self._stress_event_at = time.time()
        asyncio.get_event_loop().call_later(duration_s, self._clear_stress)

    def _clear_stress(self):
        self._stress_event_at = None

    def read(self) -> dict:
        t = time.time()
        elapsed = t - self._start
        hour_of_day = (time.localtime().tm_hour + time.localtime().tm_min / 60)

        # Circadian HR curve: lower at night, higher during day
        circadian = 62 + 8 * math.sin((hour_of_day - 4) / 24 * 2 * math.pi)

        # Activity modifiers
        activity_add = {"resting": 0, "walking": 20, "running": 50, "working": 5}.get(self._activity, 0)

        # Stress spike
        stress_add = 0
        if self._stress_event_at:
            age = t - self._stress_event_at
            stress_add = max(0, 35 * math.exp(-age / 15))

        # Breathing-rate oscillation (RSA)
        rsa = 3 * math.sin(elapsed * 0.25)

        hr = int(circadian + activity_add + stress_add + rsa + random.gauss(0, 1.5))
        hr = max(50, min(180, hr))

        # SpO2: normally 96-99, dips slightly with exertion
        spo2_base = 98 - (activity_add / 30)
        spo2 = round(max(92, min(100, spo2_base + random.gauss(0, 0.3))), 1)

        # Skin temperature: slow drift
        temp_base = 36.4 + 0.3 * math.sin((hour_of_day - 16) / 24 * 2 * math.pi)
        temp = round(temp_base + random.gauss(0, 0.1), 1)

        return {
            "heart_rate_bpm": hr,
            "spo2_pct": spo2,
            "skin_temp_c": temp,
            "activity": self._activity,
            "timestamp": t,
        }


class SmartHomeSimulator:
    """Simulates smart home state changes for demo scenarios."""

    def __init__(self):
        self.state = {
            "lights_on": True,
            "brightness": 80,
            "color": "#FFFFFF",
            "color_temp_k": 4000,
            "thermostat_c": 22.0,
            "scene": "default",
        }

    def execute(self, action: str, params: dict) -> dict:
        if action == "set_scene":
            scene = params.get("scene", "relax")
            scenes = {
                "morning": {"brightness": 90, "color_temp_k": 5000, "color": "#FFF5E6"},
                "focus": {"brightness": 100, "color_temp_k": 6500, "color": "#FFFFFF"},
                "relax": {"brightness": 30, "color_temp_k": 2700, "color": "#FF8C00"},
                "calming": {"brightness": 20, "color_temp_k": 2200, "color": "#FFB347"},
                "movie": {"brightness": 5, "color_temp_k": 2000, "color": "#1A0A2E"},
                "sleep": {"brightness": 0, "color_temp_k": 1800, "color": "#000000"},
            }
            settings = scenes.get(scene, scenes["relax"])
            self.state.update(settings)
            self.state["scene"] = scene
            logger.info("Smart home scene: %s -> %s", scene, settings)
            return {"ok": True, "scene": scene, **settings}

        if action == "lights":
            on = params.get("state", "on").lower() == "on"
            self.state["lights_on"] = on
            return {"ok": True, "lights_on": on}

        if action == "brightness":
            bri = int(params.get("value", 80))
            self.state["brightness"] = max(0, min(100, bri))
            return {"ok": True, "brightness": self.state["brightness"]}

        if action == "thermostat":
            temp = float(params.get("temperature", 22))
            self.state["thermostat_c"] = temp
            return {"ok": True, "thermostat_c": temp}

        return {"ok": False, "error": f"Unknown action: {action}"}


class DemoOrchestrator:
    """Coordinates all simulators and feeds telemetry into the brain."""

    def __init__(self, orchestrator=None, sessions=None):
        self.wristband = WristbandSimulator()
        self.smart_home = SmartHomeSimulator()
        self._orchestrator = orchestrator
        self._sessions = sessions
        self._running = False
        self._callbacks: list[Callable] = []
        self._tick = 0

    def set_refs(self, orchestrator, sessions):
        self._orchestrator = orchestrator
        self._sessions = sessions

    def on_telemetry(self, callback: Callable[[dict], Awaitable[None]]):
        self._callbacks.append(callback)

    async def start(self, interval_s: float = 3.0):
        self._running = True
        logger.info("Demo simulators started (interval=%.1fs)", interval_s)
        while self._running:
            data = {
                "source": "demo_simulator",
                "wristband": self.wristband.read(),
                "smart_home": self.smart_home.state,
            }
            for cb in self._callbacks:
                try:
                    await cb(data)
                except Exception as e:
                    logger.warning("Demo telemetry callback error: %s", e)

            self._tick += 1
            if self._orchestrator and self._sessions and self._tick % 3 == 0:
                try:
                    await self._emit_random_brain_event()
                except Exception as e:
                    logger.debug("Demo brain event error: %s", e)

            await asyncio.sleep(interval_s)

    async def _emit_random_brain_event(self):
        """Emit a simulated brain event to liven up the Glass Brain."""
        event_pool = [
            ("llm_call", {"model": "gpt-4o-mini", "source": "demo"}),
            ("tool_exec", {"tool": random.choice(["web_search", "weather_current", "calendar_lookup", "notes_search", "memory_recall"]), "success": True, "source": "demo"}),
            ("memory_write", {"type": random.choice(["episodic", "knowledge", "note"]), "source": "demo"}),
        ]
        if self._tick % 30 == 0:
            event_pool.append(("proactive_alert", {"title": "Demo wellness check", "source": "demo"}))

        event_type, event_data = random.choice(event_pool)
        for sid in list(self._sessions.keys()):
            try:
                await self._orchestrator._emit_brain_event(sid, event_type, event_data)
            except Exception:
                pass

    def stop(self):
        self._running = False
