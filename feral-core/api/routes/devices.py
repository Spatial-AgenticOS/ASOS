"""Device mesh, session handoff, command ledger, node health, and pairing endpoints."""

import io
import json
import socket

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

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

    result = await state.session_handoff.handoff(from_session, to_node_type)
    return {"ok": bool(result.get("success")), **result}


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


# ─────────────────────────────────────────────
# Command Ledger & Node Health endpoints
# ─────────────────────────────────────────────


@router.get("/api/commands/recent")
async def recent_commands(limit: int = 50):
    """Recent commands with full lifecycle state."""
    if not state.hardware_mesh:
        return {"commands": [], "error": "hardware mesh not initialised"}
    records = state.hardware_mesh.ledger.get_recent(limit=limit)
    return {
        "commands": [
            {
                "command_id": r.envelope.command_id,
                "node_id": r.envelope.node_id,
                "action": r.envelope.action,
                "priority": r.envelope.priority,
                "state": r.state.value,
                "created_at": r.envelope.created_at,
                "ack_at": r.ack_at,
                "completed_at": r.completed_at,
                "retries": r.retries,
                "correlation_id": r.envelope.correlation_id,
            }
            for r in records
        ],
        "stats": state.hardware_mesh.ledger.stats(),
    }


@router.get("/api/commands/{command_id}")
async def command_detail(command_id: str):
    """Single command full detail including state history and result."""
    if not state.hardware_mesh:
        return {"error": "hardware mesh not initialised"}
    record = state.hardware_mesh.ledger.get(command_id)
    if record is None:
        return {"error": "command not found"}
    return {
        "command_id": record.envelope.command_id,
        "node_id": record.envelope.node_id,
        "action": record.envelope.action,
        "params": record.envelope.params,
        "priority": record.envelope.priority,
        "state": record.state.value,
        "state_history": record.state_history,
        "created_at": record.envelope.created_at,
        "deadline": record.envelope.deadline,
        "ack_at": record.ack_at,
        "completed_at": record.completed_at,
        "result": record.result,
        "retries": record.retries,
        "idempotency_key": record.envelope.idempotency_key,
        "correlation_id": record.envelope.correlation_id,
    }


@router.get("/api/nodes/health")
async def nodes_health():
    """All node health status with heartbeat freshness."""
    if not state.hardware_mesh:
        return {"nodes": {}, "error": "hardware mesh not initialised"}
    return {"nodes": state.hardware_mesh.node_health.get_all()}


# ─────────────────────────────────────────────
# Device Pairing REST Endpoints
# ─────────────────────────────────────────────


@router.get("/api/devices/paired")
async def list_paired_devices():
    """List all paired edge-node devices."""
    store = state.device_pairing_store
    devices = store.list_devices()
    safe = [
        {
            "device_id": d["device_id"],
            "name": d["name"],
            "paired_at": d["paired_at"],
            "last_seen": d["last_seen"],
        }
        for d in devices
    ]
    return {"devices": safe}


@router.post("/api/devices/pair")
async def pair_device(request: Request):
    """Pair a new edge-node device.  Returns the device token once."""
    body = await request.json()
    name = body.get("name", "unnamed")
    store = state.device_pairing_store
    result = store.pair_device(name)
    return result


@router.get("/api/devices/pair/qr")
async def pair_device_qr(name: str = "phone"):
    """Generate a QR code PNG containing pairing info for a new device."""
    store = state.device_pairing_store
    if not store:
        return {"error": "Pairing store not initialized"}

    result = store.pair_device(name)

    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    port = 9090

    payload = json.dumps({
        "host": ip,
        "port": port,
        "token": result["token"],
        "name": "FERAL Brain",
    })

    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="white", back_color="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")
    except ImportError:
        return {"pairing_info": json.loads(payload), "note": "Install qrcode package for QR image"}


@router.delete("/api/devices/{device_id}")
async def revoke_device(device_id: str):
    """Revoke (un-pair) a device."""
    store = state.device_pairing_store
    ok = store.revoke_device(device_id)
    if not ok:
        return {"ok": False, "error": "device not found"}
    return {"ok": True}
