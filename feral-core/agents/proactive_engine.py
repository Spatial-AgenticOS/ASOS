"""
FERAL Proactive Intelligence Engine
======================================
The #1 differentiator: FERAL doesn't wait for commands — it observes
ambient context (screen, health, calendar, memory) and proactively
initiates when it has something valuable to say.

This is NOT a simple cron. It's a context-aware decision engine with:
  - Priority tiers (critical > important > suggestion > ambient)
  - Cooldown per trigger type (don't nag)
  - User preference learning (track dismiss rates)
  - Time-of-day awareness
  - LLM evaluation for complex triggers

Architecture:
  PerceptionFrame + MemoryStore + Clock
    → TriggerEvaluator (rules + LLM hybrid)
    → ProactiveMessage
    → Delivery (voice / toast / SDUI card)
"""

from __future__ import annotations
import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Optional

logger = logging.getLogger("feral.proactive")


class Priority(Enum):
    CRITICAL = 4    # health emergency, urgent calendar
    IMPORTANT = 3   # meeting in 10 min, stress detected
    SUGGESTION = 2  # "want to take a break?", "you might like..."
    AMBIENT = 1     # weather update, daily summary


@dataclass
class ProactiveMessage:
    trigger_id: str
    priority: Priority
    title: str
    body: str
    action: str = ""           # optional action button label
    action_payload: dict = field(default_factory=dict)
    sdui: dict | None = None   # optional GenUI card
    voice_text: str = ""       # what to say aloud
    timestamp: float = field(default_factory=time.time)


@dataclass
class TriggerState:
    last_fired: float = 0.0
    fire_count: int = 0
    dismiss_count: int = 0
    cooldown_s: float = 300.0  # 5 min default


class ProactiveEngine:
    """Continuously evaluates ambient context and fires proactive messages.

    Usage:
        engine = ProactiveEngine(perception, memory)
        engine.on_message(my_callback)
        await engine.start()
    """

    def __init__(
        self,
        perception=None,
        memory=None,
        orchestrator=None,
        llm=None,
        check_interval_s: float = 15.0,
    ):
        self._perception = perception
        self._memory = memory
        self._orchestrator = orchestrator
        self._llm = llm
        self._interval = check_interval_s
        self._running = False
        self._callbacks: list[Callable[[ProactiveMessage], Awaitable[None]]] = []
        self._trigger_states: dict[str, TriggerState] = {}
        self._first_interaction_today = True
        self._last_hr_alert = 0.0
        self._last_break_suggestion = 0.0
        self._session_start = time.time()

    def on_message(self, callback: Callable[[ProactiveMessage], Awaitable[None]]):
        self._callbacks.append(callback)

    async def start(self):
        self._running = True
        self._session_start = time.time()
        logger.info("Proactive engine started (interval=%.0fs)", self._interval)
        while self._running:
            await asyncio.sleep(self._interval)
            try:
                await self._evaluate()
            except Exception as e:
                logger.warning("Proactive evaluation error: %s", e)

    def stop(self):
        self._running = False

    def record_dismiss(self, trigger_id: str):
        state = self._trigger_states.setdefault(trigger_id, TriggerState())
        state.dismiss_count += 1
        state.cooldown_s = min(state.cooldown_s * 1.5, 3600)

    async def _evaluate(self):
        """Run all trigger checks against current ambient context."""
        now = time.time()
        messages: list[ProactiveMessage] = []

        # Gather perception frames from all sessions
        frames = []
        if self._perception:
            for sid in list(getattr(self._perception, '_frames', {}).keys()):
                f = self._perception.get_frame(sid)
                if f:
                    frames.append(f)

        # --- Morning Briefing ---
        if self._first_interaction_today:
            hour = time.localtime().tm_hour
            if 5 <= hour <= 11:
                msg = await self._build_morning_briefing()
                if msg:
                    messages.append(msg)
                    self._first_interaction_today = False

        # --- Health Triggers ---
        for frame in frames:
            if frame.heart_rate > 0:
                # Elevated HR
                if frame.heart_rate > 100 and (now - self._last_hr_alert > 300):
                    messages.append(ProactiveMessage(
                        trigger_id="hr_elevated",
                        priority=Priority.IMPORTANT,
                        title="Heart Rate Alert",
                        body=f"Your heart rate is {frame.heart_rate} bpm — that's elevated. You've been {frame.activity_state}. Want to take a short break?",
                        voice_text=f"Hey, I noticed your heart rate jumped to {frame.heart_rate}. Maybe a short break would help?",
                        action="Take a break",
                        action_payload={"smart_home": "set_scene", "scene": "calming"},
                    ))
                    self._last_hr_alert = now

                # Low SpO2
                if 0 < frame.spo2_pct < 94:
                    messages.append(ProactiveMessage(
                        trigger_id="spo2_low",
                        priority=Priority.CRITICAL,
                        title="Low Blood Oxygen",
                        body=f"Your SpO2 is {frame.spo2_pct}%. This is below normal. Please take some deep breaths and consider moving to fresh air.",
                        voice_text=f"Your blood oxygen is at {frame.spo2_pct} percent, which is low. Please take some deep breaths.",
                    ))

        # --- Screen Context Triggers ---
        for frame in frames:
            if frame.scene_description:
                desc_lower = frame.scene_description.lower()
                # Error detection
                if any(w in desc_lower for w in ["error", "exception", "traceback", "failed", "crash"]):
                    if self._can_fire("screen_error"):
                        messages.append(ProactiveMessage(
                            trigger_id="screen_error",
                            priority=Priority.SUGGESTION,
                            title="Error Detected",
                            body="I see an error on your screen. Want me to take a look and help debug it?",
                            voice_text="I noticed an error on your screen. Want me to take a look?",
                            action="Help me debug",
                        ))

        # --- Break Reminder ---
        session_minutes = (now - self._session_start) / 60
        if session_minutes > 90 and (now - self._last_break_suggestion > 1800):
            messages.append(ProactiveMessage(
                trigger_id="break_reminder",
                priority=Priority.SUGGESTION,
                title="Time for a Break",
                body=f"You've been working for {int(session_minutes)} minutes straight. A short break can boost focus by 20%.",
                voice_text=f"You've been at it for about {int(session_minutes)} minutes. How about a quick stretch?",
                action="Remind me in 30 min",
            ))
            self._last_break_suggestion = now

        # --- Deliver Messages ---
        for msg in sorted(messages, key=lambda m: m.priority.value, reverse=True):
            if self._can_fire(msg.trigger_id):
                await self._deliver(msg)
                self._record_fire(msg.trigger_id)

    async def _build_morning_briefing(self) -> ProactiveMessage | None:
        """Build a personalized morning briefing from memory and health data."""
        sections = []

        # Health
        frames = []
        if self._perception:
            for sid in list(getattr(self._perception, '_frames', {}).keys()):
                f = self._perception.get_frame(sid)
                if f and f.heart_rate > 0:
                    frames.append(f)

        if frames:
            f = frames[0]
            sections.append(f"Your resting heart rate is {f.heart_rate} bpm, SpO2 {f.spo2_pct}%.")

        # Recent memory
        if self._memory:
            try:
                recent = self._memory.episode_recent(limit=3, session_id=None)
                if recent:
                    sections.append("Here's what happened recently:")
                    for ep in recent[:2]:
                        sections.append(f"  - {ep.get('summary', '')[:100]}")
            except Exception:
                pass

        if not sections:
            return None

        hour = time.localtime().tm_hour
        greeting = "Good morning" if hour < 12 else "Good afternoon"
        body = f"{greeting}! Here's your briefing:\n\n" + "\n".join(sections)
        voice = f"{greeting}! " + " ".join(sections[:3])

        return ProactiveMessage(
            trigger_id="morning_briefing",
            priority=Priority.IMPORTANT,
            title="Morning Briefing",
            body=body,
            voice_text=voice,
            sdui={
                "type": "Card",
                "children": [
                    {"type": "Text", "value": f"{greeting}, Alex!", "style": "headline"},
                    {"type": "Divider"},
                    *[{"type": "Text", "value": s, "style": "body"} for s in sections],
                ],
            },
        )

    def _can_fire(self, trigger_id: str) -> bool:
        state = self._trigger_states.get(trigger_id)
        if not state:
            return True
        if state.dismiss_count > 5 and state.fire_count > 10:
            return False
        return (time.time() - state.last_fired) >= state.cooldown_s

    def _record_fire(self, trigger_id: str):
        state = self._trigger_states.setdefault(trigger_id, TriggerState())
        state.last_fired = time.time()
        state.fire_count += 1

    async def _deliver(self, msg: ProactiveMessage):
        logger.info("Proactive [%s] %s: %s", msg.priority.name, msg.trigger_id, msg.title)
        for cb in self._callbacks:
            try:
                await cb(msg)
            except Exception as e:
                logger.warning("Proactive delivery error: %s", e)
