"""
FERAL Brain — Unleashed AI Core
==========================================
The local-first agentic brain. Runs on the user's machine.
Clients (phone, web, daemon, glasses, robots) connect via WebSocket.
MCP clients (Claude, Cursor) connect via JSON-RPC.
Channels (Telegram, Discord, Slack) bridge messaging platforms.

v1.2.0 — HUP, MCP server/client, sandbox policies, channels, federated sync, routines, permissions.
"""

import asyncio
import logging
import os
import time
import collections
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, HTMLResponse, FileResponse

from models.protocol import (
    FeralMessage,
    TextCommandPayload,
    UIEventPayload,
    NodeRegisterPayload,
    TextResponsePayload,
    DeviceRegisterPayload,
    AudioChunkPayload,
    parse_message,
)
from config.runtime import brain_bind_host, brain_port, brain_public_base_url
from gateway.protocol import GatewaySession

from api.state import state, _log_activity, VISION_MAX_FRAME_KB
from api.routes.config import _build_greeting
from api.routes.dashboard import _get_dashboard_data

from security.session_auth import (
    session_auth_required,
    verify_session,
    is_localhost,
    local_bypass_enabled,
)
from security.device_pairing import DevicePairingStore  # used in type hint

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
from api.routes.timeline import router as timeline_router
from api.routes.brain_rest import router as brain_rest_router
from api.routes.baseline import router as baseline_router
from api.routes.handoff import router as handoff_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("feral.brain")


# ─────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────

app = FastAPI(
    title="FERAL Brain",
    description="FERAL — Open AI agent with computer use, GenUI, voice, and hardware control",
    version="1.2.0",
)

CORS_ORIGINS = os.getenv("FERAL_CORS_ORIGINS", "http://localhost:5173,http://localhost:9090").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Rate Limiting Middleware
# ─────────────────────────────────────────────

_rate_limit_store: collections.OrderedDict[str, collections.deque] = collections.OrderedDict()
RATE_LIMIT_RPM = int(os.getenv("FERAL_RATE_LIMIT_RPM", "120"))
_RATE_LIMIT_MAX_KEYS = 10_000
_rate_limit_last_cleanup = 0.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        global _rate_limit_last_cleanup
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if now - _rate_limit_last_cleanup > 60:
            _rate_limit_last_cleanup = now
            cutoff = now - 60
            stale = [k for k, v in _rate_limit_store.items() if not v or v[-1] < cutoff]
            for k in stale:
                del _rate_limit_store[k]

        if client_ip in _rate_limit_store:
            _rate_limit_store.move_to_end(client_ip)
        window = _rate_limit_store.setdefault(client_ip, collections.deque())
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_RPM:
            return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
        window.append(now)

        while len(_rate_limit_store) > _RATE_LIMIT_MAX_KEYS:
            _rate_limit_store.popitem(last=False)

        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


# ─────────────────────────────────────────────
# Optional REST API Key Middleware (Part C)
# ─────────────────────────────────────────────

def _load_api_key() -> str | None:
    """Return the REST API key from env or ~/.feral/api_key, or None."""
    key = os.environ.get("FERAL_API_KEY")
    if key:
        return key
    key_path = Path(os.environ.get("FERAL_HOME", str(Path.home() / ".feral"))) / "api_key"
    if key_path.exists():
        text = key_path.read_text().strip()
        return text or None
    return None


_OPEN_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        api_key = _load_api_key()
        if api_key is None:
            return await call_next(request)

        path = request.url.path
        if path in _OPEN_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        scope_type = request.scope.get("type", "")
        if scope_type == "websocket":
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if auth == f"Bearer {api_key}":
            return await call_next(request)

        return JSONResponse({"error": "Unauthorized — provide Authorization: Bearer <key>"}, status_code=401)


app.add_middleware(APIKeyMiddleware)


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
app.include_router(timeline_router)
app.include_router(brain_rest_router)
app.include_router(baseline_router)
app.include_router(handoff_router)


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
    logger.info("FERAL Brain shutting down gracefully...")
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
async def client_session(ws: WebSocket, token: str = Query(default=None)):
    await ws.accept()

    if session_auth_required():
        client_host = ws.client.host if ws.client else None
        if is_localhost(client_host) and local_bypass_enabled():
            pass  # localhost bypass
        elif token and verify_session(token):
            pass  # valid query-param token
        else:
            try:
                first_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                if first_msg.get("type") == "auth" and verify_session(first_msg.get("token", "")):
                    pass  # valid first-message token
                else:
                    await ws.close(code=4001, reason="Unauthorized")
                    return
            except Exception:
                await ws.close(code=4001, reason="Unauthorized")
                return

    session_id = str(uuid4())
    state.sessions[session_id] = ws
    logger.info(f"Client connected: {session_id}")

    gw_session = GatewaySession(session_id, ws, state.gateway_registry)

    for node_id in state.daemons:
        state.bind_session_to_daemon(session_id, node_id)
        state.perception.update_connected_nodes(session_id, list(state.daemons.keys()))

    greeting = _build_greeting()

    await ws.send_json(FeralMessage(
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
                                await ws.send_json(FeralMessage(
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
                                await ws.send_json(FeralMessage(
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
                                await ws.send_json(FeralMessage(
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

                    await ws.send_json(FeralMessage(
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
                    _record_biometrics_to_baseline(bio)

            except Exception as msg_err:
                logger.error(f"Error processing message from {session_id[:8]}: {msg_err}", exc_info=True)
                try:
                    await ws.send_json(FeralMessage(
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

NODE_API_KEY = os.environ.get("NODE_API_KEY", "")


@app.websocket("/v1/node")
async def daemon_session(ws: WebSocket, api_key: str = Query(default=None)):
    store = state.device_pairing_store
    paired_device_id = store.verify_device(api_key) if api_key else None

    await ws.accept()

    if paired_device_id is None and api_key != NODE_API_KEY:
        logger.warning("Unauthorized daemon connection attempt rejected")
        await ws.close(code=4003, reason="Unauthorized Edge Node API Key")
        return
    node_id = None
    logger.info("Daemon connecting (device_id=%s)...", paired_device_id or "legacy-key")

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

                await ws.send_json(FeralMessage(
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
                _record_biometrics_to_baseline(sensors)

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
                _record_biometrics_to_baseline(readings)

            elif msg.type == "heartbeat":
                if node_id and state.hardware_mesh:
                    state.hardware_mesh.node_health.record_heartbeat(node_id)
                    pending = state.hardware_mesh.ledger.get_pending(node_id)
                    if pending:
                        unacked_ids = [
                            r.envelope.command_id for r in pending
                            if r.state.value == "submitted"
                        ]
                        if unacked_ids:
                            await ws.send_json({
                                "type": "pending_commands",
                                "payload": {"command_ids": unacked_ids},
                            })

            elif msg.type == "glasses_status":
                payload_dict = raw.get("payload", {})
                connected = payload_dict.get("glasses_connected", False)
                battery = payload_dict.get("battery_level", -1)
                model = payload_dict.get("glasses_model", "FERAL")
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

                expected_pass = os.getenv("FERAL_SYNC_PASSPHRASE", "")
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
# Baseline Biometric Recording
# ─────────────────────────────────────────────

_BIOMETRIC_KEY_MAP = {
    "heart_rate": ("hr_resting", "health"),
    "ppg_heart_rate": ("hr_resting", "health"),
    "spo2": ("spo2_pct", "health"),
    "spo2_pct": ("spo2_pct", "health"),
    "skin_temp_c": ("skin_temp", "health"),
    "skin_temperature_c": ("skin_temp", "health"),
    "hrv_ms": ("hrv_ms", "health"),
    "sleep_hours": ("sleep_hours", "health"),
    "sleep_score": ("sleep_score", "health"),
    "steps": ("steps_daily", "activity"),
    "calories": ("calories_daily", "activity"),
}


def _record_biometrics_to_baseline(data: dict) -> None:
    """Extract known biometric keys from a sensor payload and record them."""
    if not state.baseline_engine or not data:
        return
    try:
        flat: dict[str, float] = {}
        for key, val in data.items():
            if isinstance(val, dict):
                for k2, v2 in val.items():
                    if isinstance(v2, (int, float)) and v2 > 0:
                        flat[k2] = float(v2)
            elif isinstance(val, (int, float)) and val > 0:
                flat[key] = float(val)

        for raw_key, value in flat.items():
            mapping = _BIOMETRIC_KEY_MAP.get(raw_key)
            if mapping:
                metric_id, category = mapping
                state.baseline_engine.record(metric_id, value, category=category)
    except Exception as exc:
        logger.debug("Baseline biometric recording error: %s", exc)


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
                        from models.protocol import FeralMessage, TextResponsePayload
                        await state.send_to_session(sid, FeralMessage(
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
<html><head><title>FERAL Brain</title>
<style>body{font-family:system-ui;background:#0a0a0a;color:#e0e0e0;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0;padding:2rem}
.card{background:#141414;border:1px solid #222;border-radius:16px;padding:2.5rem;max-width:520px;text-align:center}
h1{color:#06b6d4;margin-bottom:.5rem}code{background:#1a1a1a;padding:.2em .5em;border-radius:4px;font-size:.85em}
a{color:#06b6d4}p{line-height:1.6}</style></head>
<body><div class="card">
<h1>FERAL Brain is Running</h1>
<p>The API is active, but the web dashboard is not bundled in this install.</p>
<p style="margin-top:1.5rem"><strong>Quick fix — reinstall with the dashboard:</strong></p>
<ol style="text-align:left;line-height:2">
<li>Clone: <code>git clone https://github.com/FERAL-AI/FERAL-AI.git</code></li>
<li>Build UI: <code>cd FERAL-AI && make bundle-webui</code></li>
<li>Install: <code>pip install -e feral-core[llm]</code></li>
<li>Restart: <code>feral serve</code></li>
</ol>
<p style="margin-top:1rem;opacity:.6">Or use the CLI directly: <code>feral start</code></p>
<p style="margin-top:1.5rem"><a href="/docs">API Docs</a> &middot;
<a href="/api/config">Config</a> &middot;
<a href="/skills">Skills</a> &middot;
<a href="/health">Health</a></p>
</div></body></html>"""


@app.get("/{full_path:path}")
async def serve_webui_or_fallback(full_path: str = ""):
    if _webui_ready:
        file_path = (_webui_dir / full_path).resolve()
        if not file_path.is_relative_to(_webui_dir.resolve()):
            return HTMLResponse("Forbidden", status_code=403)
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_webui_dir / "index.html")
    return HTMLResponse(_FALLBACK_HTML)


if __name__ == "__main__":
    import uvicorn
    print("""
    ╔══════════════════════════════════════╗
    ║        FERAL v1.2.0                ║
    ║   Open AI Agent · Computer Use      ║
    ║   Voice · GenUI · Hardware          ║
    ╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host=brain_bind_host(), port=brain_port(), log_level="info")
