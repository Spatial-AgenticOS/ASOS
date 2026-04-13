"""Cross-device session handoff REST endpoints."""

from fastapi import APIRouter, Request

from api.state import state

router = APIRouter()


@router.post("/api/handoff")
async def initiate_handoff(request: Request):
    """Initiate a handoff from one session to another device class (e.g. phone → desktop)."""
    body = await request.json()
    from_session = body.get("from_session", "")
    to_node_type = body.get("to_node_type", "desktop")
    history_depth = int(body.get("history_depth", 20))

    if not state.session_handoff:
        return {"ok": False, "error": "Session handoff manager not available"}

    result = await state.session_handoff.handoff(
        from_session, to_node_type, history_depth=history_depth,
    )
    return {"ok": bool(result.get("success")), **result}


@router.get("/api/handoff/devices")
async def handoff_devices():
    """List connected WebSocket sessions that can receive a handoff, with device types."""
    if not state.session_handoff:
        return {"devices": []}
    return {"devices": state.session_handoff.get_active_devices()}
