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
import json
import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
        calendar=None,
        health_aggregator=None,
        baseline_engine=None,
        check_interval_s: float = 15.0,
        config: dict | None = None,
    ):
        self._perception = perception
        self._memory = memory
        self._orchestrator = orchestrator
        self._llm = llm
        self._calendar = calendar
        self._health = health_aggregator
        self._baseline = baseline_engine
        self._interval = check_interval_s
        self._running = False
        self._callbacks: list[Callable[[ProactiveMessage], Awaitable[None]]] = []
        self._trigger_states: dict[str, TriggerState] = {}
        self._trigger_counts: dict[str, int] = defaultdict(int)
        self._first_interaction_today = True
        self._last_hr_alert = 0.0
        self._last_break_suggestion = 0.0
        self._last_llm_eval = 0.0
        self._session_start = time.time()

        cfg = config or {}
        features = cfg.get("features", {})
        self._nag_cooldown_s = float(features.get("proactive_nag_cooldown_s", 300))

    def on_message(self, callback: Callable[[ProactiveMessage], Awaitable[None]]):
        self._callbacks.append(callback)

    def stats(self) -> dict:
        """Per-trigger fire counts and current cooldown state."""
        return {
            "trigger_counts": dict(self._trigger_counts),
            "trigger_states": {
                tid: {"fire_count": s.fire_count, "dismiss_count": s.dismiss_count, "cooldown_s": s.cooldown_s}
                for tid, s in self._trigger_states.items()
            },
            "nag_cooldown_s": self._nag_cooldown_s,
            "running": self._running,
        }

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

    async def evaluate(self, session_id: str = ""):
        """Public entry point for on-demand evaluation."""
        await self._evaluate()

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
                if frame.heart_rate > 100 and self._can_fire("hr_elevated"):
                    messages.append(ProactiveMessage(
                        trigger_id="hr_elevated",
                        priority=Priority.IMPORTANT,
                        title="Heart Rate Alert",
                        body=f"Your heart rate is {frame.heart_rate} bpm — that's elevated. You've been {frame.activity_state}. Want to take a short break?",
                        voice_text=f"Hey, I noticed your heart rate jumped to {frame.heart_rate}. Maybe a short break would help?",
                        action="Take a break",
                        action_payload={"smart_home": "set_scene", "scene": "calming"},
                    ))

                # Low SpO2
                if 0 < frame.spo2_pct < 94 and self._can_fire("spo2_low"):
                    messages.append(ProactiveMessage(
                        trigger_id="spo2_low",
                        priority=Priority.CRITICAL,
                        title="Low Blood Oxygen",
                        body=f"Your SpO2 is {frame.spo2_pct}%. This is below normal. Please take some deep breaths and consider moving to fresh air.",
                        voice_text=f"Your blood oxygen is at {frame.spo2_pct} percent, which is low. Please take some deep breaths.",
                        action="Start breathing exercise",
                        action_payload={"smart_home": "breathing_exercise", "duration_minutes": 3},
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

        # --- Sleep Trend Check ---
        if self._health and self._can_fire("sleep_declining"):
            try:
                trend = await self._health.get_sleep_trend(days=3)
                if len(trend) >= 3:
                    hours = [e.get("total_sleep_hours") or e.get("sleep_score") for e in trend[-3:]]
                    hours = [h for h in hours if h is not None]
                    if len(hours) >= 3 and hours[-1] < hours[-2] < hours[-3]:
                        hr_str = ", ".join(f"{h:.1f}h" if isinstance(h, float) else str(h) for h in hours)
                        messages.append(ProactiveMessage(
                            trigger_id="sleep_declining",
                            priority=Priority.SUGGESTION,
                            title="Sleep Trend Declining",
                            body=f"Your sleep has been declining — {hr_str}. Want to set up a wind-down routine?",
                            voice_text="I noticed your sleep has been trending down the last few nights. Want to set up a wind-down routine?",
                            action="Set up routine",
                        ))
            except Exception as e:
                logger.debug("Sleep trend check failed: %s", e)

        # --- Productivity Coaching ---
        if session_minutes > 90 and self._can_fire("focus_break"):
            same_app = False
            for frame in frames:
                if frame.scene_description:
                    same_app = True
                    break
            if same_app:
                messages.append(ProactiveMessage(
                    trigger_id="focus_break",
                    priority=Priority.SUGGESTION,
                    title="Focus Break",
                    body=f"You've been focused for {int(session_minutes)}m. A 5-minute break improves sustained performance.",
                    voice_text=f"You've been locked in for {int(session_minutes)} minutes. A short break will help you stay sharp.",
                    action="Take 5 min",
                ))

        # --- Meeting Prep ---
        if self._calendar and self._can_fire("meeting_prep"):
            try:
                result = await self._calendar.next_event()
                if result.get("success") and result.get("data"):
                    ev = result["data"]
                    start_str = ev.get("start", "")
                    title = ev.get("summary", "Untitled")
                    if start_str and "No upcoming" not in str(ev.get("message", "")):
                        try:
                            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                            minutes_until = (start_dt - datetime.now(timezone.utc)).total_seconds() / 60
                            if 0 < minutes_until < 15:
                                messages.append(ProactiveMessage(
                                    trigger_id="meeting_prep",
                                    priority=Priority.IMPORTANT,
                                    title="Meeting Soon",
                                    body=f"Meeting '{title}' in {int(minutes_until)} minutes. Want a quick briefing on related context?",
                                    voice_text=f"You have '{title}' coming up in {int(minutes_until)} minutes. Want me to prep a quick briefing?",
                                    action="Brief me",
                                    action_payload={"event": ev},
                                ))
                        except (ValueError, TypeError):
                            pass
            except Exception as e:
                logger.debug("Meeting prep check failed: %s", e)

        # --- Baseline Anomaly Detection ---
        if self._baseline:
            try:
                for frame in frames:
                    if frame.heart_rate > 0:
                        alert = self._baseline.check_anomaly(
                            "hr_resting", frame.heart_rate
                        )
                        if alert and self._can_fire("baseline_hr"):
                            messages.append(ProactiveMessage(
                                trigger_id="baseline_hr",
                                priority=Priority.IMPORTANT,
                                title="Heart Rate Anomaly",
                                body=alert.message,
                                voice_text=alert.message,
                            ))
                for mid in ("sleep_hours", "hrv_ms"):
                    trend_alert = self._baseline.check_trend(mid)
                    if trend_alert and self._can_fire(f"baseline_trend_{mid}"):
                        messages.append(ProactiveMessage(
                            trigger_id=f"baseline_trend_{mid}",
                            priority=Priority.SUGGESTION,
                            title="Trend Detected",
                            body=trend_alert.message,
                            voice_text=trend_alert.message,
                        ))
            except Exception as e:
                logger.debug("Baseline check failed: %s", e)

        # --- LLM-based evaluation (additive, runs last) ---
        await self._evaluate_with_llm(frames, messages)

        # --- Deliver Messages ---
        for msg in sorted(messages, key=lambda m: m.priority.value, reverse=True):
            if self._can_fire(msg.trigger_id):
                await self._deliver(msg)
                self._record_fire(msg.trigger_id)

    async def _evaluate_with_llm(self, frames: list, existing_triggers: list[ProactiveMessage]):
        """Ask the LLM whether FERAL should proactively say something.

        Only called when an LLM client is configured and enough time has
        elapsed since the last LLM evaluation (60s cooldown).  Results are
        appended to *existing_triggers* — they don't replace rule-based ones.
        """
        if not self._llm:
            return

        now = time.time()
        if now - self._last_llm_eval < 60:
            return
        self._last_llm_eval = now

        frame_summaries = []
        for frame in frames[:3]:
            frame_summaries.append(frame.to_system_context())

        recent_trigger_ids = [m.trigger_id for m in existing_triggers[:5]]

        prompt = (
            "You are FERAL's proactive intelligence layer. Given the current "
            "perception context and recent rule-based triggers, decide if FERAL "
            "should proactively say something ADDITIONAL.\n\n"
            f"Perception frames:\n{chr(10).join(frame_summaries) or 'No sensor data.'}\n\n"
            f"Already-triggered rules: {recent_trigger_ids or 'none'}\n\n"
            "If you think FERAL should speak up, return ONLY valid JSON:\n"
            '{"trigger_id": "llm_<topic>", "priority": "SUGGESTION"|"IMPORTANT", '
            '"title": "...", "body": "...", "action": "..."}\n\n'
            "If nothing useful to add, return exactly: null"
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
            text = ""
            if isinstance(response, dict):
                text = response.get("content", "") or response.get("text", "")
            elif isinstance(response, str):
                text = response
            else:
                text = str(response)

            text = text.strip()
            if not text or text == "null":
                return

            data = json.loads(text)
            if not isinstance(data, dict) or "trigger_id" not in data:
                return

            priority_str = data.get("priority", "SUGGESTION").upper()
            priority = Priority[priority_str] if priority_str in Priority.__members__ else Priority.SUGGESTION

            existing_triggers.append(ProactiveMessage(
                trigger_id=data["trigger_id"],
                priority=priority,
                title=data.get("title", "FERAL Insight"),
                body=data.get("body", ""),
                voice_text=data.get("body", ""),
                action=data.get("action", ""),
            ))
            logger.info("LLM proactive trigger: %s", data["trigger_id"])

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("LLM eval returned non-JSON: %s", e)
        except Exception as e:
            logger.warning("LLM proactive evaluation failed: %s", e)

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
        state = self._trigger_states.setdefault(trigger_id, TriggerState(cooldown_s=self._nag_cooldown_s))
        state.last_fired = time.time()
        state.fire_count += 1
        self._trigger_counts[trigger_id] += 1

    async def _deliver(self, msg: ProactiveMessage):
        logger.info("Proactive [%s] %s: %s", msg.priority.name, msg.trigger_id, msg.title)

        if msg.action_payload:
            await self._execute_automation(msg)

        for cb in self._callbacks:
            try:
                await cb(msg)
            except Exception as e:
                logger.warning("Proactive delivery error: %s", e)

    async def _execute_automation(self, msg: ProactiveMessage):
        """Execute smart home / automation actions attached to proactive alerts."""
        if not self._orchestrator:
            return

        payload = msg.action_payload
        action_type = payload.get("smart_home") or payload.get("action_type")
        if not action_type:
            return

        try:
            from skills.impl import get_implementation

            if action_type == "set_scene":
                scene = payload.get("scene", "calming")
                impl = get_implementation("smart_home_hue")
                if impl:
                    await impl.execute("set_scene", {"scene": scene}, {})
                logger.info("Automation executed: set_scene=%s (trigger=%s)", scene, msg.trigger_id)

            elif action_type == "breathing_exercise":
                duration = payload.get("duration_minutes", 3)
                impl = get_implementation("smart_home_hue")
                if impl:
                    await impl.execute("set_scene", {"scene": "breathing"}, {})
                logger.info("Automation executed: breathing exercise %dmin (trigger=%s)", duration, msg.trigger_id)

            elif action_type == "notification":
                logger.info("Automation: notification-only for trigger=%s", msg.trigger_id)

        except Exception as e:
            logger.warning("Automation execution failed for %s: %s", msg.trigger_id, e)
