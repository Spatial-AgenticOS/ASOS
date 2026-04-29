"""
FERAL Brain — Unleashed AI Core
==========================================
The local-first agentic brain. Runs on the user's machine.
Clients (phone, web, daemon, glasses, robots) connect via WebSocket.
MCP clients (Claude, Cursor) connect via JSON-RPC.
Channels (Telegram, Discord, Slack) bridge messaging platforms.
"""

import asyncio
import logging
import os
import time
import collections
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, HTMLResponse, FileResponse

from version import VERSION as __version__
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

from security import session_auth as _session_auth_module
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
from api.routes.audio import router as audio_router
from api.routes.genui import router as genui_router
from api.routes.mcp import router as mcp_router
from api.routes.channels import router as channels_router
from api.routes.conversations import router as conversations_router
from api.routes.devices import router as devices_router
from api.routes.timeline import router as timeline_router
from api.routes.brain_rest import router as brain_rest_router
from api.routes.baseline import router as baseline_router
from api.routes.handoff import router as handoff_router
from api.routes.tool_genesis import router as tool_genesis_router
from api.routes.agent_mitosis import router as agent_mitosis_router
from api.routes.intents import router as intents_router
from api.routes.webhooks import router as webhooks_router
from api.routes.ambient import router as ambient_router
from api.routes.auth import router as auth_router
from api.routes.personas import router as personas_router
from api.routes.jobs import router as jobs_router
from api.routes.consciousness import router as consciousness_router
from api.routes.about_me import router as about_me_router
from api.routes.ideas import router as ideas_router
from api.routes.apps import router as apps_router
from api.routes.supervisor import router as supervisor_router
from api.routes.twin import router as twin_router
from api.routes.sessions import router as sessions_router  # W17

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("feral.brain")


# ─────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────

app = FastAPI(
    title="FERAL Brain",
    description="FERAL — Open AI agent with computer use, GenUI, voice, and hardware control",
    version=__version__,
)

from observability.metrics import init_metrics
init_metrics("feral")

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
# Default: 1200 req/min per remote IP. Local-first clients poll aggressively
# (dashboard / ambient / jobs / skills). We keep the limit but trust loopback.
RATE_LIMIT_RPM = int(os.getenv("FERAL_RATE_LIMIT_RPM", "1200"))
_RATE_LIMIT_MAX_KEYS = 10_000
_rate_limit_last_cleanup = 0.0

# Loopback clients (the Brain + same-host browser / CLI / iOS sim) are never
# rate-limited — that would throttle the app talking to itself.
_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1", "localhost", "unknown"})

# Low-cost polling endpoints exempted from the per-IP bucket so a UI tab cannot
# DoS itself. These are idempotent reads that the Brain should always answer.
_RATE_LIMIT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/dashboard",
    "/api/ambient/",
    "/api/ideas/",
    "/api/jobs",
    "/api/skills",
    "/api/channels",
    "/api/llm/status",
    "/api/identity",
    "/api/soul",
    "/api/memory/",
    # Pairing endpoints + installer must stay unthrottled — fresh phones
    # hit them before anything else and we don't want to lock them out.
    "/api/devices/pair",
    "/install-phone-bridge.sh",
    # Supervisor oversight surface polls aggressively on the /oversight
    # v2 page; it's a read-only audit view.
    "/api/supervisor/events",
    "/api/supervisor/stats",
    # Twin policy + approval queue polling.
    "/api/twin/",
)


def _route_template_for(request) -> str:
    """Return the FastAPI route template for *request* (e.g. ``/api/jobs/{id}``).

    Falls back to the literal path when the matcher hasn't run yet
    (rare — only happens for routes resolved by the catch-all SPA
    handler). Using the template instead of the raw path keeps
    ``feral_http_requests_total`` cardinality bounded.
    """
    route = request.scope.get("route")
    path_template = getattr(route, "path", None)
    return path_template or request.url.path


def _status_class(code: int) -> str:
    return f"{code // 100}xx" if 100 <= code < 600 else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        global _rate_limit_last_cleanup
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Skip loopback + well-known read-only polling endpoints entirely.
        if client_ip in _LOOPBACK_IPS:
            response = await call_next(request)
            _emit_http_metrics(request, response, time.time())
            return response
        if any(path == p or path.startswith(p) for p in _RATE_LIMIT_EXEMPT_PREFIXES):
            response = await call_next(request)
            _emit_http_metrics(request, response, time.time())
            return response

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
            response = JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
            _emit_http_metrics(request, response, now)
            return response
        window.append(now)

        while len(_rate_limit_store) > _RATE_LIMIT_MAX_KEYS:
            _rate_limit_store.popitem(last=False)

        response = await call_next(request)
        _emit_http_metrics(request, response, now)
        return response


def _emit_http_metrics(request, response, started_at: float) -> None:
    """W13 proof-of-concept: emit feral_http_requests_total + duration.

    This is the ONLY emit() call site this PR ships — every other
    module's emit() wiring is deferred to W13.1 so each owning
    workstream lands its own changes inside its own owned-paths set.
    """
    from observability.metrics import emit  # local import — keeps the
    # cold-import cost off the boot path when metrics are killed.

    status = getattr(response, "status_code", 0)
    labels = {
        "method": request.method,
        "route": _route_template_for(request),
        "status": _status_class(status),
    }
    emit("feral_http_requests_total", labels=labels)
    emit(
        "feral_http_request_duration_seconds",
        value=max(0.0, time.time() - started_at),
        labels={"method": labels["method"], "route": labels["route"]},
    )


app.add_middleware(RateLimitMiddleware)


# ─────────────────────────────────────────────
# Optional REST API Key Middleware (Part C)
# ─────────────────────────────────────────────

from api.keys import load_or_generate_api_key as _generate_key_impl
from api.keys import load_api_key as _load_api_key
from api.keys import get_api_key_path as _get_api_key_path


def _load_or_generate_api_key() -> str:
    """Load FERAL_API_KEY from env or ~/.feral/api_key; generate on first boot."""
    key_path = _get_api_key_path()
    existed = (key_path.exists() and key_path.read_text().strip()) or os.environ.get("FERAL_API_KEY", "").strip()
    key = _generate_key_impl()
    if not existed:
        print("=" * 70)
        print("FERAL: Generated new API key on first boot.")
        print(f"Location: {key_path}")
        print(f"Key: {key}")
        print("Use this key to authenticate clients (iOS, Android, browser ext).")
        print("Set FERAL_API_KEY env var to override.")
        print("=" * 70)
    return key


FERAL_API_KEY = _load_or_generate_api_key()


_OPEN_PATHS = frozenset({
    "/health", "/docs", "/redoc", "/openapi.json", "/metrics",
    "/api/auth/local-key", "/api/boot-report",
    # Phone-bridge installer script must be fetchable without an API key
    # because it's delivered over `curl … | bash` from a laptop / phone
    # that doesn't have the key yet.
    "/install-phone-bridge.sh",
    # /api/devices/pair/url + QR are served so a brand-new phone can
    # reach them after scanning the Pair modal QR; they only expose
    # one-time pairing tokens that the Brain itself issues.
    "/api/devices/pair/url",
    "/api/devices/pair/qr",
    "/api/devices/pair/complete",
    # Code-pair flow (SDK ↔ dashboard typed pair code).
    # Daemon announces an 8-char base32 code, dashboard claims it.
    # Codes have ~38 bits of entropy, 600s TTL, and /code/claim is
    # rate-limited to 5 wrong attempts per IP per 15 minutes — see
    # ``feral-core/api/middleware/rate_limit.py``.
    "/api/devices/pair/announce",
    "/api/devices/pair/status",
    "/api/devices/pair/code/claim",
})

_OPEN_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/api/oauth/callback",
    "/webhooks/",
)

# Narrow GET-only allowlist for the device-pairing landing page and the
# static bundle it needs to boot. A phone on the LAN that scanned the
# pairing QR will not have the Brain's API key yet; locking these paths
# behind Bearer-auth would make `/pair?t=…` unusable off-loopback. The
# pairing token is validated separately on the WebSocket handshake
# (`verify_device`), so serving the SPA shell + hashed asset bundles
# here does not widen the authenticated API surface.
_OPEN_GET_PATHS = frozenset({
    "/pair",
    "/v2/pair",
})

_OPEN_GET_PATH_PREFIXES = (
    "/assets/",
    "/v2/assets/",
)


def _is_webhook_receive(path: str) -> bool:
    """External webhook endpoints (POST /api/webhooks/{app_id}) must be public.
    
    External services cannot know our API key; they authenticate via HMAC signature.
    The LIST endpoint (GET /api/webhooks) remains authenticated.
    """
    if not path.startswith("/api/webhooks/"):
        return False
    tail = path[len("/api/webhooks/"):].strip("/")
    return bool(tail) and "/" not in tail


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in _OPEN_PATHS:
            return await call_next(request)
        if any(path.startswith(p) for p in _OPEN_PATH_PREFIXES):
            return await call_next(request)
        if _is_webhook_receive(path) and request.method == "POST":
            return await call_next(request)

        if request.method == "GET":
            if path in _OPEN_GET_PATHS:
                return await call_next(request)
            if any(path.startswith(p) for p in _OPEN_GET_PATH_PREFIXES):
                return await call_next(request)

        scope_type = request.scope.get("type", "")
        if scope_type == "websocket":
            return await call_next(request)

        client_host = request.client.host if request.client else None
        if _session_auth_module.is_localhost(client_host) and _session_auth_module.local_bypass_enabled():
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if auth == f"Bearer {FERAL_API_KEY}":
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
app.include_router(audio_router)
app.include_router(genui_router)
app.include_router(mcp_router)
app.include_router(channels_router)
app.include_router(conversations_router)
app.include_router(devices_router)
app.include_router(timeline_router)
app.include_router(brain_rest_router)
app.include_router(baseline_router)
app.include_router(handoff_router)
app.include_router(tool_genesis_router)
app.include_router(agent_mitosis_router)
app.include_router(intents_router)
app.include_router(webhooks_router)
app.include_router(ambient_router)
app.include_router(auth_router)
app.include_router(personas_router)
app.include_router(jobs_router)
app.include_router(consciousness_router)
app.include_router(about_me_router)
app.include_router(ideas_router)
app.include_router(apps_router)
app.include_router(supervisor_router)
app.include_router(twin_router)
app.include_router(sessions_router)  # W17


# ─────────────────────────────────────────────
# Prometheus-compatible /metrics endpoint
# ─────────────────────────────────────────────

from observability.metrics import (
    in_memory_snapshot as _metrics_snapshot,
    render_prometheus as _render_prometheus,
)


@app.get("/install-phone-bridge.sh")
async def install_phone_bridge_script():
    """Serve the phone-bridge installer over HTTP so the one-liner works:

        curl -fsSL http://brain.local:9090/install-phone-bridge.sh | bash -s -- \
            --token ... --brain-url ws://brain.local:9090/v1/node
    """
    from pathlib import Path as _Path
    from starlette.responses import PlainTextResponse

    here = _Path(__file__).resolve().parent.parent.parent
    candidates = [
        here / "scripts" / "install-phone-bridge.sh",
        _Path(__file__).resolve().parent.parent / "scripts" / "install-phone-bridge.sh",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return PlainTextResponse(candidate.read_text(), media_type="text/x-shellscript")
    return PlainTextResponse(
        "# install-phone-bridge.sh not bundled in this build\n",
        status_code=404,
        media_type="text/plain",
    )


# /metrics ownership notes
# ─────────────────────────
# W13 (roadmap §3.1 #4) flipped this endpoint from default-OFF to
# default-ON-on-loopback. Two switches gate it:
#
#   FERAL_METRICS_ENDPOINT  — kill switch. Set to "0"/"false" to silence
#                              both the endpoint and every emit() write.
#                              Defaults to "1" (on).
#   FERAL_METRICS_PUBLIC    — exposure switch. Off-loopback callers get
#                              404 unless this is set to "1"/"true".
#                              Defaults to "0".
#
# Off-loopback default is 404 (NOT 401/403) so the response is
# indistinguishable from "endpoint not mounted" — preserving the
# pre-W13 public-internet behaviour for unconfigured installs.
#
# The body concatenates the W13 prometheus_client REGISTRY (Grafana /
# alert-rule surface) with the legacy in-memory snapshot lines so
# pre-W13 ``increment()``/``observe()`` call sites stay scrapeable
# during the cross-module emit() rollout (W13.1 follow-up).

_METRICS_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _metrics_endpoint_killed() -> bool:
    val = os.getenv("FERAL_METRICS_ENDPOINT", "1").strip().lower()
    return val in ("0", "false", "off", "no")


def _metrics_public_enabled() -> bool:
    val = os.getenv("FERAL_METRICS_PUBLIC", "0").strip().lower()
    return val in ("1", "true", "yes", "on")


@app.get("/metrics")
async def metrics_endpoint(request: Request):
    if _metrics_endpoint_killed():
        return JSONResponse({"error": "Metrics endpoint disabled. Set FERAL_METRICS_ENDPOINT=1"}, status_code=404)
    client_host = request.client.host if request.client else None
    if client_host not in _METRICS_LOOPBACK_HOSTS and not _metrics_public_enabled():
        return JSONResponse({"error": "Not Found"}, status_code=404)

    from starlette.responses import PlainTextResponse
    body, content_type = _render_prometheus()

    # Append legacy in-memory snapshot lines so pre-W13 increment()/observe()
    # callers remain scrapeable until W13.1 migrates them to emit().
    snap = _metrics_snapshot()
    legacy_lines: list[str] = []
    for name, v in snap["counters"].items():
        legacy_lines.append(f"# TYPE {name} counter")
        legacy_lines.append(f"{name} {v}")
    for name, h in snap["histograms"].items():
        legacy_lines.append(f"# TYPE {name} histogram")
        legacy_lines.append(f"{name}_count {h['count']}")
        legacy_lines.append(f"{name}_mean {h['mean']}")
    if legacy_lines:
        body = body + "\n".join(legacy_lines) + "\n"

    return PlainTextResponse(body, media_type=content_type)


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
                    # Pass an explicit context so the Supervisor audit log
                    # can distinguish cron-driven turns from user / web.
                    # Without this, source defaulted to "web".
                    cron_context = {
                        "source": "cron",
                        "actor": "system",
                        "routine_id": job.id,
                        "routine_type": job.job_type,
                    }
                    loop = _aio.new_event_loop()
                    try:
                        loop.run_until_complete(
                            state.orchestrator.handle_command(session_id, prompt, context=cron_context)
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
    state.register_background_task(
        asyncio.create_task(_state_heartbeat(), name="feral-state-heartbeat")
    )

    async def _provider_catalog_refresher():
        """Refresh the ProviderCatalog every 6h while the Brain is up.

        Owned by W1 (Roadmap §3.5 P0 / Appendix A.1): the daily
        provider-research.yml cron keeps the bundled `model_catalog.json`
        current for fresh clones, but a brain that's been running for
        days would otherwise serve a 24h+ stale model list to the v2
        Settings picker. ProviderCatalog.refresh_async() skips providers
        without a configured key so this is a no-op for adapters the
        user hasn't set up.
        """
        # Initial nudge so Settings sees fresh data shortly after boot
        # without waiting six hours.
        await asyncio.sleep(60)
        while True:
            try:
                if state.provider_catalog is not None:
                    await state.provider_catalog.refresh_async()
            except Exception as exc:
                logger.debug("provider catalog refresh failed: %s", exc)
            await asyncio.sleep(6 * 3600)
    state.register_background_task(
        asyncio.create_task(_provider_catalog_refresher(), name="feral-provider-catalog-refresher")
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown: stop producers, close LLM, then teardown I/O.

    A7 — Ordering matters. Before this pass, ``llm.close()`` ran first
    while ambient loops (proactive, screen loop, scheduled tasks,
    scene analysis, channel handlers) were still firing HTTP requests
    through the shared client, producing ``Cannot send a request, as
    the client has been closed`` tracebacks. We now:

      1. Stop every background producer (registry + engines + integrations
         + channel manager + embed queue).
      2. THEN close the LLM + MCP so no in-flight request can leak.
      3. Stop taskflows.
      4. Tear down sync/mDNS via the async-safe paths so zeroconf
         doesn't stall the loop (``EventLoopBlocked``).
      5. Snapshot ConsciousnessStore last, while SQLite pools are alive.
    """
    logger.info("FERAL Brain shutting down gracefully...")

    # (a) Cancel every registered background task (heartbeat, catalog
    # refresher, ideas brief, screen loop bootstrap, demo, proactive
    # evaluation loop, etc.). This flips producer state before we
    # touch the shared HTTP client.
    try:
        cancelled = await state.shutdown_background_tasks(timeout=5.0)
        if cancelled:
            logger.info("Shutdown: cancelled %d background task(s)", cancelled)
    except Exception as exc:
        logger.warning("Shutdown: background-task cancellation failed: %s", exc)

    # (a.1) Ask the engines that own their own task handles to stop so
    # they can drain any in-flight tick cleanly. These are idempotent
    # with the registry cancellation above — if the task is already
    # cancelled, stop() becomes a no-op.
    for owner_name in ("proactive", "screen_loop"):
        owner = getattr(state, owner_name, None)
        if owner is None:
            continue
        stop = getattr(owner, "stop", None)
        if not callable(stop):
            continue
        try:
            result = stop()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            logger.debug("Shutdown: %s.stop() raised: %s", owner_name, exc)

    # (a.2) Messaging + channel integrations that spawn their own
    # polling loops.
    for bridge_name in ("channel_manager", "mqtt_bridge", "email_watcher"):
        bridge = getattr(state, bridge_name, None)
        if bridge is None:
            continue
        stop = getattr(bridge, "stop_all", None) or getattr(bridge, "stop", None)
        if not callable(stop):
            continue
        try:
            result = stop()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            logger.warning("Shutdown: %s stop failed: %s", bridge_name, exc)

    # (a.3) Close the MemoryStore so the embed queue's background
    # coroutine stops before the event loop starts tearing down.
    try:
        if state.memory is not None:
            close = getattr(state.memory, "close", None)
            if callable(close):
                close()
    except Exception as exc:
        logger.debug("Shutdown: memory.close() raised: %s", exc)

    # (b) LLM client — safe now that every producer is stopped.
    if state.orchestrator and state.orchestrator.llm:
        try:
            await state.orchestrator.llm.close()
        except Exception as exc:
            logger.debug("Shutdown: llm.close() raised: %s", exc)

    # (c) MCP connections.
    if state.mcp_client:
        try:
            await state.mcp_client.disconnect_all()
        except Exception as exc:
            logger.debug("Shutdown: mcp disconnect_all raised: %s", exc)

    # (d) Taskflows. These may call back into skills/LLM; we keep them
    # after LLM close because TaskFlowRuntime.stop() is expected to
    # cancel outstanding runs rather than start new ones.
    if state.taskflows:
        try:
            await state.taskflows.stop()
        except Exception as exc:
            logger.debug("Shutdown: taskflows.stop raised: %s", exc)

    # (e) Sync engine mDNS teardown (async-safe — see memory/sync.py).
    if state.sync_engine:
        try:
            await state.sync_engine.stop_discovery()
        except Exception as exc:
            logger.warning("Shutdown: sync_engine.stop_discovery failed: %s", exc)

    # (f) Persist consciousness before the SQLite connection pools die.
    try:
        store = getattr(state, "consciousness", None)
        if store is not None:
            from memory.consciousness import default_snapshot_path
            import json as _json
            blob = store.snapshot()
            path = default_snapshot_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_json.dumps(blob, indent=2))
            logger.info(
                "Consciousness snapshot written: %d entities -> %s",
                blob.get("count", 0), path,
            )
    except Exception as exc:
        logger.warning("Consciousness snapshot-on-shutdown failed: %s", exc)
    try:
        from services.mdns import stop_advertisement
        stop_advertisement()
    except Exception:
        pass
    logger.info("Shutdown complete.")


# ─────────────────────────────────────────────
# Main Client WebSocket
# ─────────────────────────────────────────────

@app.websocket("/v1/session")
async def client_session(ws: WebSocket, token: str = Query(default=None)):
    await ws.accept()

    client_host = ws.client.host if ws.client else None
    _ws_authed = False

    if is_localhost(client_host) and local_bypass_enabled():
        _ws_authed = True
    elif token and (verify_session(token) or token == FERAL_API_KEY):
        _ws_authed = True

    if not _ws_authed:
        try:
            first_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if first_msg.get("type") == "auth":
                t = first_msg.get("token", "")
                if verify_session(t) or t == FERAL_API_KEY:
                    _ws_authed = True
        except Exception:
            pass

    if not _ws_authed:
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

    if greeting:
        state.memory.working_push(session_id, {"role": "assistant", "content": greeting})

    try:
        while True:
            try:
                raw = await ws.receive_json()
            except (ValueError, TypeError) as e:
                logger.warning("Malformed message from session %s: %s", session_id[:8], e)
                await state.send_to_session(session_id, FeralMessage(
                    type="error", payload={"text": "Invalid message format. Please send valid JSON."}
                ))
                continue
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
                            try:
                                frame = state.perception.get_frame(session_id) if getattr(state, "perception", None) else None
                            except Exception:
                                frame = None
                            system_prompt = state.identity_workspace.build_system_prompt(
                                frame=frame,
                                skill_registry=getattr(state, "skills", None),
                            )

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
                        app_id=payload.app_id,
                        screen_id=payload.screen_id,
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
                        await state.orchestrator._emit_brain_event(session_id, "device_telemetry", {"source": "client"})
                    state.perception.update_sensors(session_id, bio)
                    if state.somatic_engine:
                        state.somatic_engine.update_from_perception_frame(session_id, bio)
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
    except Exception as exc:
        logger.error(f"Unexpected error in session {session_id[:8]}: {exc}", exc_info=True)
        state.sessions.pop(session_id, None)
        state.audio.clear_session(session_id)
        state.perception.clear(session_id)
        state.memory.working_clear(session_id)


# ─────────────────────────────────────────────
# Daemon WebSocket (HUP nodes)
# ─────────────────────────────────────────────

NODE_API_KEY = os.environ.get("NODE_API_KEY", "")


async def _send_protocol_error(ws: WebSocket, code: int, message: str, *, name: str = "bad_schema") -> None:
    """Emit an HUP §8 error frame to the daemon."""
    try:
        await ws.send_json({
            "hup_version": "1.2.0",
            "type": "error",
            "ts": __import__("time").time(),
            "payload": {
                "code": code,
                "name": name,
                "message": message,
                "recoverable": False,
                "ref_action_id": None,
            },
        })
    except Exception:
        pass


@app.websocket("/v1/node")
async def daemon_session(ws: WebSocket, api_key: str = Query(default=None)):
    if not api_key:
        api_key = ws.headers.get("authorization", "").replace("Bearer ", "")
    if not api_key:
        api_key = ws.headers.get("x-api-key", "")
    if not api_key:
        protocols = ws.headers.get("sec-websocket-protocol", "")
        if protocols.startswith("feral-token-"):
            api_key = protocols.replace("feral-token-", "")

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
            try:
                raw = await ws.receive_json()
            except (ValueError, KeyError):
                await _send_protocol_error(ws, 1002, "Malformed JSON frame")
                continue
            msg, payload = parse_message(raw)

            if msg.type in ("node_register", "register") and isinstance(payload, NodeRegisterPayload):
                node_id = payload.node_id
                state.daemons[node_id] = ws
                # Stash the HUP-declared node_type on the WebSocket so
                # /api/devices/connected can report the real type instead
                # of the legacy "phone"-for-everyone default. `manufacturer`
                # and `model` are HUP v1 fields that the narrower
                # models.protocol.NodeRegisterPayload doesn't yet mirror —
                # getattr falls back to "" when absent, so we pick them up
                # from v1.1+ daemons without tripping on v1.0 payloads.
                setattr(ws, "_feral_node_type", (getattr(payload, "node_type", None) or "unknown").lower())
                setattr(ws, "_feral_capabilities", list(getattr(payload, "capabilities", []) or []))
                setattr(ws, "_feral_platform", getattr(payload, "platform", "") or "")
                setattr(ws, "_feral_manufacturer", getattr(payload, "manufacturer", "") or "")
                setattr(ws, "_feral_model", getattr(payload, "model", "") or "")
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

                session_token = str(__import__("uuid").uuid4())
                await ws.send_json({
                    "hup_version": "1.2.0",
                    "type": "node_ack",
                    "ts": __import__("time").time(),
                    "payload": {
                        "node_id": node_id,
                        "session_token": session_token,
                        "hup_version": "1.2.0",
                        "heartbeat_ms": 10000,
                        "server_time": __import__("time").time(),
                        "capabilities": list(payload.capabilities),
                        "granted_capabilities": list(payload.capabilities),
                        "denied_capabilities": [],
                    },
                })

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
                        if state.somatic_engine:
                            state.somatic_engine.update_from_perception_frame(sid, sensors)
                        if state.orchestrator:
                            await state.orchestrator._emit_brain_event(sid, "device_telemetry", {"source": node_id, "hr": hr or 0})
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
                        if state.somatic_engine:
                            state.somatic_engine.update_from_perception_frame(sid, sensors_map)
                        if state.orchestrator:
                            await state.orchestrator._emit_brain_event(sid, "device_telemetry", {"source": node_id, "sensor": sensor_name})

            elif msg.type == "sensor_batch":
                payload_dict = raw.get("payload", {})
                readings = payload_dict.get("readings", {})
                logger.info(f"Sensor batch from {node_id}: {list(readings.keys())}")
                if state.orchestrator:
                    state.orchestrator.update_biometric(node_id, readings)
                if node_id:
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.perception.update_sensors(sid, readings)
                        if state.somatic_engine:
                            state.somatic_engine.update_from_perception_frame(sid, readings)
                        if state.orchestrator:
                            await state.orchestrator._emit_brain_event(sid, "device_telemetry", {"source": node_id, "sensors": list(readings.keys())})
                _record_biometrics_to_baseline(readings)

            elif msg.type == "node_heartbeat":
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

            elif msg.type == "hup_action_response":
                result_payload = raw.get("payload", {})
                action_id = result_payload.get("action_id", "") or result_payload.get("request_id", "")
                if state.hardware_mesh and action_id:
                    state.hardware_mesh.resolve_invoke(action_id, result_payload)
                if state.orchestrator:
                    await state.orchestrator.handle_daemon_result(
                        node_id=node_id,
                        result=result_payload,
                        session_id=msg.session_id,
                    )

            elif msg.type == "node_bye":
                logger.info("node_bye from %s: %s", node_id, raw.get("payload", {}).get("reason", ""))
                if node_id:
                    state.daemons.pop(node_id, None)
                    if state.skill_executor:
                        state.skill_executor.unregister_daemon(node_id)
                    if state.hardware_mesh:
                        state.hardware_mesh.on_node_disconnected(node_id)
                await ws.close(code=1000)
                return

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

            elif msg.type == "video_frame":
                # HUP v1.1 §5.4.2 — route video frames into the vision buffer,
                # same sink as the legacy vision_frame branch above.
                _handle_video_frame(node_id, raw.get("payload", {}), msg.msg_id)

            elif msg.type == "audio_frame":
                # HUP v1.1 §5.4.1 — route audio frames into the audio pipeline
                # when available; otherwise log and move on.
                _handle_audio_frame(node_id, raw.get("payload", {}))

            elif msg.type == "device_event":
                # HUP v1.1 `device_event` envelope. Unwrap to the concrete
                # event_type and dispatch. Biometric / sensor / gesture
                # types land in the same sinks as the legacy `telemetry`
                # and `gesture` branches above. Unknown event_types are
                # ignored per the forward-compat rule in HUP_SPEC.md §1.
                de_payload = raw.get("payload", {}) or {}
                ev_type = de_payload.get("event_type", "")
                if ev_type == "audio_frame":
                    _handle_audio_frame(node_id, de_payload)
                elif ev_type == "video_frame":
                    _handle_video_frame(node_id, de_payload, msg.msg_id)
                elif ev_type in {
                    "heart_rate", "spo2", "skin_temperature", "steps",
                    "temperature", "accelerometer", "gesture",
                }:
                    _handle_biometric_device_event(node_id, ev_type, de_payload)
                else:
                    logger.debug(
                        "Ignoring unknown device_event event_type=%r from %s",
                        ev_type, node_id,
                    )

            else:
                logger.debug("Unknown HUP msg type=%r from %s", msg.type, node_id)
                await _send_protocol_error(ws, 1002, f"Unknown message type: {msg.type}")

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


AUDIO_FRAME_MAX_BYTES = 64 * 1024  # HUP_SPEC.md §5.4.1 cap
VIDEO_FRAME_MAX_BYTES = 512 * 1024  # HUP_SPEC.md §5.4.2 cap (matches existing VISION_MAX_FRAME_KB)


def _unwrap_hup_frame(raw_payload: dict) -> dict:
    """Accept both ``device_event`` shapes.

    The HUP v1.1 Python SDK wraps media fields inside
    ``DeviceEventPayload.data`` (so the wire carries
    ``payload.data.data_b64``), while legacy direct-send daemons emit
    the fields flat at the top of the payload (``payload.data_b64``).
    Normalise to a single flat dict here so the downstream vision /
    audio sinks keep working regardless of which client shipped the
    frame. Top-level fields always win, so partially-migrated daemons
    that send both shapes are tolerated.
    """
    if not isinstance(raw_payload, dict):
        return {}
    nested = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else {}
    if not nested:
        return raw_payload
    merged: dict = {}
    merged.update(nested)
    for k, v in raw_payload.items():
        if k == "data":
            continue
        merged[k] = v
    return merged


def _handle_video_frame(node_id, frame_payload: dict, msg_id=None) -> None:
    """Dispatch a HUP v1.1 ``video_frame`` payload into the vision buffer.

    Shares the existing vision-buffer sink with the legacy ``vision_frame``
    branch so downstream perception code stays unchanged. Over-cap frames
    are dropped with a warning per HUP_SPEC.md error code 4020.

    Accepts both the flat and nested ``device_event`` payload shapes
    via :func:`_unwrap_hup_frame` — the HUP v1.1 Python SDK serialises
    its frames nested under ``payload.data`` while the legacy direct
    ``vision_frame`` path carries them flat.
    """
    frame_payload = _unwrap_hup_frame(frame_payload)
    data_b64 = frame_payload.get("data_b64", "") or ""
    if len(data_b64) > VIDEO_FRAME_MAX_BYTES:
        logger.warning(
            "Rejecting oversized video_frame from %s: %dB > %dB (HUP error 4020)",
            node_id, len(data_b64), VIDEO_FRAME_MAX_BYTES,
        )
        return

    effective_node = node_id or frame_payload.get("node_id", "unknown")
    state.vision_buffer.push(effective_node, frame_payload)

    for sid in state.get_sessions_for_daemon(effective_node):
        state.perception.update_vision(sid, state.vision_buffer, effective_node)

    change_event = state.change_detector.should_analyze(
        effective_node, data_b64, frame_payload.get("codec", "jpeg"),
    )
    if change_event and state.scene and state.scene.available:
        mode = "tracking" if change_event.trigger_reason == "scene_change" else "general"
        asyncio.ensure_future(
            _analyze_scene_background(effective_node, frame_payload, mode=mode)
        )

    if msg_id and state.orchestrator:
        state.orchestrator.resolve_pending_frame(msg_id, frame_payload)


def _handle_audio_frame(node_id, frame_payload: dict) -> None:
    """Dispatch a HUP v1.1 ``audio_frame`` payload into the audio pipeline.

    Accepts both SDK-nested and flat payload shapes via
    :func:`_unwrap_hup_frame`. Falls back to a debug log when
    ``state.audio`` does not expose an ``ingest_frame`` hook — the
    Brain boot tolerates the pipeline being absent, so we must too.
    """
    frame_payload = _unwrap_hup_frame(frame_payload)
    data_b64 = frame_payload.get("data_b64", "") or ""
    if len(data_b64) > AUDIO_FRAME_MAX_BYTES:
        logger.warning(
            "Rejecting oversized audio_frame from %s: %dB > %dB (HUP error 4020)",
            node_id, len(data_b64), AUDIO_FRAME_MAX_BYTES,
        )
        return

    effective_node = node_id or frame_payload.get("node_id", "unknown")
    audio = getattr(state, "audio", None)
    ingest = getattr(audio, "ingest_frame", None)
    if callable(ingest):
        try:
            ingest(effective_node, frame_payload)
        except Exception as exc:
            logger.warning("audio.ingest_frame raised for %s: %s", effective_node, exc)
    else:
        logger.debug(
            "Received audio_frame from %s but state.audio has no ingest_frame hook; dropping.",
            effective_node,
        )


def _handle_biometric_device_event(node_id, event_type: str, frame_payload: dict) -> None:
    """Dispatch ``device_event`` payloads with biometric / sensor event types.

    Accepts both SDK-nested and flat shapes. Lands in the same sinks
    as the legacy ``telemetry`` branch: ``state.perception.update_sensors``
    per session and ``_record_biometrics_to_baseline`` for rolling stats.
    Handles ``heart_rate``, ``spo2``, ``skin_temperature``, ``steps``,
    ``temperature``, ``accelerometer``, ``button_press``.
    """
    frame_payload = _unwrap_hup_frame(frame_payload)
    effective_node = node_id or frame_payload.get("node_id", "unknown")
    # Reshape into the same ``sensors`` dict the legacy ``telemetry``
    # branch already expects: numeric keys land at the top level.
    sensors: dict = {}
    # HR carried either as {"bpm": int} (per HUP_SPEC examples) or as a
    # flat number under the event_type key — accept both.
    if event_type == "heart_rate":
        bpm = frame_payload.get("bpm")
        if bpm is None and isinstance(frame_payload.get("value"), (int, float)):
            bpm = frame_payload.get("value")
        if bpm is not None:
            sensors["ppg_heart_rate"] = bpm
    elif event_type == "spo2":
        val = frame_payload.get("current") or frame_payload.get("spo2") or frame_payload.get("value")
        if val is not None:
            sensors["spo2_pct"] = val
    elif event_type == "skin_temperature":
        val = frame_payload.get("celsius") or frame_payload.get("value")
        if val is not None:
            sensors["skin_temperature_c"] = val
    elif event_type == "steps":
        val = frame_payload.get("count") or frame_payload.get("value")
        if val is not None:
            sensors["steps"] = val
    elif event_type == "temperature":
        val = frame_payload.get("celsius") or frame_payload.get("value")
        if val is not None:
            sensors["temperature"] = val
    elif event_type == "accelerometer":
        accel = [
            frame_payload.get("x", 0.0),
            frame_payload.get("y", 0.0),
            frame_payload.get("z", 0.0),
        ]
        sensors["accel_xyz"] = accel
    elif event_type == "gesture":
        # Route straight to the gesture pipeline. No baseline recording.
        gesture = frame_payload.get("gesture") or frame_payload.get("name") or ""
        if gesture and effective_node:
            for sid in state.get_sessions_for_daemon(effective_node):
                state.perception.update_gesture(sid, gesture)
        return

    if not sensors:
        logger.debug(
            "Dropping device_event %r from %s — could not extract a value from %r",
            event_type, effective_node, frame_payload,
        )
        return

    if effective_node:
        for sid in state.get_sessions_for_daemon(effective_node):
            state.perception.update_sensors(sid, sensors)
            if state.somatic_engine:
                state.somatic_engine.update_from_perception_frame(sid, sensors)

    _record_biometrics_to_baseline(sensors)


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
# Bundled Web UI
# ─────────────────────────────────────────────
#
# v2 (feral-client-v2) is the default UI. When ``webui_v2/index.html`` is on
# disk the Brain serves it at / directly, and v1 (``webui/``) is never
# reached. If webui_v2/ isn't built (fresh clone), fall back to v1 so users
# still see something. v1 source is kept in the tree for history only.
#
# The directory is named ``webui_v2`` (underscore) so setuptools treats it
# as a real Python package — without that, ``pip install feral-ai`` ships a
# wheel missing the v2 bundle and the fallback kicks in on end-user machines.
# See feral-core/pyproject.toml [tool.setuptools.package-data] for the mirror.
#
# The ``/v2/`` alias is retained so existing bookmarks keep working even
# when v2 is already the default at /.

_webui_v2_dir = Path(__file__).parent.parent / "webui_v2"
_webui_legacy_dir = Path(__file__).parent.parent / "webui"
_webui_v2_ready = _webui_v2_dir.is_dir() and (_webui_v2_dir / "index.html").exists()
_webui_legacy_ready = _webui_legacy_dir.is_dir() and (_webui_legacy_dir / "index.html").exists()

_webui_dir = _webui_v2_dir if _webui_v2_ready else _webui_legacy_dir
_webui_ready = _webui_v2_ready or _webui_legacy_ready
_webui_variant = "v2" if _webui_v2_ready else ("v1-legacy" if _webui_legacy_ready else "missing")
_webui_route_mode = "spa" if _webui_ready else "fallback"
logger.info("Web UI routing mode=%s variant=%s path=%s", _webui_route_mode, _webui_variant, _webui_dir)

if _webui_ready and (_webui_dir / "assets").is_dir():
    from starlette.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(_webui_dir / "assets")), name="webui-assets")
    logger.info(f"Web UI ({_webui_variant}) bundled from {_webui_dir} — open {brain_public_base_url()}")
else:
    logger.warning(
        f"Web UI not found at {_webui_dir}. Dashboard will show setup instructions. "
        "Run 'make bundle-webui' to build the dashboard."
    )

# Keep the /v2/ alias so ``http://host/v2/`` still resolves when v2 is
# already the default at /. Harmless: both paths end up serving the same
# bundle because feral-client-v2 uses relative asset URLs.
if _webui_v2_ready:
    from starlette.staticfiles import StaticFiles
    app.mount("/v2", StaticFiles(directory=str(_webui_v2_dir), html=True), name="webui-v2")
    logger.info(f"Web UI v2 alias also available at {brain_public_base_url()}/v2/")

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
    # Honest 404 for unknown API and protocol paths. Until this guard
    # was added the catch-all returned 200 SPA HTML for any unknown
    # ``/api/...`` GET, which silently broke SDKs that polled missing
    # endpoints (parsers crashed on HTML; flows hung indefinitely).
    if (
        full_path.startswith("api/")
        or full_path.startswith("v1/")
        or full_path.startswith("v2/api/")
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "no_such_route", "path": "/" + full_path},
        )
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
    print(f"""
    ╔══════════════════════════════════════╗
    ║        FERAL v{__version__:<22s}║
    ║   Open AI Agent · Computer Use      ║
    ║   Voice · GenUI · Hardware          ║
    ╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host=brain_bind_host(), port=brain_port(), log_level="info")
