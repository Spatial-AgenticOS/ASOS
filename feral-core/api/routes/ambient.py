"""Ambient surface API — briefing, next event, snapshot."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from api.state import state

router = APIRouter(prefix="/api/ambient", tags=["ambient"])
logger = logging.getLogger("feral.ambient")


@router.get("/briefing")
async def get_briefing():
    """Morning briefing: sleep recap, today's agenda, weather, goals."""
    if not state.orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")

    briefing = {
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

    now = datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        briefing["greeting"] = "Good morning"
    elif 12 <= hour < 17:
        briefing["greeting"] = "Good afternoon"
    else:
        briefing["greeting"] = "Good evening"

    return briefing


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
