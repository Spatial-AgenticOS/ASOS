"""REST routes for the Supervisor / Oversight surface.

Exposes:
  * GET    /api/supervisor/events?limit=&source=&actor=&decision=
  * GET    /api/supervisor/stats
  * POST   /api/supervisor/pause    {paused: bool}
  * POST   /api/supervisor/record   — explicit record for non-orchestrator
                                       sources (twin, proactive, cron, …)

The v2 /oversight page reads the first two, toggles the kill-switch via
the third, and the digital-twin engine (Commit 7) uses the fourth.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.state import state

router = APIRouter(tags=["supervisor"])


def _require_supervisor():
    sup = getattr(state, "supervisor", None)
    if sup is None:
        raise HTTPException(status_code=503, detail="Supervisor not initialised")
    return sup


@router.get("/api/supervisor/events")
async def get_events(
    limit: int = 50,
    source: str = "",
    actor: str = "",
    decision: str = "",
):
    sup = _require_supervisor()
    events = sup.recent(limit=limit, source=source, actor=actor, decision=decision)
    return {"count": len(events), "events": events}


@router.get("/api/supervisor/stats")
async def get_stats():
    sup = _require_supervisor()
    return sup.stats()


@router.post("/api/supervisor/pause")
async def set_paused(body: dict):
    sup = _require_supervisor()
    paused = bool((body or {}).get("paused", False))
    sup.set_paused(paused)
    return {"paused": sup.paused}


@router.post("/api/supervisor/record")
async def record(body: dict):
    """Record a supervisor event for a non-orchestrator source.

    Body shape: ``{source, kind, session_id?, actor?, payload?, decision?,
    detail?}``. Useful for cron, proactive, twin, channels — anything that
    bypasses the wrapped orchestrator entry points.
    """
    body = body or {}
    source = body.get("source")
    kind = body.get("kind")
    if not source or not kind:
        raise HTTPException(status_code=400, detail="source and kind required")
    sup = _require_supervisor()
    ev = sup.record(
        source=source,
        kind=kind,
        session_id=body.get("session_id", ""),
        actor=body.get("actor", "system"),
        payload=body.get("payload"),
        decision=body.get("decision", "allowed"),
        detail=body.get("detail") or {},
    )
    return {"success": True, "event_id": ev.event_id}
