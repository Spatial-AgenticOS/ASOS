"""
THEORA Brain — Universal Agentic OS Core
==========================================
The local-first agentic brain. Runs on the user's machine.
Clients (phone, web, daemon, glasses, robots) connect via WebSocket.
MCP clients (Claude, Cursor) connect via JSON-RPC.
Channels (Telegram, Discord, Slack) bridge messaging platforms.

v1.0.0 — HUP, MCP server/client, sandbox policies, channels, federated sync.
"""

import asyncio
import json
import logging
import os
import time
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
from perception.change_detector import ChangeDetector
from config.loader import ConfigLoader
from security.vault import BlindVault, PermissionTier, ExecutionSandbox
from security.sandbox_policy import SandboxPolicy
from hardware.protocol import DeviceRegistry, DeviceManifest, HUPAction, HUPActionType, THEORA_GLASSES_MANIFEST
from mcp.server import TheoraMCPServer
from mcp.client import MCPClientManager, MCPServerConnection
from channels.base import ChannelManager, ChannelMessage, ChannelResponse
from voice.realtime_proxy import RealtimeProxy
from voice.router import VoiceRouter
from memory.sync import SyncEngine
from security.wasm_sandbox import WASMSandbox
from perception.wake_word import WakeWordDetector, WakeWordConfig
from integrations.oauth_manager import OAuthManager
from integrations.spotify import SpotifyIntegration
from integrations.home_assistant import HomeAssistantIntegration
from integrations.notion import NotionIntegration
from integrations.webhook_receiver import WebhookReceiver, EventBus
from skills.marketplace import MarketplaceClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("theora.brain")


# ─────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────

app = FastAPI(
    title="THEORA Brain",
    description="Local-first agentic intelligence core — self-learning, streaming, scene-aware",
    version="1.0.0",
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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import collections

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
        self.change_detector = ChangeDetector()
        self.learner: Optional[Learner] = None
        self.skill_gen: Optional[SkillGenerator] = None
        self.vault: Optional[BlindVault] = None
        self.sandbox: Optional[ExecutionSandbox] = None
        self.policy: Optional[SandboxPolicy] = None
        self.device_registry: Optional[DeviceRegistry] = None
        self.mcp_server: Optional[TheoraMCPServer] = None
        self.mcp_client: Optional[MCPClientManager] = None
        self.channel_manager: Optional[ChannelManager] = None
        self.voice_router: Optional[VoiceRouter] = None
        self.realtime_proxy: Optional[RealtimeProxy] = None
        self.oauth: Optional[OAuthManager] = None
        self.spotify: Optional[SpotifyIntegration] = None
        self.home_assistant: Optional[HomeAssistantIntegration] = None
        self.notion: Optional[NotionIntegration] = None
        self.event_bus: Optional[EventBus] = None
        self.webhook_receiver: Optional[WebhookReceiver] = None
        self.marketplace: Optional[MarketplaceClient] = None
        self.sync_engine: Optional[SyncEngine] = None
        self.wasm_sandbox: Optional[WASMSandbox] = None
        self.wake_word: Optional[WakeWordDetector] = None
        self.orchestrator: Optional[Orchestrator] = None
        self.activity_log: deque = deque(maxlen=100)

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

        self.policy = SandboxPolicy.load_default()
        self.device_registry = DeviceRegistry()
        self.mcp_server = TheoraMCPServer(
            device_registry=self.device_registry,
            memory=self.memory,
            perception=self.perception,
        )
        self.mcp_client = MCPClientManager()
        try:
            await self.mcp_client.load_and_connect()
        except Exception as e:
            logger.warning(f"MCP client auto-connect failed: {e}")
        self.channel_manager = ChannelManager()

        self.oauth = OAuthManager(vault=self.vault)
        self.spotify = SpotifyIntegration(oauth_manager=self.oauth)
        self.home_assistant = HomeAssistantIntegration(oauth_manager=self.oauth)
        self.notion = NotionIntegration(oauth_manager=self.oauth)
        self.event_bus = EventBus()
        self.webhook_receiver = WebhookReceiver(event_bus=self.event_bus)
        self.marketplace = MarketplaceClient(skill_registry=self.skill_registry)

        # Federated sync engine
        import socket
        sync_node_id = f"{socket.gethostname()}-{os.getpid()}"
        self.sync_engine = SyncEngine(node_id=sync_node_id, memory_store=self.memory)
        self.memory.set_sync_engine(self.sync_engine)
        await self.sync_engine.start_discovery()

        # WASM sandbox for untrusted skill execution
        self.wasm_sandbox = WASMSandbox()

        # Wake word detector
        self.wake_word = WakeWordDetector(WakeWordConfig(
            enabled=os.getenv("THEORA_WAKE_WORD", "true").lower() in ("true", "1", "yes"),
        ))

        from skills.impl import register_instance
        if self.spotify:
            register_instance("spotify_music", self.spotify)
        if self.home_assistant:
            register_instance("smart_home_hue", self.home_assistant)
        if self.notion:
            register_instance("notion", self.notion)

        self.orchestrator = Orchestrator(
            skill_registry=self.skill_registry,
            send_to_client=self.send_to_session,
            daemons=self.daemons,
            memory=self.memory,
            vision_buffer=self.vision_buffer,
            perception=self.perception,
            learner=self.learner,
        )
        self.orchestrator.set_llm(_shared_llm)
        if self.vault:
            self.orchestrator.set_vault(self.vault)
        if self.wasm_sandbox:
            self.orchestrator.executor.set_wasm_sandbox(self.wasm_sandbox)
        if self.mcp_client:
            self.orchestrator.set_mcp_client(self.mcp_client)

        self.realtime_proxy = RealtimeProxy(
            skill_registry=self.skill_registry,
            skill_executor=self.orchestrator.executor if self.orchestrator else None,
            memory=self.memory,
            perception=self.perception,
            send_to_node=self._send_dict_to_node,
            send_to_session=self.send_to_session,
        )

        self.voice_router = VoiceRouter(
            realtime_proxy=self.realtime_proxy,
            audio_pipeline=self.audio,
            orchestrator=self.orchestrator,
            memory=self.memory,
            perception=self.perception,
            wake_word_detector=self.wake_word,
            send_to_session=self.send_to_session,
            send_to_node=self._send_dict_to_node,
        )

        stats = self.memory.stats()
        logger.info(
            f"Brain v1.0.0 initialized — {len(self.skill_registry.skills)} skills, "
            f"{stats['notes']} notes, {stats['knowledge_triples']} knowledge triples, "
            f"{stats['episodes']} episodes | Self-learning: ON | Vault: {len(self.vault.list_keys()) if self.vault else 0} keys"
        )

    async def send_to_session(self, session_id: str, msg: TheoraMessage):
        ws = self.sessions.get(session_id)
        if ws:
            await ws.send_json(msg.model_dump())

    async def send_to_daemon(self, node_id: str, msg: TheoraMessage):
        ws = self.daemons.get(node_id)
        if ws:
            await ws.send_json(msg.model_dump())

    async def _send_dict_to_node(self, node_id: str, msg_dict: dict):
        """Send a raw dict message to a daemon node (used by voice pipeline)."""
        ws = self.daemons.get(node_id)
        if ws:
            await ws.send_json(msg_dict)

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

@app.get("/health")
async def health():
    """Health check endpoint for Docker HEALTHCHECK and load balancers."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/")
async def root():
    stats = state.memory.stats()
    return {
        "name": "THEORA Brain",
        "version": "1.0.0",
        "status": "running",
        "sessions": len(state.sessions),
        "daemons": list(state.daemons.keys()),
        "devices": len(state.devices),
        "skills": len(state.skill_registry.skills),
        "memory": stats,
        "audio_available": state.audio.available,
        "realtime_available": state.realtime_proxy.available if state.realtime_proxy else False,
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


@app.get("/api/identity")
async def get_identity():
    """Get the agent identity configuration."""
    identity_path = Path(os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))) / "identity.yaml"
    if identity_path.exists():
        try:
            import yaml
            with open(identity_path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {"name": "THEORA", "personality": "", "rules": [], "greeting_style": "", "voice": {"tts_voice": "nova"}}


@app.post("/api/identity")
async def update_identity(body: dict):
    """Update the agent identity configuration."""
    identity_path = Path(os.environ.get("THEORA_HOME", str(Path.home() / ".theora"))) / "identity.yaml"
    try:
        import yaml
        with open(identity_path, "w") as f:
            yaml.dump(body, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/devices")
async def list_devices():
    """List all connected hardware nodes / daemons."""
    nodes = []
    for node_id, info in state.daemons.items():
        ws = info if not isinstance(info, dict) else None
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
# MCP API (JSON-RPC endpoint + management)
# ─────────────────────────────────────────────

@app.post("/mcp")
async def mcp_jsonrpc(body: dict):
    """MCP JSON-RPC endpoint for external MCP clients."""
    if not state.mcp_server:
        return {"jsonrpc": "2.0", "error": {"code": -32603, "message": "MCP server not initialized"}, "id": body.get("id")}
    return await state.mcp_server.handle_jsonrpc(body)


@app.get("/api/mcp/status")
async def mcp_status():
    """MCP server and client status."""
    server_tools = len(state.mcp_server.handle_tools_list()["tools"]) if state.mcp_server else 0
    client_stats = state.mcp_client.stats if state.mcp_client else {}
    return {
        "server": {"tools_exposed": server_tools},
        "client": client_stats,
    }


@app.get("/api/mcp/tools")
async def mcp_external_tools():
    """List all tools from connected external MCP servers."""
    if not state.mcp_client:
        return {"tools": []}
    return {"tools": state.mcp_client.all_tools()}


@app.get("/api/mcp/registry")
async def mcp_registry():
    """List all known MCP servers with status."""
    from mcp.registry import MCPServerRegistry
    registry = MCPServerRegistry(mcp_client=state.mcp_client)
    return {"servers": registry.list_known()}


@app.post("/api/mcp/connect")
async def mcp_connect(body: dict):
    """Connect to a new MCP server at runtime."""
    if not state.mcp_client:
        return {"error": "MCP client not initialized"}
    name = body.get("name", "unnamed")
    conn = MCPServerConnection(name, body)
    success = await conn.connect()
    if success:
        state.mcp_client._servers[name] = conn
        _log_activity("mcp_connected", f"MCP server '{name}' connected ({len(conn.tools)} tools)")
        return {"success": True, "tools": len(conn.tools)}
    return {"success": False, "error": f"Failed to connect to MCP server '{name}'"}


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
# Channel API
# ─────────────────────────────────────────────

@app.get("/api/channels")
async def list_channels():
    if not state.channel_manager:
        return {"channels": []}
    return state.channel_manager.stats


@app.post("/api/channels/start")
async def start_channel(body: dict):
    channel_type = body.get("type", "")
    config = body.get("config", {})
    if not state.channel_manager:
        return {"error": "Channel manager not initialized"}
    await state.channel_manager.start_channel(channel_type, config)
    return {"ok": True, "channel": channel_type}


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
    from starlette.requests import Request
    # For JSON webhooks, use the parsed body
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
    hw_stats = state.device_registry.stats if state.device_registry else {}
    mcp_client_stats = state.mcp_client.stats if state.mcp_client else {}
    channel_stats = state.channel_manager.stats if state.channel_manager else {}
    skill_gen_stats = state.skill_gen.stats if state.skill_gen else {}
    return {
        "version": "1.0.0",
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
        "hardware": hw_stats,
        "mcp": {
            "server_active": state.mcp_server is not None,
            "client": mcp_client_stats,
        },
        "channels": channel_stats,
        "skill_generator": skill_gen_stats,
        "security": {
            "vault_keys": len(state.vault.list_keys()) if state.vault else 0,
            "max_tier": state.sandbox.max_tier if state.sandbox else "active",
            "policy": state.policy._data.get("name", "default") if state.policy else "none",
        },
        "voice": {
            "audio_available": state.audio.available,
            "realtime_available": state.realtime_proxy.available if state.realtime_proxy else False,
            "active_realtime_sessions": len(state.realtime_proxy._sessions) if state.realtime_proxy else 0,
        },
        "vision": {
            "change_detector": state.change_detector.stats() if state.change_detector else {},
            "scene_available": state.scene.available if state.scene else False,
        },
        "integrations": {
            "oauth": state.oauth.status() if state.oauth else {},
            "spotify": state.spotify.connected if state.spotify else False,
            "home_assistant": state.home_assistant.connected if state.home_assistant else False,
            "notion": state.notion.connected if state.notion else False,
            "webhooks": state.event_bus.stats() if state.event_bus else {},
        },
        "marketplace": {
            "installed_skills": len(state.marketplace.list_installed()) if state.marketplace else 0,
        },
        "multi_agent": state.orchestrator._multi_agent.stats if state.orchestrator and state.orchestrator._multi_agent else {},
    }


def _log_activity(action: str, detail: str = ""):
    """Log an activity to the brain's activity feed."""
    state.activity_log.append({
        "action": action,
        "detail": detail,
        "timestamp": time.time(),
    })


@app.get("/api/dashboard")
async def dashboard_data():
    """Aggregated data for the live dashboard — weather, devices, health, activity."""
    stats = state.memory.stats()
    devices_list = []
    latest_health = {}

    for node_id in state.daemons:
        dev = state.devices.get(node_id, {})
        devices_list.append({
            "node_id": node_id,
            "type": dev.get("device_type", dev.get("node_type", "unknown")),
            "connected": True,
        })

    for sid in state.sessions:
        frame = state.perception.get_frame(sid)
        if frame:
            if frame.heart_rate:
                latest_health["heart_rate"] = frame.heart_rate
            if frame.spo2_pct:
                latest_health["spo2"] = frame.spo2_pct
            if frame.skin_temperature_c:
                latest_health["temperature"] = frame.skin_temperature_c

    return {
        "devices": devices_list,
        "device_count": len(state.daemons),
        "session_count": len(state.sessions),
        "health": latest_health,
        "memory": stats,
        "skills_count": len(state.skill_registry.skills),
        "llm_available": state.orchestrator is not None,
        "audio_available": state.audio.available,
        "sync": state.sync_engine.stats if state.sync_engine else {},
        "wasm_available": state.wasm_sandbox.available if state.wasm_sandbox else False,
        "wake_word_enabled": state.wake_word.enabled if state.wake_word else False,
    }


@app.get("/api/activity")
async def get_activity():
    """Recent brain activity log."""
    return {"entries": list(state.activity_log)}


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
                await ws.send_json({
                    "type": "sync_response",
                    "node_id": state.sync_engine.node_id if state.sync_engine else "",
                    "vector_clock": state.sync_engine.get_vector_clock() if state.sync_engine else {},
                })

                incoming = await ws.receive_json()
                if incoming.get("type") == "sync_data" and state.sync_engine:
                    applied = state.sync_engine.apply_remote_changes(incoming.get("changes", []))
                    my_changes = state.sync_engine._wal.get_changes_since(
                        remote_vc.get(state.sync_engine.node_id, "0:0:"),
                        exclude_node=peer_id,
                    ) if hasattr(state.sync_engine, '_wal') else []
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


@app.get("/api/sync/status")
async def sync_status():
    if not state.sync_engine:
        return {"enabled": False}
    return {"enabled": True, **state.sync_engine.stats}


@app.get("/api/llm/status")
async def llm_status():
    """LLM availability status for the client UI."""
    if not state.orchestrator:
        return {"available": False, "provider": "none", "reason": "Brain not initialized"}
    llm = state.orchestrator.llm
    if not llm:
        return {"available": False, "provider": "none", "reason": "No LLM configured"}
    return {
        "available": getattr(llm, "available", False),
        "provider": getattr(llm, "provider", "unknown"),
        "model": getattr(llm, "model", "unknown"),
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
                                    session_id=session_id, hop="brain",
                                    type="skill_proposal",
                                    payload={"manifest": manifest, "reason": need.get("capability", "")},
                                ).model_dump())

                elif msg.type == "audio_chunk" and isinstance(payload, AudioChunkPayload):
                    if state.voice_router:
                        await state.voice_router.handle_audio_from_client(
                            session_id=session_id,
                            audio_b64=payload.data_b64,
                            chunk_index=payload.chunk_index,
                            is_final=payload.is_final,
                            encoding=payload.encoding,
                            sample_rate=payload.sample_rate,
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
                _log_activity("device_connected", f"{node_id} ({payload.node_type})")

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

            # ── Voice Pipeline: node declares voice capabilities ──
            elif msg.type == "voice_config":
                payload_dict = raw.get("payload", {})
                if state.voice_router and node_id:
                    state.voice_router.register_voice_config(node_id, payload_dict)
                    for sid in state.get_sessions_for_daemon(node_id):
                        state.voice_router.bind_node_to_session(node_id, sid)
                    supports_rt = payload_dict.get("supports_realtime", False)
                    logger.info(f"Voice config from {node_id}: realtime={supports_rt}")

            # ── Voice Pipeline: audio from phone/glasses node ──
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
# Entry Point
# ─────────────────────────────────────────────

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
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    import uvicorn
    print("""
    ╔══════════════════════════════════════╗
    ║        THEORA Brain v1.0.0          ║
    ║   Local-First Agentic Intelligence  ║
    ║   Voice · Vision · Integrations     ║
    ╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=9090, log_level="info")
