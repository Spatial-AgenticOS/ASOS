"""
FERAL Timeline API — Chronological life view
"""
from __future__ import annotations

import time
from fastapi import APIRouter, Query

from api.state import state

router = APIRouter()


@router.get("/api/timeline")
async def get_timeline(
    days: int = Query(7, ge=1, le=90),
    type: str = Query("all"),
):
    """Return a chronological feed of memories, health, screen, and events."""
    entries = []
    since_ts = time.time() - (days * 86400)

    if type in ("all", "memories"):
        try:
            memories = state.memory.search("", limit=100)
            for m in memories:
                ts = m.get("timestamp") or m.get("created_at", 0)
                if isinstance(ts, str):
                    try:
                        from datetime import datetime
                        ts = datetime.fromisoformat(ts).timestamp()
                    except Exception:
                        ts = 0
                if ts >= since_ts:
                    entries.append({
                        "type": "memory",
                        "timestamp": ts,
                        "title": m.get("summary", "Memory"),
                        "content": m.get("content", m.get("summary", "")),
                        "metadata": m.get("metadata", {}),
                    })
        except Exception:
            pass

    if type in ("all", "health") and state.health_aggregator:
        try:
            trend = await state.health_aggregator.get_sleep_trend(days=days)
            for entry in (trend if isinstance(trend, list) else []):
                entries.append({
                    "type": "health",
                    "timestamp": entry.get("timestamp", time.time()),
                    "title": "Sleep",
                    "content": f"{entry.get('hours', '?')}h sleep, quality {entry.get('quality', '?')}",
                    "metadata": entry,
                })
        except Exception:
            pass

    if type in ("all", "events") and state.calendar:
        try:
            events = await state.calendar.execute("list_events", {"days_ahead": days})
            for ev in events.get("events", []):
                entries.append({
                    "type": "event",
                    "timestamp": ev.get("start_epoch", time.time()),
                    "title": ev.get("summary", "Event"),
                    "content": ev.get("description", ""),
                    "metadata": ev,
                })
        except Exception:
            pass

    entries.sort(key=lambda e: e.get("timestamp", 0))
    return {"entries": entries, "count": len(entries), "days": days}


@router.get("/api/digital-twin/ask")
async def digital_twin_ask(question: str = Query(...)):
    """Ask the digital twin a question."""
    if not state.digital_twin:
        return {"error": "Digital twin not initialized", "answer": ""}
    try:
        answer = await state.digital_twin.ask(question)
        return {"answer": answer, "question": question}
    except Exception as e:
        return {"error": str(e), "answer": ""}


@router.get("/api/automations")
async def list_automations():
    """List user-created automations."""
    try:
        jobs = state.scheduler.list_automations()
        return {"automations": [
            {
                "id": j.id,
                "description": j.description,
                "cron": j.cron_expr,
                "enabled": j.enabled,
                "next_run": j.next_run,
                "run_count": j.run_count,
            }
            for j in jobs
        ]}
    except Exception as e:
        return {"automations": [], "error": str(e)}


@router.post("/api/automations")
async def create_automation(body: dict):
    """Create an automation from natural language."""
    text = body.get("text", "")
    session_id = body.get("session_id", "web")
    if not text:
        return {"error": "text is required"}
    try:
        job = state.scheduler.create_from_natural_language(text, session_id)
        return {"success": True, "job_id": job.id, "cron": job.cron_expr, "description": job.description}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.delete("/api/automations/{job_id}")
async def delete_automation(job_id: int):
    """Delete a user automation."""
    try:
        state.scheduler.delete_automation(job_id)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/health-summary")
async def health_summary():
    """Aggregated health data from all connected platforms."""
    if not state.health_aggregator:
        return {"error": "No health platforms connected", "data": {}}
    try:
        data = await state.health_aggregator.get_health_summary()
        return {"data": data}
    except Exception as e:
        return {"error": str(e), "data": {}}


@router.post("/api/location/update")
async def update_location(body: dict):
    """Update user's location from phone bridge."""
    if not state.location_engine:
        return {"error": "Location engine not initialized"}
    lat = body.get("lat")
    lon = body.get("lon")
    if lat is None or lon is None:
        return {"error": "lat and lon required"}
    try:
        triggered = state.location_engine.update_location(lat, lon, source=body.get("source", "phone"))
        return {"success": True, "triggered_fences": triggered}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/geofences")
async def add_geofence(body: dict):
    """Add a geofence."""
    if not state.location_engine:
        return {"error": "Location engine not initialized"}
    try:
        state.location_engine.add_geofence(
            name=body["name"],
            lat=body["lat"],
            lon=body["lon"],
            radius_m=body.get("radius_m", 200),
            on_enter=body.get("on_enter", ""),
            on_exit=body.get("on_exit", ""),
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/geofences")
async def list_geofences():
    """List all geofences."""
    if not state.location_engine:
        return {"fences": []}
    try:
        fences = state.location_engine.list_geofences()
        return {"fences": [{"name": f.name, "lat": f.center.lat, "lon": f.center.lon, "radius_m": f.radius_m} for f in fences]}
    except Exception as e:
        return {"fences": [], "error": str(e)}


@router.post("/api/push/register")
async def register_push_device(body: dict):
    """Register a device for push notifications."""
    if not state.push_channel:
        return {"error": "Push channel not initialized"}
    try:
        state.push_channel.register_device(
            user_id=body.get("user_id", "default"),
            token=body["token"],
            platform=body.get("platform", "fcm"),
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/push/send")
async def send_push(body: dict):
    """Send a push notification to a user."""
    if not state.push_channel:
        return {"error": "Push channel not initialized"}
    try:
        result = await state.push_channel.broadcast(
            user_id=body.get("user_id", "default"),
            title=body.get("title", "FERAL"),
            body=body.get("body", ""),
            data=body.get("data"),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/autonomy")
async def get_autonomy():
    """Get current autonomy mode."""
    orch = state.orchestrator
    if orch and hasattr(orch, "tool_runner"):
        return {"mode": orch.tool_runner.autonomy_mode}
    return {"mode": "hybrid"}


@router.post("/api/autonomy")
async def set_autonomy(body: dict):
    """Set autonomy mode (strict/hybrid/loose)."""
    mode = body.get("mode", "hybrid")
    if mode not in ("strict", "hybrid", "loose"):
        return {"error": "mode must be strict, hybrid, or loose"}
    orch = state.orchestrator
    if orch and hasattr(orch, "tool_runner"):
        orch.tool_runner.set_autonomy_mode(mode)
        return {"success": True, "mode": mode}
    return {"error": "Orchestrator not ready"}
