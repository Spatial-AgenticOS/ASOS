"""Device mesh, session handoff, and proactive alert endpoints."""

from fastapi import APIRouter, Request

from api.state import state

router = APIRouter()


@router.get("/api/devices/connected")
async def connected_devices():
    """List all connected devices with their types and metrics."""
    if state.session_handoff:
        return {"devices": state.session_handoff.get_active_devices()}

    devices = []
    devices.append({"type": "desktop", "session_id": "local", "status": "connected"})
    for nid, ws in state.daemons.items():
        devices.append({"type": "phone", "node_id": nid, "status": "connected"})
    return {"devices": devices}


@router.post("/api/devices/handoff")
async def session_handoff(request: Request):
    """Initiate a session handoff between devices."""
    body = await request.json()
    from_session = body.get("from_session", "")
    to_node_type = body.get("to_node_type", "desktop")

    if not state.session_handoff:
        return {"ok": False, "error": "Session handoff manager not available"}

    success = await state.session_handoff.handoff(from_session, to_node_type)
    return {"ok": success}


@router.post("/api/proactive/dismiss")
async def dismiss_proactive(request: Request):
    """User dismissed a proactive alert — learn from it."""
    body = await request.json()
    trigger_id = body.get("trigger_id", "")
    if state.proactive and trigger_id:
        state.proactive.record_dismiss(trigger_id)
    return {"ok": True}


@router.get("/api/demo/status")
async def demo_status():
    """Check if running in demo mode and get simulator state."""
    demo = getattr(state, "_demo", None)
    if not demo:
        return {"demo": False}
    return {
        "demo": True,
        "wristband": demo.wristband.read(),
        "smart_home": demo.smart_home.state,
    }


@router.post("/api/demo/scenario")
async def run_demo_scenario(request: Request):
    """Start a demo scenario."""
    body = await request.json()
    scenario_name = body.get("scenario", "")
    if not scenario_name:
        from demo.scenarios import SCENARIOS
        return {"available": list(SCENARIOS.keys())}

    try:
        from demo.scenarios import ScenarioRunner
        import asyncio
        runner = ScenarioRunner(brain_state=state)
        asyncio.create_task(runner.run(scenario_name))
        return {"ok": True, "scenario": scenario_name, "status": "started"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
