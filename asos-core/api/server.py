"""
THEORA Brain — Universal Agentic OS Core
==========================================
The local-first agentic brain. Runs on the user's machine.
Clients (phone, web, daemon, glasses, robots) connect via WebSocket.
MCP clients (Claude, Cursor) connect via JSON-RPC.
Channels (Telegram, Discord, Slack) bridge messaging platforms.

v1.2.0 — HUP, MCP server/client, sandbox policies, channels, federated sync, routines, permissions.
"""

import asyncio
import json
import logging
import os
import time
import collections
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, HTMLResponse, FileResponse

from models.protocol import (
    TheoraMessage,
    TextCommandPayload,
    UIEventPayload,
    NodeRegisterPayload,
    SDUIPayload,
    TextResponsePayload,
    DeviceRegisterPayload,
    AudioChunkPayload,
    TranscriptPayload,
    TTSChunkPayload,
    StreamDeltaPayload,
    GesturePayload,
    VisionFramePayload,
    VisionRequestPayload,
    parse_message,
)
from config.loader import theora_home
from config.runtime import brain_bind_host, brain_port, brain_public_base_url
from security.vault import PermissionTier
from security.sandbox_policy import SandboxPolicy
from hardware.protocol import HUPAction, HUPActionType
from gateway.protocol import GatewaySession

from api.state import state, _log_activity, VISION_MAX_FRAME_KB
from api.routes.config import _build_greeting
from api.routes.dashboard import _get_dashboard_data

from api.routes.dashboard import router as dashboard_router
from api.routes.config import router as config_router
from api.routes.skills import router as skills_router
from api.routes.memory import router as memory_router
from api.routes.routines import router as routines_router
from api.routes.taskflows import router as taskflows_router
from api.routes.llm import router as llm_router
from api.routes.genui import router as genui_router
from api.routes.mcp import router as mcp_router
from api.routes.channels import router as channels_router
from api.routes.conversations import router as conversations_router
from api.routes.devices import router as devices_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("theora.brain")


# ─────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────

app = FastAPI(
    title="THEORA Brain",
    description="THEORA — Open AI agent with computer use, GenUI, voice, and hardware control",
    version="1.2.0",
)

CORS_ORIGINS = os.getenv("THEORA_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Rate Limiting Middleware
# ─────────────────────────────────────────────

_rate_limit_store: dict[str, collections.deque] = {}
RATE_LIMIT_RPM = int(os.getenv("THEORA_RATE_LIMIT_RPM", "120"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = _rate_limit_store.setdefault(client_ip, collections.deque())
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_RPM:
            return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
        window.append(now)
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


# ─────────────────────────────────────────────
# Include Route Modules
# ─────────────────────────────────────────────

app.include_router(dashboard_router)
app.include_router(config_router)
app.include_router(skills_router)
app.include_router(memory_router)
app.include_router(routines_router)
app.include_router(taskflows_router)
app.include_router(llm_router)
app.include_router(genui_router)
app.include_router(mcp_router)
app.include_router(channels_router)
app.include_router(conversations_router)
app.include_router(devices_router)


# ─────────────────────────────────────────────
# Security API
# ─────────────────────────────────────────────

@app.get("/api/security/vault")
async def vault_summary():
    """Key names + fingerprints — never raw values."""
    if not state.vault:
        return {"keys": {}}
    return {"keys": state.vault.to_safe_summary()}


@app.post("/api/security/vault/store")
async def vault_store(body: dict):
    """Store a credential in the blind vault."""
    name = body.get("key_name", "")
    value = body.get("value", "")
    if not name or not value:
        return {"error": "key_name and value are required"}
    state.vault.store(name, value, stored_by="api")
    return {"ok": True, "key_name": name, "fingerprint": state.vault.fingerprint(name)}


@app.delete("/api/security/vault/{key_name}")
async def vault_remove(key_name: str):
    removed = state.vault.remove(key_name, removed_by="api")
    return {"ok": removed}


@app.get("/api/security/permissions")
async def get_permissions():
    """Current permission tier and sandbox status."""
    return {
        "max_tier": state.sandbox.max_tier if state.sandbox else "active",
        "tiers": PermissionTier.TIER_ORDER,
        "tier_descriptions": {
            "passive": "Read-only, no side effects (weather, search)",
            "active": "Can send data (messaging, calendar)",
            "privileged": "Can modify system state (file access)",
            "dangerous": "Destructive operations (delete, financial)",
        },
    }


@app.post("/api/security/permissions/update")
async def update_permissions(body: dict):
    new_tier = body.get("max_tier", "active")
    if new_tier not in PermissionTier.TIER_ORDER:
        return {"error": f"Invalid tier: {new_tier}"}
    if state.sandbox:
        state.sandbox.max_tier = new_tier
    return {"ok": True, "max_tier": new_tier}


@app.get("/api/security/audit")
async def get_audit_log():
    """Get recent security audit entries."""
    audit_path = theora_home() / "audit.log"
    if not audit_path.exists():
        return {"entries": []}
    entries = []
    with open(audit_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return {"entries": entries[-100:]}


# ─────────────────────────────────────────────
# Hardware Use Protocol (HUP) API
# ─────────────────────────────────────────────

@app.get("/api/hardware/devices")
async def list_hardware_devices():
    """List all registered hardware devices."""
    if not state.device_registry:
        return {"devices": []}
    devices = state.device_registry.list_devices()
    return {"devices": [d.model_dump() for d in devices]}


@app.get("/api/hardware/device/{device_id}")
async def get_hardware_device(device_id: str):
    if not state.device_registry:
        return {"error": "No device registry"}
    device = state.device_registry.get_device(device_id)
    if not device:
        return {"error": f"Device not found: {device_id}"}
    return device.model_dump()


@app.post("/api/hardware/execute")
async def execute_hardware_action(body: dict):
    """Execute a HUP action on a device."""
    if not state.device_registry:
        return {"error": "No device registry"}
    action = HUPAction(
        device_id=body.get("device_id", ""),
        capability_id=body.get("capability_id", ""),
        action_type=HUPActionType(body.get("action_type", "execute")),
        parameters=body.get("parameters", {}),
        timeout_ms=body.get("timeout_ms", 5000),
    )

    if state.policy and not state.policy.can_read_sensor(action.capability_id.replace("read_", "")):
        return {"error": "Blocked by sandbox policy"}

    result = await state.device_registry.execute_action(action)
    return result.model_dump()


@app.get("/api/hardware/context")
async def hardware_llm_context():
    """Get hardware context string for LLM."""
    if not state.device_registry:
        return {"context": "No hardware devices connected."}
    return {"context": state.device_registry.to_llm_context()}


@app.get("/api/hardware/stats")
async def hardware_stats():
    if not state.device_registry:
        return {}
    return state.device_registry.stats


# ─────────────────────────────────────────────
# Sandbox Policy API
# ─────────────────────────────────────────────

@app.get("/api/policy")
async def get_policy():
    if not state.policy:
        return {}
    return state.policy.to_dict()


@app.post("/api/policy/update")
async def update_policy(body: dict):
    state.policy = SandboxPolicy(body)
    state.policy.save()
    return {"ok": True}


# ─────────────────────────────────────────────
# OAuth & Integrations API
# ─────────────────────────────────────────────

@app.get("/api/integrations")
async def list_integrations():
    """List all available integrations and their connection status."""
    providers = state.oauth.list_providers() if state.oauth else []
    return {
        "providers": providers,
        "spotify_connected": state.spotify.connected if state.spotify else False,
        "home_assistant_connected": state.home_assistant.connected if state.home_assistant else False,
        "notion_connected": state.notion.connected if state.notion else False,
    }


@app.get("/api/oauth/authorize/{provider_id}")
async def oauth_authorize(provider_id: str):
    """Start an OAuth2 flow — returns the authorization URL."""
    if not state.oauth:
        return {"error": "OAuth manager not initialized"}
    url = state.oauth.build_authorize_url(provider_id)
    if not url:
        return {"error": f"Cannot build authorize URL for {provider_id}"}
    return {"url": url, "provider": provider_id}


@app.get("/api/oauth/callback")
async def oauth_callback(state_param: str = Query(alias="state", default=""), code: str = ""):
    """Handle OAuth2 callback from provider."""
    if not state.oauth:
        return {"error": "OAuth manager not initialized"}
    result = await state.oauth.handle_callback(state_param, code)
    return result


@app.post("/api/integrations/token")
async def store_integration_token(body: dict):
    """Store a long-lived API token (e.g., Home Assistant)."""
    provider_id = body.get("provider_id", "")
    token = body.get("token", "")
    if not provider_id or not token:
        return {"error": "provider_id and token are required"}
    if state.oauth:
        state.oauth.store_api_token(provider_id, token)
    return {"ok": True, "provider": provider_id}


@app.post("/api/integrations/disconnect/{provider_id}")
async def disconnect_integration(provider_id: str):
    """Disconnect an integration by revoking its tokens."""
    if state.oauth:
        state.oauth.revoke_token(provider_id)
    return {"ok": True, "provider": provider_id}


# ─────────────────────────────────────────────
# Webhook API
# ─────────────────────────────────────────────

@app.post("/api/webhooks/{app_id}")
async def receive_webhook(app_id: str, request_body: dict = None):
    """Receive an incoming webhook from an external app."""
    if not state.webhook_receiver:
        return {"error": "Webhook receiver not initialized"}
    body_bytes = json.dumps(request_body or {}).encode() if request_body else b"{}"
    result = await state.webhook_receiver.handle_request(
        app_id=app_id,
        body=body_bytes,
        headers={},
        content_type="application/json",
    )
    return result


@app.get("/api/webhooks")
async def list_webhooks():
    """List registered webhook configurations."""
    if not state.webhook_receiver:
        return {"webhooks": []}
    return {
        "webhooks": state.webhook_receiver.list_webhooks(),
        "events": state.event_bus.recent_events(20) if state.event_bus else [],
    }


# ─────────────────────────────────────────────
# Marketplace API
# ─────────────────────────────────────────────

@app.get("/api/marketplace/search")
async def marketplace_search(q: str = ""):
    """Search the skill marketplace."""
    if not state.marketplace:
        return {"results": []}
    results = await state.marketplace.search(q)
    return {"results": results}


@app.post("/api/marketplace/install")
async def marketplace_install(body: dict):
    """Install a skill from the marketplace."""
    if not state.marketplace:
        return {"success": False, "error": "Marketplace not available"}
    skill_id = body.get("skill_id", "")
    version = body.get("version", "latest")
    source_url = body.get("source_url")
    result = await state.marketplace.install(skill_id, version, source_url)
    return result


@app.get("/api/marketplace/installed")
async def marketplace_installed():
    """List all marketplace-installed skills."""
    if not state.marketplace:
        return {"skills": []}
    return {"skills": state.marketplace.list_installed()}


@app.delete("/api/marketplace/uninstall/{skill_id}")
async def marketplace_uninstall(skill_id: str):
    """Uninstall a marketplace skill."""
    if not state.marketplace:
        return {"success": False, "error": "Marketplace not available"}
    return await state.marketplace.uninstall(skill_id)


@app.post("/api/marketplace/update/{skill_id}")
async def marketplace_update(skill_id: str):
    """Update a marketplace skill to latest version."""
    if not state.marketplace:
        return {"success": False, "error": "Marketplace not available"}
    return await state.marketplace.update(skill_id)


# ─────────────────────────────────────────────
# Browser Control API
# ─────────────────────────────────────────────

@app.post("/api/browser/init")
async def browser_init():
    """Initialize browser control (CDP connection)."""
    if not state.browser:
        return {"error": "Browser controller not available"}
    ok = await state.browser.initialize()
    return {"connected": ok}


@app.post("/api/browser/navigate")
async def browser_navigate(body: dict):
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    return await state.browser.navigate(body.get("url", ""))


@app.post("/api/browser/screenshot")
async def browser_screenshot(body: dict):
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    return await state.browser.screenshot(body.get("full_page", False))


@app.post("/api/browser/snapshot")
async def browser_snapshot():
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    return await state.browser.snapshot()


@app.post("/api/browser/action")
async def browser_action(body: dict):
    """Execute a browser action (click, type, scroll, etc.)."""
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    action = body.get("action", "")
    if action == "click":
        return await state.browser.click(body.get("selector", body.get("ref_or_selector", "")))
    elif action == "hover":
        return await state.browser.hover(body.get("selector", body.get("ref_or_selector", "")))
    elif action in ("type", "type_text"):
        return await state.browser.type_text(
            body.get("selector", body.get("ref_or_selector", "")),
            body.get("text", ""),
        )
    elif action == "fill_form":
        return await state.browser.fill_form(body.get("fields", {}))
    elif action == "scroll":
        return await state.browser.scroll(body.get("direction", "down"), body.get("amount", 500))
    elif action == "evaluate":
        return await state.browser.evaluate(body.get("js_code", ""))
    elif action == "select":
        return await state.browser.select(body.get("selector", ""), body.get("value", ""))
    elif action == "console_logs":
        return await state.browser.get_console_logs(body.get("limit", 50), body.get("clear", False))
    elif action == "pdf":
        return await state.browser.get_page_pdf(
            body.get("print_background", True),
            body.get("landscape", False),
        )
    elif action == "wait":
        return await state.browser.wait(body.get("ms", 1000))
    return {"error": f"Unknown action: {action}"}


# ─────────────────────────────────────────────
# Hardware Mesh API
# ─────────────────────────────────────────────

@app.post("/api/hardware/invoke")
async def hardware_invoke(body: dict):
    """Invoke a command on a connected node via the hardware mesh."""
    if not state.hardware_mesh:
        return {"error": "Hardware mesh not initialized"}
    return await state.hardware_mesh.invoke(
        node_id=body.get("node_id", ""),
        command=body.get("command", ""),
        params=body.get("params", {}),
        timeout=body.get("timeout", 10.0),
    )


@app.get("/api/hardware/mesh")
async def hardware_mesh_status():
    """Get hardware mesh status with all connected nodes."""
    if not state.hardware_mesh:
        return {"nodes": []}
    return {"nodes": state.hardware_mesh.connected_nodes}


# ─────────────────────────────────────────────
# Identity API (enhanced)
# ─────────────────────────────────────────────

@app.get("/api/identity/soul")
async def get_soul():
    """Get the agent's SOUL.md (personality)."""
    if state.identity_workspace:
        return {"soul": state.identity_workspace.read_soul()}
    return {"soul": ""}


@app.post("/api/identity/soul")
async def update_soul(body: dict):
    """Update the agent's SOUL.md."""
    if state.identity_workspace:
        if body.get("append"):
            state.identity_workspace.append_soul(body["append"])
        elif body.get("content"):
            state.identity_workspace.write_soul(body["content"])
        return {"ok": True}
    return {"error": "Identity workspace not initialized"}


@app.get("/api/identity/memory_md")
async def get_memory_md():
    """Get the agent's MEMORY.md (long-term curated memory)."""
    if state.identity_workspace:
        return {"memory": state.identity_workspace.read_memory()}
    return {"memory": ""}


@app.get("/api/nodes")
async def list_nodes():
    """List all connected hardware nodes."""
    nodes = []
    for node_id, ws in state.daemons.items():
        nodes.append({
            "node_id": node_id,
            "connected": True,
            "sessions": list(state.get_sessions_for_daemon(node_id)),
        })
    return {"nodes": nodes, "count": len(nodes)}


@app.get("/api/devices")
async def list_devices():
    """List all connected hardware nodes / daemons."""
    nodes = []
    for node_id, info in state.daemons.items():
        _ = info if not isinstance(info, dict) else None
        nodes.append({
            "node_id": node_id,
            "connected": True,
            "type": state.devices.get(node_id, {}).get("device_type", "unknown"),
            "capabilities": state.devices.get(node_id, {}).get("capabilities", []),
        })
    for dev_id, dev_info in state.devices.items():
        if dev_id not in [n["node_id"] for n in nodes]:
            nodes.append({
                "node_id": dev_id,
                "connected": dev_id in state.daemons,
                "type": dev_info.get("device_type", "unknown"),
                "capabilities": dev_info.get("capabilities", []),
            })
    return {"devices": nodes, "total": len(nodes)}


# ─────────────────────────────────────────────
# Federated Sync API
# ─────────────────────────────────────────────

@app.get("/api/sync/status")
async def sync_status():
    if not state.sync_engine:
        return {"enabled": False}
    return {"enabled": True, **state.sync_engine.stats}


@app.get("/api/sync/export")
async def sync_export():
    """Export memory bundle for manual federated sync."""
    if not state.sync_engine:
        return {"error": "Sync engine not running"}
    return state.sync_engine.export_to_bundle()


@app.post("/api/sync/import")
async def sync_import(body: dict):
    """Import a memory bundle from another node."""
    if not state.sync_engine:
        return {"error": "Sync engine not running"}
    applied = state.sync_engine.import_from_bundle(body)
    return {"applied": applied}


# ─────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await state.init()
    if state.memory:
        state.memory.start_background_tasks()
    if state.cron_service:
        def _routine_executor(job):
            import asyncio as _aio
            logger.info("Routine fired: id=%s type=%s desc=%s", job.id, job.job_type, job.description)
            run_id = state.cron_service.record_run_start(job.id)
            try:
                payload = job.payload or {}
                skill_id = payload.get("skill")
                endpoint = payload.get("endpoint")
                prompt = payload.get("prompt")

                if skill_id and endpoint and state.skill_registry:
                    skill = state.skill_registry.get_skill(skill_id)
                    if skill:
                        loop = _aio.new_event_loop()
                        try:
                            result = loop.run_until_complete(
                                skill.execute(endpoint, payload.get("args", {}), {})
                            )
                        finally:
                            loop.close()
                        state.cron_service.record_run_finish(
                            run_id, "success" if result.get("success") else "error",
                            result, result.get("error"),
                        )
                        return

                if prompt and state.orchestrator:
                    session_id = job.session_id or f"routine-{job.id}"
                    loop = _aio.new_event_loop()
                    try:
                        loop.run_until_complete(
                            state.orchestrator.handle_command(session_id, prompt)
                        )
                    finally:
                        loop.close()
                    state.cron_service.record_run_finish(run_id, "success", {"prompt": prompt}, None)
                    return

                state.cron_service.record_run_finish(
                    run_id, "success",
                    {"message": "No skill or prompt configured; routine logged."},
                    None,
                )
            except Exception as exc:
                logger.exception("Routine execution error for job %s", job.id)
                state.cron_service.record_run_finish(run_id, "error", {}, str(exc))

        state.cron_service.start(_routine_executor)

    async def _state_heartbeat():
        """Push dashboard/system state to all WS clients every 10s."""
        while True:
            await asyncio.sleep(10)
            if not state.sessions:
                continue
            try:
                dashboard = await _get_dashboard_data()
                await state.broadcast_event("dashboard_update", dashboard)
            except Exception:
                pass
    asyncio.create_task(_state_heartbeat())


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown: close LLM clients, MCP connections, sync engine."""
    logger.info("THEORA Brain shutting down gracefully...")
    if state.orchestrator and state.orchestrator.llm:
        await state.orchestrator.llm.close()
    if state.mcp_client:
        await state.mcp_client.disconnect_all()
    if state.sync_engine:
        await state.sync_engine.stop_discovery()
    if state.taskflows:
        await state.taskflows.stop()
    logger.info("Shutdown complete.")


# ─────────────────────────────────────────────
# Main Client WebSocket
# ─────────────────────────────────────────────

@app.websocket("/v1/session")
async def client_session(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid4())
    state.sessions[session_id] = ws
    logger.info(f"Client connected: {session_id}")

    gw_session = GatewaySession(session_id, ws, state.gateway_registry)

    for node_id in state.daemons:
        state.bind_session_to_daemon(session_id, node_id)
        state.perception.update_connected_nodes(session_id, list(state.daemons.keys()))

    greeting = _build_greeting()

    await ws.send_json(TheoraMessage(
        session_id=session_id,
        hop="brain",
        type="text_response",
        payload=TextResponsePayload(
            text=greeting
        ).model_dump(),
    ).model_dump())

    try:
        while True:
            raw = await ws.receive_json()
            raw["session_id"] = session_id

            msg_type = raw.get("type", "")
            if msg_type in ("req", "res", "event"):
                await gw_session.handle_message(raw)
                continue

            try:
                msg, payload = parse_message(raw)

                if msg.type == "text_command" and isinstance(payload, TextCommandPayload):
                    state.memory.working_push(session_id, {"role": "user", "text": payload.text})
                    await state.orchestrator.handle_command_stream(
                        session_id=session_id,
                        text=payload.text,
                        context=payload.context,
                    )

                    if state.skill_gen:
                        history = state.memory.working_get(session_id) or []
                        need = await state.skill_gen.detect_unmet_need(history)
                        if need:
                            manifest = await state.skill_gen.generate_skill(
                                capability=need.get("capability", ""),
                                service=need.get("service", ""),
                            )
                            if manifest:
                                await ws.send_json(TheoraMessage(
                                    session_id=session_id,
                                    hop="brain",
                                    type="skill_proposal",
                                    payload={"manifest": manifest, "reason": need.get("capability", "")},
                                ).model_dump())

                elif msg.type == "voice_config":
                    vcfg = raw.get("payload", {})
                    mode = vcfg.get("mode", "realtime")
                    provider = vcfg.get("provider", "openai")
                    if state.voice_router:
                        state.voice_router.set_session_voice_mode(session_id, mode)
                        if mode == "disabled":
                            await state.voice_router.stop_session_voice(session_id)

                    if provider == "gemini" and mode == "realtime" and state.gemini_proxy:
                        system_prompt = ""
                        if state.identity_workspace:
                            system_prompt = state.identity_workspace.build_system_prompt()

                        async def _gemini_audio_cb(sid, b64, is_done):
                            try:
                                await ws.send_json(TheoraMessage(
                                    session_id=sid,
                                    hop="brain",
                                    type="audio_response",
                                    payload={
                                        "data_b64": b64,
                                        "encoding": "pcm16",
                                        "sample_rate": 24000,
                                        "is_final": is_done,
                                    },
                                ).model_dump())
                            except Exception:
                                pass

                        async def _gemini_transcript_cb(sid, text, is_partial):
                            try:
                                await ws.send_json(TheoraMessage(
                                    session_id=sid,
                                    hop="brain",
                                    type="transcript",
                                    payload={"text": text, "role": "assistant", "is_partial": is_partial},
                                ).model_dump())
                            except Exception:
                                pass

                        await state.gemini_proxy.start_session(
                            session_id=session_id,
                            node_id="web",
                            system_prompt=system_prompt,
                            on_audio_delta=_gemini_audio_cb,
                            on_transcript=_gemini_transcript_cb,
                        )

                    await ws.send_json(TheoraMessage(
                        session_id=session_id,
                        hop="brain",
                        type="voice_config_ack",
                        payload={"mode": mode, "provider": provider, "status": "ok"},
                    ).model_dump())
                    logger.info(f"Web client voice mode: {mode} (provider: {provider})")

                elif msg.type == "audio_chunk" and isinstance(payload, AudioChunkPayload):
                    if state.gemini_proxy and state.gemini_proxy.has_session(session_id):
                        await state.gemini_proxy.relay_audio(session_id, payload.data_b64)
                    elif state.voice_router:
                        await state.voice_router.handle_audio_from_client(
                            session_id=session_id,
                            audio_b64=payload.data_b64,
                            chunk_index=payload.chunk_index,
                            is_final=payload.is_final,
                            encoding=payload.encoding or "pcm16",
                            sample_rate=payload.sample_rate or 24000,
                        )

                elif msg.type == "ui_event" and isinstance(payload, UIEventPayload):
                    await state.orchestrator.handle_ui_event(
                        session_id=session_id,
                        action_id=payload.action_id,
                        event=payload.event,
                        value=payload.value,
                    )

                elif msg.type == "device_register" and isinstance(payload, DeviceRegisterPayload):
                    state.devices[payload.device_id] = payload.model_dump()
                    logger.info(f"Device registered: {payload.device_id} ({payload.device_type})")

                elif msg.type == "vision_query":
                    payload_dict = raw.get("payload", {})
                    query_text = payload_dict.get("query", "What do you see?")
                    target_node = payload_dict.get("node_id", "")
                    if not target_node:
                        nodes = state.vision_buffer.node_ids_with_frames()
                        target_node = nodes[0] if nodes else "default"
                    state.change_detector.force_trigger(target_node, "user_request")
                    latest = state.vision_buffer.latest(target_node)
                    if latest and state.scene and state.scene.available:
                        asyncio.ensure_future(
                            _analyze_scene_background(target_node, latest, mode="query", query=query_text)
                        )

                elif msg.type == "vision_frame":
                    frame_payload = raw.get("payload", {})
                    frame_b64_len = len(frame_payload.get("data_b64", ""))
                    if frame_b64_len > VISION_MAX_FRAME_KB * 1024:
                        logger.warning(f"Rejecting oversized frame from webclient {session_id[:8]}: {frame_b64_len}B")
                    else:
                        virtual_node = f"webclient_{session_id[:8]}"
                        state.vision_buffer.push(virtual_node, frame_payload)
                        state.perception.update_vision(session_id, state.vision_buffer, virtual_node)
                        state.bind_session_to_daemon(session_id, virtual_node)

                        data_b64 = frame_payload.get("data_b64", "")
                        change_event = state.change_detector.should_analyze(
                            virtual_node,
                            data_b64,
                            frame_payload.get("encoding", "jpeg"),
                        )
                        if change_event and state.scene and state.scene.available:
                            mode = "tracking" if change_event.trigger_reason == "scene_change" else "general"
                            asyncio.ensure_future(
                                _analyze_scene_background(virtual_node, frame_payload, mode=mode)
                            )

                elif msg.type == "biometric":
                    bio = raw.get("payload", {})
                    if state.orchestrator:
                        state.orchestrator.update_biometric(session_id, bio)
                    state.perception.update_sensors(session_id, bio)

            except Exception as msg_err:
                logger.error(f"Error processing message from {session_id[:8]}: {msg_err}", exc_info=True)
                try:
                    await ws.send_json(TheoraMessage(
                        session_id=session_id, hop="brain", type="text_response",
                        payload=TextResponsePayload(text=f"Sorry, something went wrong: {msg_err}").model_dump(),
                    ).model_dump())
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {session_id}")
        if state.orchestrator:
            try:
                await state.orchestrator.on_session_disconnect(session_id)
            except Exception as e:
                logger.warning(f"Session summarization failed: {e}")
        if state.identity_workspace:
            try:
                _llm = state.orchestrator.llm if state.orchestrator else None
                await state.identity_workspace.maintenance_cycle(
                    memory_store=state.memory,
                    llm=_llm,
                    session_id=session_id,
                )
            except Exception as e:
                logger.debug(f"Identity maintenance skipped: {e}")
        state.sessions.pop(session_id, None)
        state.audio.clear_session(session_id)
        state.perception.clear(session_id)
        state.memory.working_clear(session_id)


# ─────────────────────────────────────────────
# Daemon WebSocket (for OpenClaw-style nodes)
# ─────────────────────────────────────────────

NODE_API_KEY = os.environ.get("NODE_API_KEY", "dev-secret-key")

@app.websocket("/v1/node")
async def daemon_session(ws: WebSocket, api_key: str = Query(default=None)):
    if api_key != NODE_API_KEY:
        logger.warning("Unauthorized daemon connection attempt rejected")
        await ws.close(code=1008, reason="Unauthorized Edge Node API Key")
        return

    await ws.accept()
    node_id = None
    logger.info("Daemon connecting...")

    try:
        while True:
            raw = await ws.receive_json()
            msg, payload = parse_message(raw)

            if msg.type in ("node_register", "register") and isinstance(payload, NodeRegisterPayload):
                node_id = payload.node_id
                state.daemons[node_id] = ws
                if state.skill_executor:
                    state.skill_executor.register_daemon_type(node_id, payload.node_type)
                logger.info(f"Node registered: {node_id} ({payload.node_type}/{payload.platform}) — caps: {payload.capabilities}")
                _log_activity("device_connected", f"{node_id} ({payload.node_type})")

                for sid in state.sessions:
                    state.bind_session_to_daemon(sid, node_id)
                    state.perception.update_connected_nodes(sid, list(state.daemons.keys()))

                if state.hardware_mesh:
                    await state.hardware_mesh.on_node_connected(node_id, {
                        "node_type": payload.node_type,
                        "platform": payload.platform,
                        "capabilities": payload.capabilities,
                    })

                await ws.send_json(TheoraMessage(
                    hop="brain", type="text_response",
                    payload=TextResponsePayload(text=f"Node '{node_id}' registered successfully.").model_dump(),
                ).model_dump())

            elif msg.type == "execute_result":
                logger.info(f"Daemon result from {node_id}")
                result_payload = raw.get("payload", {})
                request_id = result_payload.get("request_id", "")
                if state.hardware_mesh and request_id:
                    state.hardware_mesh.resolve_invoke(request_id, result_payload)
                if state.orchestrator:
                    await state.orchestrator.handle_daemon_result(
                        node_id=node_id,
                        result=result_payload,
                        session_id=msg.session_id,
                    )

            elif msg.type == "vision_frame":
                frame_payload = raw.get("payload", {})
                if "data_b64" not in frame_payload and "image_b64" in frame_payload:
                    frame_payload["data_b64"] = frame_payload["image_b64"]
                frame_b64_len = len(frame_payload.get("data_b64", ""))
                if frame_b64_len > VISION_MAX_FRAME_KB * 1024:
                    logger.warning(f"Rejecting oversized frame from {node_id}: {frame_b64_len}B")
                else:
                    effective_node = node_id or frame_payload.get("node_id", "unknown")
                    state.vision_buffer.push(effective_node, frame_payload)

                    for sid in state.get_sessions_for_daemon(effective_node):
                        state.perception.update_vision(sid, state.vision_buffer, effective_node)

                    data_b64 = frame_payload.get("data_b64", "")
                    change_event = state.change_detector.should_analyze(
                        effective_node, data_b64, frame_payload.get("encoding", "jpeg"),
                    )
                    if change_event and state.scene and state.scene.available:
                        mode = "tracking" if change_event.trigger_reason == "scene_change" else "general"
                        asyncio.ensure_future(
                            _analyze_scene_background(effective_node, frame_payload, mode=mode)
                        )

                    if state.orchestrator:
                        state.orchestrator.resolve_pending_frame(msg.msg_id, frame_payload)

            elif msg.type == "vision_query":
                payload_dict = raw.get("payload", {})
                query_text = payload_dict.get("query", "What do you see?")
                target_node = payload_dict.get("node_id", "") or node_id or "default"
                state.change_detector.force_trigger(target_node, "user_request")
                latest = state.vision_buffer.latest(target_node)
                if latest and state.scene and state.scene.available:
                    asyncio.ensure_future(
                        _analyze_scene_background(target_node, latest, mode="query", query=query_text)
                    )

            elif msg.type == "gesture":
                gesture_payload = raw.get("payload", {})
                gesture = gesture_payload.get("gesture", "")
                if gesture and node_id:
                    logger.info(f"Gesture from {node_id}: {gesture}")
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.perception.update_gesture(sid, gesture)
                        if state.orchestrator:
                            await state.orchestrator.handle_command(
                                session_id=sid,
                                text=f"[GESTURE] User performed: {gesture}",
                                context={"source": "gesture", "gesture": gesture, "node": node_id},
                    )

            elif msg.type == "telemetry":
                telemetry_payload = raw.get("payload", {})
                sensors = telemetry_payload.get("sensors", {})

                vitals = sensors.get("vitals", {})
                hr = vitals.get("ppg_heart_rate") or sensors.get("ppg_heart_rate")
                if hr:
                    logger.info(f"Telemetry from {node_id}: {hr} BPM")

                if state.orchestrator:
                    state.orchestrator.update_biometric(node_id, sensors)

                if node_id:
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.perception.update_sensors(sid, sensors)

            elif msg.type == "sensor_telemetry":
                payload_dict = raw.get("payload", {})
                sensor_name = payload_dict.get("sensor", "")
                sensor_data = payload_dict.get("data", {})
                source = payload_dict.get("source", "unknown")
                logger.info(f"Sensor [{sensor_name}] from {node_id} ({source}): {sensor_data}")

                sensors_map = {sensor_name: sensor_data}
                if state.orchestrator:
                    state.orchestrator.update_biometric(node_id, sensors_map)
                if node_id:
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.perception.update_sensors(sid, sensors_map)

            elif msg.type == "sensor_batch":
                payload_dict = raw.get("payload", {})
                readings = payload_dict.get("readings", {})
                logger.info(f"Sensor batch from {node_id}: {list(readings.keys())}")
                if state.orchestrator:
                    state.orchestrator.update_biometric(node_id, readings)
                if node_id:
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.perception.update_sensors(sid, readings)

            elif msg.type == "glasses_status":
                payload_dict = raw.get("payload", {})
                connected = payload_dict.get("glasses_connected", False)
                battery = payload_dict.get("battery_level", -1)
                model = payload_dict.get("glasses_model", "THEORA")
                logger.info(f"Glasses ({model}) {'connected' if connected else 'disconnected'} via {node_id}, battery={battery}%")

            elif msg.type == "voice_config":
                payload_dict = raw.get("payload", {})
                if state.voice_router and node_id:
                    state.voice_router.register_voice_config(node_id, payload_dict)
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.voice_router.bind_node_to_session(node_id, sid)
                    supports_rt = payload_dict.get("supports_realtime", False)
                    logger.info(f"Voice config from {node_id}: realtime={supports_rt}")

            elif msg.type == "audio_chunk" and node_id:
                payload_dict = raw.get("payload", {})
                audio_b64 = payload_dict.get("data_b64", "")
                if state.voice_router and audio_b64:
                    sessions = state.get_sessions_for_daemon(node_id)
                    target_sid = next(iter(sessions), None)
                    if target_sid:
                        await state.voice_router.handle_audio_from_node(
                            node_id=node_id,
                            session_id=target_sid,
                            audio_b64=audio_b64,
                            chunk_index=payload_dict.get("chunk_index", 0),
                            is_final=payload_dict.get("is_final", False),
                            encoding=payload_dict.get("encoding", "pcm16"),
                            sample_rate=payload_dict.get("sample_rate", 24000),
                        )

            elif msg.type == "skill_approval":
                payload_dict = raw.get("payload", {})
                skill_id = payload_dict.get("skill_id", "")
                approved = payload_dict.get("approved", False)
                if state.skill_gen and skill_id:
                    if approved:
                        await state.skill_gen.approve_skill(skill_id)
                        logger.info(f"Skill approved via phone: {skill_id}")
                    else:
                        state.skill_gen.reject_skill(skill_id)
                        logger.info(f"Skill rejected via phone: {skill_id}")

            elif msg.type == "text_command":
                payload_dict = raw.get("payload", {})
                text = payload_dict.get("text", "")
                context = payload_dict.get("context", {})
                if text and state.orchestrator and node_id:
                    sessions = state.get_sessions_for_daemon(node_id)
                    target_sid = next(iter(sessions), None)
                    if not target_sid:
                        target_sid = f"daemon-{node_id}"
                        state.sessions[target_sid] = ws
                        state.bind_session_to_daemon(target_sid, node_id)
                    state.memory.working_push(target_sid, {"role": "user", "text": text})
                    context["source_node"] = node_id
                    await state.orchestrator.handle_command_stream(
                        session_id=target_sid,
                        text=text,
                        context=context,
                    )
                    logger.info(f"Text command from daemon {node_id}: {text[:80]}")

            elif msg.type == "frame":
                frame_payload = raw.get("payload", {})
                data_b64 = frame_payload.get("data_b64") or frame_payload.get("image_b64", "")
                if data_b64:
                    frame_payload["data_b64"] = data_b64
                    frame_b64_len = len(data_b64)
                    if frame_b64_len > VISION_MAX_FRAME_KB * 1024:
                        logger.warning(f"Rejecting oversized frame from {node_id}: {frame_b64_len}B")
                    else:
                        effective_node = node_id or frame_payload.get("node_id", "unknown")
                        state.vision_buffer.push(effective_node, frame_payload)
                        for sid in state.get_sessions_for_daemon(effective_node):
                            state.perception.update_vision(sid, state.vision_buffer, effective_node)

    except WebSocketDisconnect:
        if node_id:
            logger.info(f"Daemon disconnected: {node_id}")
            state.daemons.pop(node_id, None)
            if state.skill_executor:
                state.skill_executor.unregister_daemon(node_id)
            if state.hardware_mesh:
                state.hardware_mesh.on_node_disconnected(node_id)
            for sid in state.get_sessions_for_daemon(node_id):
                state.perception.update_connected_nodes(sid, list(state.daemons.keys()))


# ─────────────────────────────────────────────
# Federated Sync WebSocket
# ─────────────────────────────────────────────

@app.websocket("/sync")
async def sync_peer_endpoint(ws: WebSocket):
    """Peer-to-peer sync endpoint for federated memory."""
    await ws.accept()
    logger.info("Sync peer connected")

    try:
        while True:
            raw = await ws.receive_json()
            msg_type = raw.get("type")

            if msg_type == "sync_request":
                peer_id = raw.get("node_id", "unknown")
                remote_vc = raw.get("vector_clock", {})

                expected_pass = os.getenv("THEORA_SYNC_PASSPHRASE", "")
                remote_pass = raw.get("passphrase", "")
                if expected_pass and remote_pass != expected_pass:
                    await ws.send_json({"type": "sync_error", "message": "Invalid passphrase"})
                    break

                await ws.send_json({
                    "type": "sync_response",
                    "node_id": state.sync_engine.node_id if state.sync_engine else "",
                    "vector_clock": state.sync_engine.get_vector_clock() if state.sync_engine else {},
                })

                incoming = await ws.receive_json()
                applied = 0
                if incoming.get("type") == "sync_data" and state.sync_engine:
                    applied = state.sync_engine.apply_remote_changes(incoming.get("changes", []))

                my_changes = []
                if state.sync_engine and hasattr(state.sync_engine, '_wal'):
                    my_changes = state.sync_engine._wal.get_changes_since(
                        remote_vc.get(state.sync_engine.node_id, "0:0:"),
                        exclude_node=peer_id,
                    )
                await ws.send_json({
                    "type": "sync_data",
                    "changes": [op.to_dict() for op in my_changes] if my_changes else [],
                })
                _log_activity("sync", f"Synced with {peer_id}: received {applied} ops")
                break

    except WebSocketDisconnect:
        logger.info("Sync peer disconnected")
    except Exception as e:
        logger.warning(f"Sync peer error: {e}")


# ─────────────────────────────────────────────
# Background Scene Analysis
# ─────────────────────────────────────────────

async def _analyze_scene_background(
    node_id: str, frame_payload: dict, mode: str = "general", query: str = "",
):
    """Run VLM scene analysis on a vision frame and update perception."""
    try:
        data_b64 = frame_payload.get("data_b64", "")
        encoding = frame_payload.get("encoding", "jpeg")
        if not data_b64:
            return

        result = await state.scene.analyze_frame(
            data_b64=data_b64, encoding=encoding, node_id=node_id,
            force=True, mode=mode, query=query,
        )
        if result:
            for sid in state.get_sessions_for_daemon(node_id):
                frame = state.perception.get_frame(sid)
                frame.scene_description = result.get("scene_description", result.get("answer", ""))
                frame.detected_objects = result.get("detected_objects", [])
                frame.text_in_scene = result.get("text_in_scene", [])

                if mode == "query" and query:
                    answer = result.get("answer", result.get("scene_description", ""))
                    if answer and state.orchestrator:
                        from models.protocol import TheoraMessage, TextResponsePayload
                        await state.send_to_session(sid, TheoraMessage(
                            session_id=sid, hop="brain", type="text_response",
                            payload=TextResponsePayload(text=f"[Vision] {answer}").model_dump(),
                        ))
    except Exception as e:
        logger.warning(f"Background scene analysis failed: {e}")


# ─────────────────────────────────────────────
# Bundled Web UI (served from webui/ if present)
# ─────────────────────────────────────────────

_webui_dir = Path(__file__).parent.parent / "webui"
_webui_ready = _webui_dir.is_dir() and (_webui_dir / "index.html").exists()
_webui_route_mode = "spa" if _webui_ready else "fallback"
logger.info("Web UI routing mode=%s path=%s", _webui_route_mode, _webui_dir)

if _webui_ready and (_webui_dir / "assets").is_dir():
    from starlette.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(_webui_dir / "assets")), name="webui-assets")
    logger.info(f"Web UI bundled from {_webui_dir} — open {brain_public_base_url()}")
else:
    logger.warning(
        f"Web UI not found at {_webui_dir}. Dashboard will show setup instructions. "
        "Run 'make bundle-webui' to build the dashboard."
    )

_FALLBACK_HTML = """<!DOCTYPE html>
<html><head><title>THEORA Brain</title>
<style>body{font-family:system-ui;background:#0a0a0a;color:#e0e0e0;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0;padding:2rem}
.card{background:#141414;border:1px solid #222;border-radius:16px;padding:2.5rem;max-width:520px;text-align:center}
h1{color:#06b6d4;margin-bottom:.5rem}code{background:#1a1a1a;padding:.2em .5em;border-radius:4px;font-size:.85em}
a{color:#06b6d4}p{line-height:1.6}</style></head>
<body><div class="card">
<h1>THEORA Brain is Running</h1>
<p>The API is active, but the web dashboard is not bundled in this install.</p>
<p style="margin-top:1.5rem"><strong>Quick fix — reinstall with the dashboard:</strong></p>
<ol style="text-align:left;line-height:2">
<li>Clone: <code>git clone https://github.com/Spatial-AgenticOS/ASOS</code></li>
<li>Build UI: <code>cd ASOS && make bundle-webui</code></li>
<li>Install: <code>pip install -e asos-core[llm]</code></li>
<li>Restart: <code>theora serve</code></li>
</ol>
<p style="margin-top:1rem;opacity:.6">Or use the CLI directly: <code>theora start</code></p>
<p style="margin-top:1.5rem"><a href="/docs">API Docs</a> &middot;
<a href="/api/config">Config</a> &middot;
<a href="/skills">Skills</a> &middot;
<a href="/health">Health</a></p>
</div></body></html>"""


@app.get("/{full_path:path}")
async def serve_webui_or_fallback(full_path: str = ""):
    if _webui_ready:
        file_path = _webui_dir / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_webui_dir / "index.html")
    return HTMLResponse(_FALLBACK_HTML)


if __name__ == "__main__":
    import uvicorn
    print("""
    ╔══════════════════════════════════════╗
    ║        THEORA v1.2.0                ║
    ║   Open AI Agent · Computer Use      ║
    ║   Voice · GenUI · Hardware          ║
    ╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host=brain_bind_host(), port=brain_port(), log_level="info")
