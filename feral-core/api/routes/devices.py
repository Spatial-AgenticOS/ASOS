"""Device mesh, session handoff, command ledger, node health, and pairing endpoints."""

import io
import json
import socket

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.state import state

router = APIRouter()


def _infer_node_type(node_id: str, ws) -> str:
    """Pick the most honest node_type label for a connected daemon.

    Priority:
    1. ``ws._feral_node_type`` — set at ``node_register`` time from the
       HUP payload. This is the authoritative source.
    2. ``state.skill_executor._daemon_types[node_id]`` — a mirror set at
       the same moment; used as fallback if the ws attr is missing for
       any reason.
    3. A node_id prefix heuristic (``feral-w300-*`` → glasses,
       ``feral-wristband-*`` → wearable). Last-resort.
    4. ``"unknown"`` when nothing else fits. We never silently label
       something "phone" again.
    """
    declared = getattr(ws, "_feral_node_type", None)
    if declared:
        return declared
    if state.skill_executor is not None:
        mirror = getattr(state.skill_executor, "_daemon_types", {}).get(node_id)
        if mirror:
            return str(mirror).lower()
    low = (node_id or "").lower()
    if "glasses" in low or "w300" in low:
        return "glasses"
    if "wristband" in low or "watch" in low:
        return "wearable"
    if "browser" in low and "camera" in low:
        return "browser_camera"
    if "browser" in low:
        return "browser_node"
    # "phone" label is only reserved for daemons that explicitly declared
    # it at register time (handled above via ws._feral_node_type). A
    # substring heuristic was mislabelling random node_ids + making the UI
    # show a phone that didn't exist.
    if "robot" in low:
        return "robot"
    return "unknown"


def _describe_device(node_id: str, ws) -> dict:
    return {
        "node_id": node_id,
        "type": _infer_node_type(node_id, ws),
        "capabilities": list(getattr(ws, "_feral_capabilities", []) or []),
        "platform": getattr(ws, "_feral_platform", "") or "",
        "manufacturer": getattr(ws, "_feral_manufacturer", "") or "",
        "model": getattr(ws, "_feral_model", "") or "",
        "status": "connected",
    }


@router.get("/api/devices/connected")
async def connected_devices():
    """List all connected HUP daemons with their real node_type.

    No more fake ``"desktop"`` / ``"phone"`` placeholders — every entry
    corresponds to a live WebSocket in ``state.daemons``. Empty list is
    a valid answer and means "nothing is paired yet", not "we made one up".
    """
    if state.session_handoff:
        active = state.session_handoff.get_active_devices() or []
        # Trust the session_handoff view when it exists but sanity-check
        # the 'type' field isn't a hardcoded "phone" default.
        cleaned = []
        for d in active:
            if isinstance(d, dict):
                # If the upstream handoff code returned an opaque type we
                # prefer, keep it; otherwise fall back to our inference.
                if not d.get("type") or d.get("type") == "phone":
                    ws = state.daemons.get(d.get("node_id", ""))
                    if ws is not None:
                        d = {**d, "type": _infer_node_type(d.get("node_id", ""), ws)}
            cleaned.append(d)
        return {"devices": cleaned}

    return {
        "devices": [
            _describe_device(nid, ws) for nid, ws in state.daemons.items()
        ]
    }


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
    """List all paired edge-node devices — with typed metadata."""
    store = state.device_pairing_store
    devices = store.list_devices()
    safe = [
        {
            "device_id": d["device_id"],
            "name": d["name"],
            "paired_at": d["paired_at"],
            "last_seen": d["last_seen"],
            "kind": d.get("kind", ""),
            "node_id": d.get("node_id", ""),
            "claimed_at": d.get("claimed_at"),
            "platform": d.get("platform", ""),
            "capabilities": d.get("capabilities", []),
        }
        for d in devices
    ]
    return {"devices": safe}


@router.post("/api/devices/pair")
async def pair_device(request: Request):
    """Pair a new edge-node device.

    Typed body — every pairing flow goes through this endpoint:

        {"kind": "name"}                    — label-only pair, generic QR
        {"kind": "hup", "node_id": "...",   — daemon / node SDK pair, declares
         "capabilities": [...] }              its node_id + capabilities up front
        {"kind": "browser",                 — browser-Node pair (Pair page)
         "platform": "...",                   includes user-agent hint
         "capabilities": [...] }

    All kinds accept an optional ``name`` label. Legacy body {name: ...}
    without ``kind`` is still honoured (falls back to kind="name").

    Returns the pairing record — token is included exactly once; clients
    must store it immediately because it won't be returned again.
    """
    body = await request.json() if await request.body() else {}
    name = body.get("name", "unnamed")
    kind = (body.get("kind") or "name").lower()
    if kind not in {"name", "hup", "browser"}:
        raise HTTPException(status_code=400, detail=f"unknown pair kind: {kind}")
    node_id = body.get("node_id") or ""
    platform = body.get("platform") or ""
    capabilities = body.get("capabilities") or []
    if not isinstance(capabilities, list):
        raise HTTPException(status_code=400, detail="capabilities must be a list")

    store = state.device_pairing_store
    if not store:
        raise HTTPException(status_code=503, detail="Pairing store not initialized")

    return store.pair_device(
        name,
        kind=kind,
        node_id=node_id,
        platform=platform,
        capabilities=capabilities,
    )


def _pair_payload(result: dict, *, mode: str, request_origin: str = "") -> dict:
    """Build the JSON encoded into the pair QR.

    When ``mode="app"`` we emit the historical shape:
        {host, port, token, name}  — parsed by the native iOS / Android app.
    When ``mode="web"`` we emit a single pair URL that a plain phone camera
    can scan without any app installed:
        {url: "<origin>/pair?t=<token>"}
    """
    if mode == "web":
        origin = request_origin or ""
        if not origin:
            hostname = socket.gethostname()
            try:
                ip = socket.gethostbyname(hostname)
            except OSError:
                ip = "127.0.0.1"
            origin = f"http://{ip}:9090"
        return {
            "mode": "web",
            "url": f"{origin.rstrip('/')}/pair?t={result['token']}",
            "token": result["token"],
            "device_id": result["device_id"],
        }
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except OSError:
        ip = "127.0.0.1"
    port = 9090
    return {
        "mode": "app",
        "host": ip,
        "port": port,
        "token": result["token"],
        "name": "FERAL Brain",
    }


@router.get("/api/devices/pair/qr")
async def pair_device_qr(request: Request, name: str = "unnamed", mode: str = "app"):
    """Generate a QR code PNG for a new device.

    ``mode=app`` (default) encodes ``{host, port, token, name}`` JSON for
    the native iOS / Android app. ``mode=web`` encodes ``<origin>/pair?t=<token>``
    so ANY phone camera app can scan it and land on the browser-side pairing
    page — no app install required.
    """
    store = state.device_pairing_store
    if not store:
        raise HTTPException(status_code=503, detail="Pairing store not initialized")
    if mode not in {"app", "web"}:
        raise HTTPException(status_code=400, detail="mode must be 'app' or 'web'")

    kind = "browser" if mode == "web" else "name"
    result = store.pair_device(name, kind=kind)

    origin = str(request.base_url).rstrip("/")
    payload = _pair_payload(result, mode=mode, request_origin=origin)
    encoded = json.dumps(payload) if mode == "app" else payload["url"]

    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(encoded)
        qr.make(fit=True)
        img = qr.make_image(fill_color="white", back_color="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")
    except ImportError:
        return {
            "pairing_info": payload,
            "note": "Install qrcode package for QR image",
        }


@router.get("/api/devices/pair/url")
async def pair_device_url(request: Request, name: str = "unnamed"):
    """Return the web-pair URL + token WITHOUT an image — handy for tests
    and for the ``/pair`` landing page needing the token to render."""
    store = state.device_pairing_store
    if not store:
        raise HTTPException(status_code=503, detail="Pairing store not initialized")
    result = store.pair_device(name, kind="browser")
    origin = str(request.base_url).rstrip("/")
    return _pair_payload(result, mode="web", request_origin=origin)


@router.post("/api/devices/pair/complete")
async def pair_device_complete(body: dict):
    """Mark a pairing token as claimed by the device that just attached.

    Called by BrowserNode.js the moment its WebSocket register succeeds;
    the UI on the brain-side then shows "device connected" instead of
    "token issued, no attach yet".
    """
    token = (body or {}).get("token") or ""
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    store = state.device_pairing_store
    if not store:
        raise HTTPException(status_code=503, detail="Pairing store not initialized")
    device_id = store.mark_claimed(token)
    if device_id is None:
        raise HTTPException(status_code=404, detail="unknown pairing token")
    return {"success": True, "device_id": device_id}


@router.delete("/api/devices/{device_id}")
async def revoke_device(device_id: str):
    """Revoke (un-pair) a device."""
    store = state.device_pairing_store
    ok = store.revoke_device(device_id)
    if not ok:
        return {"ok": False, "error": "device not found"}
    return {"ok": True}
