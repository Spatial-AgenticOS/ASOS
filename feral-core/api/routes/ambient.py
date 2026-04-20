"""Ambient surface API — briefing, next event, snapshot, wind-down, wake-word."""

import logging
import os
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from api.state import state

router = APIRouter(prefix="/api/ambient", tags=["ambient"])
logger = logging.getLogger("feral.ambient")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _outfit_from_temp(t: float) -> str:
    if t < 5:
        return "heavy coat, scarf, gloves"
    elif t < 15:
        return "jacket, long sleeves"
    elif t < 22:
        return "light layer"
    return "t-shirt, sunscreen"


# ── Briefing ─────────────────────────────────────────────────────────────────

@router.get("/briefing")
async def get_briefing():
    """Morning briefing: sleep recap, today's agenda, weather, goals."""
    if not state.orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")

    briefing: dict = {
        "greeting": "",
        "sleep": None,
        "agenda": [],
        "weather": None,
        "goals": [],
        "vip_emails": [],
    }

    try:
        if state.baseline_engine:
            metrics = state.baseline_engine.get_all_baselines()
            hrv = next((m for m in metrics if m.get("metric") == "hrv_ms"), None)
            if hrv:
                briefing["sleep"] = {
                    "hrv_ms": hrv.get("value"),
                    "trend": hrv.get("trend", "stable"),
                }
    except Exception as e:
        logger.debug("sleep recap unavailable: %s", e)

    try:
        if hasattr(state, "intent_compiler") and state.intent_compiler:
            today = state.intent_compiler.today()
            briefing["agenda"] = today.get("actions", [])[:3]
    except Exception as e:
        logger.debug("agenda unavailable: %s", e)

    try:
        if hasattr(state, "intent_compiler") and state.intent_compiler:
            plans = state.intent_compiler.list_active()
            briefing["goals"] = [
                {"id": p["id"], "title": p.get("goal", ""), "progress": p.get("progress", 0)}
                for p in plans[:3]
            ]
    except Exception as e:
        logger.debug("goals unavailable: %s", e)

    try:
        if hasattr(state, "email_watcher") and state.email_watcher:
            if hasattr(state.email_watcher, "get_recent_vip"):
                briefing["vip_emails"] = state.email_watcher.get_recent_vip(limit=3)
    except Exception as e:
        logger.debug("vip emails unavailable: %s", e)

    # Weather (optional — requires OPENWEATHER_API_KEY). Vault uses
    # ``retrieve(key_name)`` — there is no ``get`` method — so we fall through
    # to an env lookup + vault retrieve without tripping AttributeError when
    # the key is absent.
    ow_key = os.environ.get("OPENWEATHER_API_KEY") or ""
    if not ow_key and hasattr(state, "vault") and state.vault:
        try:
            ow_key = state.vault.retrieve("OPENWEATHER_API_KEY") or ""
        except Exception:
            ow_key = ""
    if ow_key:
        try:
            import httpx

            lat = os.environ.get("FERAL_USER_LAT", "40.7128")
            lng = os.environ.get("FERAL_USER_LNG", "-74.0060")
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"https://api.openweathermap.org/data/2.5/weather"
                    f"?lat={lat}&lon={lng}&appid={ow_key}&units=metric"
                )
                if r.status_code == 200:
                    data = r.json()
                    briefing["weather"] = {
                        "temp_c": data["main"]["temp"],
                        "feels_like_c": data["main"]["feels_like"],
                        "condition": data["weather"][0]["main"],
                        "description": data["weather"][0]["description"],
                        "outfit_hint": _outfit_from_temp(data["main"]["feels_like"]),
                    }
        except Exception as e:
            logger.debug("weather unavailable: %s", e)

    now = datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        briefing["greeting"] = "Good morning"
    elif 12 <= hour < 17:
        briefing["greeting"] = "Good afternoon"
    else:
        briefing["greeting"] = "Good evening"

    return briefing


# ── Next event ───────────────────────────────────────────────────────────────

@router.get("/next_event")
async def get_next_event():
    """Return the next calendar event from the integrated calendar service."""
    try:
        if state.skill_registry:
            cal_skill = state.skill_registry.skills.get(
                "calendar_lookup"
            ) or state.skill_registry.skills.get("google_calendar")
            if cal_skill and hasattr(cal_skill, "execute"):
                result = await cal_skill.execute("next_event", {}, {})
                if result.get("success") and result.get("data"):
                    return result["data"]
    except Exception as e:
        logger.debug("next_event lookup failed: %s", e)

    return {"event": None, "hint": "Connect Google Calendar via Settings > Integrations"}


# ── Snapshot ─────────────────────────────────────────────────────────────────

@router.get("/snapshot")
async def get_snapshot():
    """Minimal ambient snapshot: time, vitals, greeting, mode suggestion."""
    now = datetime.now()
    hour = now.hour

    if 5 <= hour < 9:
        suggested_mode = "briefing"
    elif 9 <= hour < 19:
        suggested_mode = "desk"
    else:
        suggested_mode = "wind_down"

    vitals = {}
    try:
        if state.perception and state.sessions:
            for sid in state.sessions:
                frame = state.perception.get_frame(sid)
                if frame:
                    vitals = {
                        "heart_rate": getattr(frame, "heart_rate", 0),
                        "spo2": getattr(frame, "spo2_pct", 0),
                        "skin_temperature_c": getattr(frame, "skin_temperature_c", 0),
                        "battery_pct": getattr(frame, "battery_pct", 100),
                    }
                    break
    except Exception as e:
        logger.debug("vitals snapshot failed: %s", e)

    return {
        "time": now.isoformat(),
        "suggested_mode": suggested_mode,
        "vitals": vitals,
    }


# ── Wind-Down ────────────────────────────────────────────────────────────────

_JOURNAL_PROMPTS = [
    "What did you learn today?",
    "What went well?",
    "What's one thing you're grateful for?",
    "What do you want to carry forward?",
]


@router.get("/wind_down")
async def get_wind_down():
    """Evening wind-down: day recap, sleep prep, memory highlights."""
    day_recap: dict = {
        "completed_tasks": [],
        "active_durations_s": 0,
        "key_episodes": [],
    }

    try:
        if hasattr(state, "intent_compiler") and state.intent_compiler:
            if hasattr(state.intent_compiler, "get_completed_today"):
                day_recap["completed_tasks"] = state.intent_compiler.get_completed_today()
    except Exception as e:
        logger.debug("day recap unavailable: %s", e)

    episodes: list = []
    try:
        if hasattr(state, "memory") and state.memory:
            recent = state.memory.episode_recent(limit=10) or []
            today = datetime.now().date()
            episodes = [
                e for e in recent
                if datetime.fromisoformat(e.get("ts", "1970-01-01")).date() == today
            ][:2]
    except Exception as e:
        logger.debug("episodes unavailable: %s", e)

    now = datetime.now()
    bedtime = now.replace(hour=23, minute=0, second=0, microsecond=0)
    if now > bedtime:
        bedtime += timedelta(days=1)
    time_to_bed_min = max(0, int((bedtime - now).total_seconds() / 60))

    hints = [
        "Dim the lights" if time_to_bed_min < 60 else "Plan tomorrow",
    ]
    if time_to_bed_min < 30:
        hints.append("Avoid screens soon")

    sleep_prep = {
        "time_to_bed_min": time_to_bed_min,
        "hints": hints,
    }

    return {
        "day_recap": day_recap,
        "episodes": [
            {"id": e.get("id"), "summary": (e.get("summary") or e.get("content", ""))[:100]}
            for e in episodes
        ],
        "sleep_prep": sleep_prep,
        "journal_prompt": random.choice(_JOURNAL_PROMPTS),
    }


# ── Wake-Word ────────────────────────────────────────────────────────────────

@router.get("/wake_word/status")
async def wake_word_status():
    """Returns current wake-word detector status."""
    if not hasattr(state, "wake_word") or not state.wake_word:
        return {"enabled": False, "supported": False}
    return {
        "enabled": getattr(state.wake_word, "enabled", False),
        "phrase": getattr(state.wake_word, "phrase", "hey feral"),
        "supported": True,
    }


@router.post("/wake_word/toggle")
async def toggle_wake_word():
    """Toggle the wake-word detector on/off."""
    if not hasattr(state, "wake_word") or not state.wake_word:
        raise HTTPException(503, "Wake word detector not initialized")
    state.wake_word.enabled = not state.wake_word.enabled
    return {"enabled": state.wake_word.enabled}
