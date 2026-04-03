"""
THEORA Brain — Core WebSocket Server
======================================
The local-first agentic brain. Runs on the user's machine.
Clients (phone, web, daemon, glasses) connect via WebSocket.

v0.3.0 — Full perception engine, audio pipeline, 4-tier memory.
"""

import asyncio
import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

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
from agents.orchestrator import Orchestrator
from agents.learner import Learner
from agents.skill_generator import SkillGenerator
from skills.registry import SkillRegistry
from memory.store import MemoryStore
from perception.fusion import PerceptionEngine
from perception.audio_pipeline import AudioPipeline
from perception.scene import SceneAnalyzer
from config.loader import ConfigLoader
from security.vault import BlindVault, PermissionTier, ExecutionSandbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("theora.brain")


# ─────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────

app = FastAPI(
    title="THEORA Brain",
    description="Local-first agentic intelligence core — self-learning, streaming, scene-aware",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Vision Buffer — Ring buffer of recent frames per node
# ─────────────────────────────────────────────

VISION_MAX_FRAME_KB = int(os.environ.get("THEORA_VISION_MAX_FRAME_KB", "512"))

class VisionBuffer:
    """Stores the latest N frames per hardware node in a memory-bounded ring buffer."""

    def __init__(self, max_frames_per_node: int = 3):
        self._max = max_frames_per_node
        self.frames: dict[str, deque] = {}

    def push(self, node_id: str, frame: dict):
        if node_id not in self.frames:
            self.frames[node_id] = deque(maxlen=self._max)
        self.frames[node_id].append(frame)

    def latest(self, node_id: str) -> Optional[dict]:
        buf = self.frames.get(node_id)
        return buf[-1] if buf else None

    def latest_data_url(self, node_id: str) -> Optional[str]:
        frame = self.latest(node_id)
        if not frame or not frame.get("data_b64"):
            return None
        encoding = frame.get("encoding", "jpeg")
        mime = f"image/{encoding}"
        return f"data:{mime};base64,{frame['data_b64']}"

    def node_ids_with_frames(self) -> list[str]:
        return [nid for nid, buf in self.frames.items() if buf]


# ─────────────────────────────────────────────
# State
# ─────────────────────────────────────────────

class BrainState:
    def __init__(self):
        self.config = ConfigLoader()
        self.config.discover()
        self.sessions: dict[str, WebSocket] = {}
        self.daemons: dict[str, WebSocket] = {}
        self.devices: dict[str, dict] = {}
        self.skill_registry = SkillRegistry()
        self.memory = MemoryStore()
        self.vision_buffer = VisionBuffer()
        self.perception = PerceptionEngine()
        self.audio = AudioPipeline()
        self.scene: Optional[SceneAnalyzer] = None
        self.learner: Optional[Learner] = None
        self.skill_gen: Optional[SkillGenerator] = None
        self.vault: Optional[BlindVault] = None
        self.sandbox: Optional[ExecutionSandbox] = None
        self.orchestrator: Optional[Orchestrator] = None

        # Map daemon node_id → list of sessions interested in its data
        self._daemon_session_bindings: dict[str, set[str]] = {}

    async def init(self):
        self.skill_registry.load_builtin_skills()

        from agents.llm_provider import LLMProvider
        _shared_llm = LLMProvider()
        self.learner = Learner(llm=_shared_llm, memory=self.memory)
        self.scene = SceneAnalyzer(llm=_shared_llm)
        scene_cooldown = int(os.environ.get("THEORA_SCENE_COOLDOWN", "10"))
        self.scene.set_cooldown(scene_cooldown)

        self.skill_gen = SkillGenerator(
            llm=_shared_llm,
            skill_registry=self.skill_registry,
        )

        self.vault = BlindVault()
        self.sandbox = ExecutionSandbox(
            max_tier=os.environ.get("THEORA_MAX_TIER", "active")
        )

        self.orchestrator = Orchestrator(
            skill_registry=self.skill_registry,
            send_to_client=self.send_to_session,
            daemons=self.daemons,
            memory=self.memory,
            vision_buffer=self.vision_buffer,
            perception=self.perception,
            learner=self.learner,
        )
        stats = self.memory.stats()
        logger.info(
            f"Brain v0.4.0 initialized — {len(self.skill_registry.skills)} skills, "
            f"{stats['notes']} notes, {stats['knowledge_triples']} knowledge triples, "
            f"{stats['episodes']} episodes | Self-learning: ON"
        )

    async def send_to_session(self, session_id: str, msg: TheoraMessage):
        ws = self.sessions.get(session_id)
        if ws:
            await ws.send_json(msg.model_dump())

    async def send_to_daemon(self, node_id: str, msg: TheoraMessage):
        ws = self.daemons.get(node_id)
        if ws:
            await ws.send_json(msg.model_dump())

    def bind_session_to_daemon(self, session_id: str, node_id: str):
        if node_id not in self._daemon_session_bindings:
            self._daemon_session_bindings[node_id] = set()
        self._daemon_session_bindings[node_id].add(session_id)

    def get_sessions_for_daemon(self, node_id: str) -> set[str]:
        return self._daemon_session_bindings.get(node_id, set())


state = BrainState()


# ─────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await state.init()


# ─────────────────────────────────────────────
# Health & Discovery
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    stats = state.memory.stats()
    return {
        "name": "THEORA Brain",
        "version": "0.4.0",
        "status": "running",
        "sessions": len(state.sessions),
        "daemons": list(state.daemons.keys()),
        "devices": len(state.devices),
        "skills": len(state.skill_registry.skills),
        "memory": stats,
        "audio_available": state.audio.available,
    }


# ─────────────────────────────────────────────
# Setup & Configuration API
# ─────────────────────────────────────────────

@app.get("/api/setup/status")
async def setup_status():
    """Check if initial setup has been completed."""
    return {
        "setup_complete": state.config.setup_complete,
        "settings": state.config.to_client_safe_dict(),
    }


@app.get("/api/config")
async def get_config():
    """Get current configuration (safe for client, no secrets)."""
    return state.config.to_client_safe_dict()


@app.post("/api/config/update")
async def update_config(body: dict):
    """Update a setting. Body: {section, key, value}"""
    section = body.get("section", "")
    key = body.get("key", "")
    value = body.get("value")
    if not section or not key:
        return {"error": "section and key are required"}
    state.config.update_settings(section, key, value)
    return {"ok": True, "section": section, "key": key, "value": value}


@app.post("/api/config/credentials")
async def save_credentials(body: dict):
    """Save API credentials. Body: {OPENAI_API_KEY: "...", skill_keys: {...}}"""
    creds = {}
    for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        if key in body:
            creds[key] = body[key]
            os.environ[key] = body[key]
    if "skill_keys" in body:
        creds["skill_keys"] = body["skill_keys"]
        for skill_id, api_key in body["skill_keys"].items():
            os.environ[f"THEORA_KEY_{skill_id}"] = api_key
    state.config.save_credentials(creds)
    return {"ok": True, "keys_saved": list(creds.keys())}


@app.post("/api/config/validate-key")
async def validate_key(body: dict):
    """Validate an LLM API key by making a test request."""
    provider = body.get("provider", "openai")
    api_key = body.get("api_key", "")
    if not api_key:
        return {"valid": False, "error": "No API key provided"}

    import httpx
    try:
        if provider == "openai":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"valid": True, "provider": "openai", "models": len(resp.json().get("data", []))}
                return {"valid": False, "error": f"API returned {resp.status_code}"}
        elif provider == "groq":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                return {"valid": resp.status_code == 200, "provider": "groq"}
        elif provider == "ollama":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    body.get("base_url", "http://localhost:11434") + "/api/tags",
                    timeout=5.0,
                )
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {"valid": True, "provider": "ollama", "models": len(models)}
                return {"valid": False, "error": "Ollama not reachable"}
        return {"valid": False, "error": f"Unknown provider: {provider}"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@app.post("/api/setup/complete")
async def complete_setup(body: dict):
    """Mark setup as complete and apply settings."""
    settings = body.get("settings", {})
    credentials = body.get("credentials", {})

    if settings:
        state.config.save_user_settings(settings)
    if credentials:
        for key in ("OPENAI_API_KEY", "GROQ_API_KEY"):
            if credentials.get(key):
                os.environ[key] = credentials[key]
        state.config.save_credentials(credentials)

    state.config.mark_setup_complete()

    # Re-discover config with new values
    state.config.discover()

    return {"ok": True, "setup_complete": True}


# ─────────────────────────────────────────────
# Skill Generation API (Self-Evolving Agent)
# ─────────────────────────────────────────────

@app.post("/api/skills/generate")
async def generate_skill(body: dict):
    """Generate a new skill from a capability description."""
    capability = body.get("capability", "")
    service = body.get("service", "")
    if not capability:
        return {"error": "capability is required"}
    if not state.skill_gen:
        return {"error": "Skill generator not initialized"}
    manifest = await state.skill_gen.generate_skill(capability, service)
    if manifest:
        return {"ok": True, "manifest": manifest, "needs_approval": True}
    return {"ok": False, "error": "Failed to generate skill"}


@app.post("/api/skills/approve")
async def approve_skill(body: dict):
    """Approve a pending generated skill — registers it live."""
    skill_id = body.get("skill_id", "")
    if not skill_id:
        return {"error": "skill_id is required"}
    success = await state.skill_gen.approve_skill(skill_id)
    return {"ok": success, "skill_id": skill_id, "registered": success}


@app.post("/api/skills/reject")
async def reject_skill(body: dict):
    """Reject a pending generated skill."""
    skill_id = body.get("skill_id", "")
    state.skill_gen.reject_skill(skill_id)
    return {"ok": True, "skill_id": skill_id}


@app.get("/api/skills/pending")
async def pending_skills():
    """Get all skills waiting for user approval."""
    if not state.skill_gen:
        return {"pending": []}
    return {"pending": state.skill_gen.get_pending_skills()}


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
    audit_path = Path(os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))) / "audit.log"
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


@app.get("/api/system/info")
async def system_info():
    """Full system info for the dashboard."""
    stats = state.memory.stats()
    return {
        "version": "0.4.0",
        "config": state.config.to_client_safe_dict(),
        "memory": stats,
        "sessions": len(state.sessions),
        "nodes": list(state.daemons.keys()),
        "devices": len(state.devices),
        "skills": [
            {"skill_id": s.skill_id, "name": s.brand.name, "endpoints": len(s.endpoints)}
            for s in state.skill_registry.skills.values()
        ],
        "audio_available": state.audio.available,
    }


@app.get("/skills")
async def list_skills():
    return [
        {
            "skill_id": s.skill_id,
            "name": s.brand.name,
            "description": s.description,
            "endpoints": len(s.endpoints),
            "trigger_phrases": s.trigger_phrases,
        }
        for s in state.skill_registry.skills.values()
    ]


# ─────────────────────────────────────────────
# Memory API (all tiers)
# ─────────────────────────────────────────────

@app.post("/internal/memory/save")
async def memory_save(body: dict):
    content = body.get("content", "")
    tags = body.get("tags", [])
    importance = body.get("importance", "normal")
    if not content:
        return {"error": "content is required"}
    return state.memory.save(content=content, tags=tags, importance=importance)


@app.get("/internal/memory/search")
async def memory_search(query: str = "", limit: int = 10):
    if not query:
        return []
    return state.memory.search(query=query, limit=limit)


@app.get("/internal/memory/recent")
async def memory_recent(limit: int = 10):
    return state.memory.list_recent(limit=limit)


@app.delete("/internal/memory/{note_id}")
async def memory_delete(note_id: str):
    return {"deleted": state.memory.delete(note_id)}


@app.get("/internal/memory/stats")
async def memory_stats():
    return state.memory.stats()


@app.post("/internal/knowledge/store")
async def knowledge_store(body: dict):
    subject = body.get("subject", "")
    predicate = body.get("predicate", "")
    obj = body.get("object", "")
    if not all([subject, predicate, obj]):
        return {"error": "subject, predicate, and object are required"}
    return state.memory.knowledge_store(subject=subject, predicate=predicate, obj=obj)


@app.get("/internal/knowledge/query")
async def knowledge_query(subject: str = "", predicate: str = "", limit: int = 20):
    return state.memory.knowledge_query(subject=subject, predicate=predicate, limit=limit)


@app.get("/internal/knowledge/about/{entity}")
async def knowledge_about(entity: str, limit: int = 20):
    return state.memory.knowledge_about(entity, limit=limit)


@app.get("/internal/episodes/recent")
async def episodes_recent(limit: int = 10, session_id: str = ""):
    return state.memory.episode_recent(limit=limit, session_id=session_id or None)


@app.get("/internal/execution-log")
async def execution_log(skill_id: str = "", limit: int = 20):
    return state.memory.log_recent(skill_id=skill_id, limit=limit)


# ─────────────────────────────────────────────
# Main Client WebSocket
# ─────────────────────────────────────────────

@app.websocket("/v1/session")
async def client_session(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid4())
    state.sessions[session_id] = ws
    logger.info(f"Client connected: {session_id}")

    # Bind session to all currently connected daemons
    for node_id in state.daemons:
        state.bind_session_to_daemon(session_id, node_id)
        state.perception.update_connected_nodes(session_id, list(state.daemons.keys()))

    await ws.send_json(TheoraMessage(
        session_id=session_id,
        hop="brain",
        type="text_response",
        payload=TextResponsePayload(
            text="THEORA Brain connected. How can I help?"
        ).model_dump(),
    ).model_dump())

    try:
        while True:
            raw = await ws.receive_json()
            raw["session_id"] = session_id
            msg, payload = parse_message(raw)

            if msg.type == "text_command" and isinstance(payload, TextCommandPayload):
                state.memory.working_push(session_id, {"role": "user", "text": payload.text})
                await state.orchestrator.handle_command_stream(
                    session_id=session_id,
                    text=payload.text,
                    context=payload.context,
                )

                # Background: detect if user needs a skill that doesn't exist
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
                                session_id=session_id, hop="brain",
                                type="skill_proposal",
                                payload={"manifest": manifest, "reason": need.get("capability", "")},
                            ).model_dump())

            elif msg.type == "audio_chunk" and isinstance(payload, AudioChunkPayload):
                transcript = await state.audio.process_audio_chunk(
                    session_id=session_id,
                    chunk_b64=payload.data_b64,
                    chunk_index=payload.chunk_index,
                    is_final=payload.is_final,
                    encoding=payload.encoding,
                    sample_rate=payload.sample_rate,
                )

                if transcript:
                    # Send transcript back to client
                    await ws.send_json(TheoraMessage(
                        session_id=session_id, hop="brain", type="transcript",
                        payload=TranscriptPayload(text=transcript, is_partial=False).model_dump(),
                    ).model_dump())

                    state.memory.working_push(session_id, {"role": "user", "text": transcript, "source": "voice"})
                    state.perception.update_audio_context(session_id, transcript=transcript)

                    # Process through orchestrator
                    await state.orchestrator.handle_command(
                        session_id=session_id,
                        text=transcript,
                        context={"source": "voice"},
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

            elif msg.type == "biometric":
                bio = raw.get("payload", {})
                if state.orchestrator:
                    state.orchestrator.update_biometric(session_id, bio)
                state.perception.update_sensors(session_id, bio)

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {session_id}")
        # Trigger self-learning: extract knowledge + summarize session
        if state.orchestrator:
            try:
                await state.orchestrator.on_session_disconnect(session_id)
            except Exception as e:
                logger.warning(f"Session summarization failed: {e}")
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
        logger.warning(f"Unauthorized daemon connection attempt rejected")
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
                logger.info(f"Node registered: {node_id} ({payload.node_type}/{payload.platform}) — caps: {payload.capabilities}")

                # Bind to all active sessions and update perception
                for sid in state.sessions:
                    state.bind_session_to_daemon(sid, node_id)
                    state.perception.update_connected_nodes(sid, list(state.daemons.keys()))

                await ws.send_json(TheoraMessage(
                    hop="brain", type="text_response",
                    payload=TextResponsePayload(text=f"Node '{node_id}' registered successfully.").model_dump(),
                ).model_dump())

            elif msg.type == "execute_result":
                logger.info(f"Daemon result from {node_id}")
                if state.orchestrator:
                    await state.orchestrator.handle_daemon_result(
                        node_id=node_id,
                        result=raw.get("payload", {}),
                        session_id=msg.session_id,
                    )

            elif msg.type == "vision_frame":
                frame_payload = raw.get("payload", {})
                frame_b64_len = len(frame_payload.get("data_b64", ""))
                if frame_b64_len > VISION_MAX_FRAME_KB * 1024:
                    logger.warning(f"Rejecting oversized frame from {node_id}: {frame_b64_len}B")
                else:
                    effective_node = node_id or frame_payload.get("node_id", "unknown")
                    state.vision_buffer.push(effective_node, frame_payload)
                    frame_id = frame_payload.get("frame_id", "?")
                    logger.info(f"Vision frame from {node_id}: {frame_id} ({frame_b64_len}B)")

                    for sid in state.get_sessions_for_daemon(effective_node):
                        state.perception.update_vision(sid, state.vision_buffer, effective_node)

                    # Scene understanding via VLM (non-blocking)
                    if state.scene and state.scene.available:
                        asyncio.ensure_future(
                            _analyze_scene_background(effective_node, frame_payload)
                        )

                    if state.orchestrator:
                        state.orchestrator.resolve_pending_frame(msg.msg_id, frame_payload)

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

            # ── Phone Bridge: individual sensor reading ──
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

            # ── Phone Bridge: batch sensor readings ──
            elif msg.type == "sensor_batch":
                payload_dict = raw.get("payload", {})
                readings = payload_dict.get("readings", {})
                logger.info(f"Sensor batch from {node_id}: {list(readings.keys())}")
                if state.orchestrator:
                    state.orchestrator.update_biometric(node_id, readings)
                if node_id:
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.perception.update_sensors(sid, readings)

            # ── Phone Bridge: glasses connection status ──
            elif msg.type == "glasses_status":
                payload_dict = raw.get("payload", {})
                connected = payload_dict.get("glasses_connected", False)
                battery = payload_dict.get("battery_level", -1)
                model = payload_dict.get("glasses_model", "THEORA")
                logger.info(f"Glasses ({model}) {'connected' if connected else 'disconnected'} via {node_id}, battery={battery}%")

            # ── Phone Bridge: skill approval ──
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

    except WebSocketDisconnect:
        if node_id:
            logger.info(f"Daemon disconnected: {node_id}")
            state.daemons.pop(node_id, None)
            for sid in state.get_sessions_for_daemon(node_id):
                state.perception.update_connected_nodes(sid, list(state.daemons.keys()))


# ─────────────────────────────────────────────
# Background Scene Analysis
# ─────────────────────────────────────────────

async def _analyze_scene_background(node_id: str, frame_payload: dict):
    """Run VLM scene analysis on a vision frame and update perception."""
    try:
        data_b64 = frame_payload.get("data_b64", "")
        encoding = frame_payload.get("encoding", "jpeg")
        if not data_b64:
            return

        result = await state.scene.analyze_frame(
            data_b64=data_b64, encoding=encoding, node_id=node_id,
        )
        if result:
            for sid in state.get_sessions_for_daemon(node_id):
                frame = state.perception.get_frame(sid)
                frame.scene_description = result.get("scene_description", "")
                frame.detected_objects = result.get("detected_objects", [])
                frame.text_in_scene = result.get("text_in_scene", [])
    except Exception as e:
        logger.warning(f"Background scene analysis failed: {e}")


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("""
    ╔══════════════════════════════════════╗
    ║        THEORA Brain v0.5.0          ║
    ║   Local-First Agentic Intelligence  ║
    ║  Setup + Config + System Service    ║
    ╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=9090, log_level="info")
