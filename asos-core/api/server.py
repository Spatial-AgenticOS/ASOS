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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, Response
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
from agents.taskflow import TaskFlowRuntime
from skills.registry import SkillRegistry
from memory.store import MemoryStore
from memory.ingest import MemoryIngestor
from perception.fusion import PerceptionEngine
from perception.audio_pipeline import AudioPipeline
from perception.scene import SceneAnalyzer
from perception.change_detector import ChangeDetector
from config.loader import ConfigLoader, theora_home
from config.runtime import brain_bind_host, brain_port, brain_public_base_url, ollama_base_url
from security.vault import BlindVault, PermissionTier, ExecutionSandbox
from security.sandbox_policy import SandboxPolicy
from hardware.protocol import DeviceRegistry, DeviceManifest, HUPAction, HUPActionType, THEORA_GLASSES_MANIFEST
from mcp.server import TheoraMCPServer
from mcp.client import MCPClientManager, MCPServerConnection
from channels.base import ChannelManager, ChannelMessage, ChannelResponse
from voice.realtime_proxy import RealtimeProxy
from voice.gemini_realtime import GeminiRealtimeProxy
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
from gateway.protocol import MethodRegistry, GatewaySession, register_core_methods
from hardware.mesh import HardwareMesh
from identity.workspace import IdentityWorkspace
from genui.generator import GenUIEngine, ServiceProviderRegistry
from skills.impl.browser_use import BrowserController

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("theora.brain")


# ─────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────

app = FastAPI(
    title="THEORA Brain",
    description="THEORA — Open AI agent with computer use, GenUI, voice, and hardware control",
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
        self._load_stored_credentials()
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
        self.gemini_proxy: Optional[GeminiRealtimeProxy] = None
        self.gateway_registry: Optional[MethodRegistry] = None
        self.hardware_mesh: Optional[HardwareMesh] = None
        self.identity_workspace: Optional[IdentityWorkspace] = None
        self.genui_engine: Optional[GenUIEngine] = None
        self.service_providers: Optional[ServiceProviderRegistry] = None
        self.browser: Optional[BrowserController] = None
        self.approval_manager = None
        self.cron_service = None
        self.docker_sandbox = None
        self.taskflows: Optional[TaskFlowRuntime] = None

        # Map daemon node_id → list of sessions interested in its data
        self._daemon_session_bindings: dict[str, set[str]] = {}

    @property
    def skill_executor(self):
        return self.orchestrator.executor if self.orchestrator else None

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

        # TaskFlow runtime must be created before Orchestrator so the
        # orchestrator receives a live reference.
        try:
            self.taskflows = TaskFlowRuntime(memory_store=self.memory)
            await self.taskflows.start()
            logger.info("TaskFlow runtime initialized")
        except Exception as e:
            logger.warning(f"TaskFlow runtime skipped: {e}")

        self.orchestrator = Orchestrator(
            skill_registry=self.skill_registry,
            send_to_client=self.send_to_session,
            daemons=self.daemons,
            memory=self.memory,
            vision_buffer=self.vision_buffer,
            perception=self.perception,
            learner=self.learner,
            taskflows=self.taskflows,
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

        # Gemini Realtime Voice
        self.gemini_proxy = GeminiRealtimeProxy(
            skill_registry=self.skill_registry,
            skill_executor=self.orchestrator.executor if self.orchestrator else None,
            memory=self.memory,
            perception=self.perception,
            send_to_node=self._send_dict_to_node,
            send_to_session=self.send_to_session,
        )

        # Gateway protocol
        self.gateway_registry = MethodRegistry()
        register_core_methods(self.gateway_registry, self)

        # Hardware mesh
        self.hardware_mesh = HardwareMesh(
            device_registry=self.device_registry,
            daemons=self.daemons,
        )

        # Identity workspace — sync TOOLS.md from actual skill registry
        self.identity_workspace = IdentityWorkspace()
        self.identity_workspace.sync_tools_from_registry(self.skill_registry)

        # GenUI engine — shared instance used by both the API layer and the orchestrator
        self.genui_engine = GenUIEngine(llm=_shared_llm)
        self.service_providers = ServiceProviderRegistry()
        if self.orchestrator:
            self.orchestrator.set_genui_engine(self.genui_engine)

        # Browser controller — register as a skill so the agent can invoke it
        self.browser = BrowserController()
        self._register_browser_skill()

        # Security: exec approvals
        try:
            from security.exec_approvals import ApprovalManager
            self.approval_manager = ApprovalManager()
            logger.info("Exec approval manager initialized")
        except Exception as e:
            logger.debug(f"Exec approvals skipped: {e}")

        # Docker sandbox
        try:
            from security.docker_sandbox import get_sandbox
            self.docker_sandbox = get_sandbox()
            if self.docker_sandbox:
                logger.info("Docker sandbox available")
        except Exception:
            pass

        # Cron scheduler
        try:
            from agents.scheduler import CronService
            self.cron_service = CronService()
            logger.info("Cron scheduler initialized")
        except Exception as e:
            logger.debug(f"Cron scheduler skipped: {e}")

        stats = self.memory.stats()
        logger.info(
            f"Brain v1.0.0 initialized — {len(self.skill_registry.skills)} skills, "
            f"{stats['notes']} notes, {stats['knowledge_triples']} knowledge triples, "
            f"{stats['episodes']} episodes | Self-learning: ON | Vault: {len(self.vault.list_keys()) if self.vault else 0} keys"
        )

    def _register_browser_skill(self):
        """Register browser control as a skill the agent can call via tool use."""
        try:
            from skills.impl.browser_use import get_browser_skill_manifest
            from skills.impl import register_instance
            from models.skill_manifest import (
                SkillManifest,
                SkillEndpoint,
                EndpointParam,
                BrandProfile,
                AuthConfig,
            )

            raw_manifest = get_browser_skill_manifest()
            endpoints: list[SkillEndpoint] = []
            for endpoint in raw_manifest.get("endpoints", []):
                params = []
                for param in endpoint.get("params", []):
                    ptype = str(param.get("type", "string"))
                    if ptype not in {"string", "number", "integer", "boolean", "array", "object"}:
                        ptype = "string"
                    params.append(
                        EndpointParam(
                            name=str(param.get("name", "")),
                            type=ptype,
                            required=bool(param.get("required", True)),
                            description=str(param.get("description", "")),
                            default=str(param.get("default")) if param.get("default") is not None else None,
                            enum=[str(v) for v in (param.get("enum") or [])],
                            items=param.get("items"),
                        )
                    )

                endpoint_id = str(endpoint.get("id", ""))
                endpoints.append(
                    SkillEndpoint(
                        id=endpoint_id,
                        method=endpoint.get("method", "PYTHON"),
                        url=endpoint.get("url", f"theora://browser/{endpoint_id}"),
                        description=str(endpoint.get("description", "")),
                        params=params,
                        returns_description=str(endpoint.get("returns_description", "Browser action result")),
                        ui_hint=endpoint.get("ui_hint"),
                    )
                )

            manifest = SkillManifest(
                skill_id=str(raw_manifest.get("skill_id", "browser")),
                version=str(raw_manifest.get("version", "1.0.0")),
                author="theora-core",
                brand=BrandProfile(
                    name=str(raw_manifest.get("name", "Browser Control")),
                    primary_color="#2563EB",
                    secondary_color="#1D4ED8",
                    logo_url="",
                    icon_set="sf_symbols",
                ),
                description=str(raw_manifest.get("description", "Control and inspect browser pages.")),
                categories=["browser", "automation"],
                auth=AuthConfig(type="none"),
                endpoints=endpoints,
            )
            self.skill_registry.register(manifest)

            class _BrowserSkillBridge:
                def __init__(self, state: "BrainState"):
                    self.skill_id = manifest.skill_id
                    self._state = state

                async def execute(self, endpoint_id: str, args: dict, vault: dict):
                    result = await self._state._execute_browser_action(endpoint_id, args or {})
                    success = not isinstance(result, dict) or bool(result.get("success", "error" not in result))
                    error = result.get("error") if isinstance(result, dict) else None
                    return {
                        "success": success,
                        "status_code": 200 if success else 500,
                        "data": result,
                        "error": error,
                    }

            register_instance(manifest.skill_id, _BrowserSkillBridge(self))
            logger.info(f"Browser skill registered: {manifest.skill_id} ({len(endpoints)} endpoints)")
        except Exception as e:
            logger.warning(f"Browser skill registration failed: {e}")

    async def _execute_browser_action(self, endpoint_id: str, args: dict) -> dict:
        """Execute a browser action when called by the agent."""
        if not self.browser:
            return {"error": "Browser not available"}
        if not self.browser.connected:
            ok = await self.browser.initialize()
            if not ok:
                return {"error": "Cannot connect to Chrome. Start it with --remote-debugging-port=9222"}
        method = getattr(self.browser, endpoint_id, None)
        if not method:
            return {"error": f"Unknown browser action: {endpoint_id}"}
        if endpoint_id == "navigate":
            return await method(args.get("url", ""))
        elif endpoint_id == "screenshot":
            return await method(args.get("full_page", False))
        elif endpoint_id == "snapshot":
            return await method()
        elif endpoint_id == "click":
            return await method(args.get("ref_or_selector", ""))
        elif endpoint_id == "hover":
            return await method(args.get("ref_or_selector", ""))
        elif endpoint_id == "type_text":
            return await method(args.get("ref_or_selector", ""), args.get("text", ""))
        elif endpoint_id == "fill_form":
            return await method(args.get("fields", {}))
        elif endpoint_id == "evaluate":
            return await method(args.get("js_code", ""))
        elif endpoint_id == "scroll":
            return await method(args.get("direction", "down"), args.get("amount", 500))
        elif endpoint_id == "get_console_logs":
            return await method(args.get("limit", 50), args.get("clear", False))
        elif endpoint_id == "get_page_pdf":
            return await method(
                args.get("print_background", True),
                args.get("landscape", False),
            )
        elif endpoint_id == "get_page_info":
            return await method()
        return await method(**args) if args else await method()

    @staticmethod
    def _load_stored_credentials():
        """Load API keys from ~/.theora/credentials.json into environment if not already set."""
        creds_path = theora_home() / "credentials.json"
        if not creds_path.exists():
            return
        try:
            import json as _json
            creds = _json.loads(creds_path.read_text())
            env_keys = [
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                "GROQ_API_KEY", "TAVILY_API_KEY",
            ]
            loaded = []
            for key in env_keys:
                if creds.get(key) and not os.environ.get(key):
                    os.environ[key] = creds[key]
                    loaded.append(key)
            if creds.get("web_search") and not os.environ.get("TAVILY_API_KEY"):
                os.environ["TAVILY_API_KEY"] = creds["web_search"]
                loaded.append("TAVILY_API_KEY")
            if loaded:
                logger.info(f"Loaded credentials from {creds_path}: {', '.join(loaded)}")
        except Exception as e:
            logger.warning(f"Failed to load credentials: {e}")

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
    if state.memory:
        state.memory.start_background_tasks()
    if state.cron_service:
        async def _cron_callback(job):
            logger.info(f"Cron job fired: {job.description} (type={job.job_type})")
        state.cron_service.start(_cron_callback)


# ─────────────────────────────────────────────
# Health & Discovery
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint for Docker HEALTHCHECK and load balancers."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/info")
async def api_info():
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
    home = theora_home()
    user_md = home / "USER.md"
    has_identity = False
    if user_md.exists():
        content = user_md.read_text().strip()
        has_identity = (
            bool(content)
            and "Tell your agent about yourself" not in content
            and ("My name is" in content or len(content) > 50)
        )
    return {
        "setup_complete": state.config.setup_complete,
        "has_identity": has_identity,
        "settings": state.config.to_client_safe_dict(),
    }


@app.get("/api/config")
async def get_config():
    """Get current configuration (safe for client, no secrets)."""
    return state.config.to_client_safe_dict()


@app.get("/api/identity")
async def get_identity():
    """Get the agent identity configuration."""
    identity_path = theora_home() / "identity.yaml"
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
    identity_path = theora_home() / "identity.yaml"
    try:
        import yaml
        with open(identity_path, "w") as f:
            yaml.dump(body, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


def _knowledge_graph_d3(limit: int) -> dict:
    """Build D3-style {nodes, links} from the entity graph and legacy triples."""
    memory = state.memory
    nodes: dict[str, dict] = {}
    links: list[dict] = []

    kg = getattr(memory, "kg", None)
    if kg:
        conn = kg._conn()
        rows = conn.execute(
            """
            SELECT r.id AS rid, r.relation_type,
                   s.id AS sid, s.name AS sname, s.entity_type AS stype,
                   t.id AS tid, t.name AS tname, t.entity_type AS ttype
            FROM relations r
            JOIN entities s ON r.source_id = s.id
            JOIN entities t ON r.target_id = t.id
            ORDER BY r.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        for r in rows:
            sid, tid = r["sid"], r["tid"]
            if sid not in nodes:
                nodes[sid] = {
                    "id": sid,
                    "name": r["sname"],
                    "type": (r["stype"] or "thing"),
                }
            if tid not in nodes:
                nodes[tid] = {
                    "id": tid,
                    "name": r["tname"],
                    "type": (r["ttype"] or "thing"),
                }
            links.append(
                {
                    "source": sid,
                    "target": tid,
                    "relation": r["relation_type"],
                    "id": r["rid"],
                }
            )

    if not links:
        triples = memory.knowledge_query(limit=limit)
        seen: dict[str, str] = {}
        nxt = 0

        def nid(label: str) -> str:
            nonlocal nxt
            if label not in seen:
                seen[label] = f"k_{nxt}"
                nxt += 1
            return seen[label]

        for t in triples:
            subj, obj = t["subject"], t["object"]
            sid, tid = nid(subj), nid(obj)
            if sid not in nodes:
                nodes[sid] = {"id": sid, "name": subj, "type": "legacy"}
            if tid not in nodes:
                nodes[tid] = {"id": tid, "name": obj, "type": "legacy"}
            links.append(
                {
                    "source": sid,
                    "target": tid,
                    "relation": t["predicate"],
                    "id": t.get("id", ""),
                }
            )

    return {"nodes": list(nodes.values()), "links": links}


@app.get("/api/knowledge/graph")
async def get_knowledge_graph(limit: int = 50):
    """Return a D3-compatible graph: ``{ nodes, links }``."""
    try:
        return _knowledge_graph_d3(limit=max(1, min(limit, 500)))
    except Exception as e:
        return {"nodes": [], "links": [], "error": str(e)}


@app.get("/api/knowledge/entities")
async def search_knowledge_entities(q: str = "", limit: int = 20):
    """Search entities in the knowledge graph (FTS + embeddings when available)."""
    lim = max(1, min(limit, 100))
    kg = getattr(state.memory, "kg", None)
    try:
        if kg and q.strip():
            entities = await kg.search_entities(q.strip(), limit=lim)
            return {"entities": entities, "source": "graph"}
        if kg and not q.strip():
            conn = kg._conn()
            rows = conn.execute(
                """
                SELECT id, name, entity_type AS type, mention_count AS mentions
                FROM entities
                ORDER BY mention_count DESC, updated_at DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
            conn.close()
            return {
                "entities": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "type": r["type"],
                        "mentions": r["mentions"],
                    }
                    for r in rows
                ],
                "source": "graph",
            }
    except Exception as e:
        return {"entities": [], "error": str(e), "source": "graph"}

    rows = (
        state.memory.knowledge_search(q.strip(), limit=lim)
        if q.strip()
        else state.memory.knowledge_query(limit=lim)
    )
    out = []
    for r in rows:
        if "subject" in r:
            out.append(
                {
                    "name": r["subject"],
                    "relation": r.get("predicate"),
                    "object": r.get("object"),
                }
            )
        else:
            out.append(r)
    return {"entities": out, "source": "legacy_triples"}


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
                    body.get("base_url", ollama_base_url()) + "/api/tags",
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
    identity = body.get("identity", {})

    if settings:
        state.config.save_user_settings(settings)
    if credentials:
        for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            if credentials.get(key):
                os.environ[key] = credentials[key]
        state.config.save_credentials(credentials)

    if identity:
        _write_identity_files(identity)

    state.config.mark_setup_complete()
    state.config.discover()

    return {"ok": True, "setup_complete": True}


def _build_greeting() -> str:
    """Build a contextual greeting based on identity files."""
    home = theora_home()
    agent_name = "THEORA"
    user_name = ""

    identity_path = home / "IDENTITY.yaml"
    if identity_path.exists():
        try:
            import yaml
            with open(identity_path) as f:
                data = yaml.safe_load(f) or {}
            agent_name = data.get("name", "THEORA")
        except Exception:
            pass

    user_md = home / "USER.md"
    if user_md.exists():
        try:
            for line in user_md.read_text().splitlines():
                if line.startswith("My name is "):
                    user_name = line.replace("My name is ", "").rstrip(".")
                    break
        except Exception:
            pass

    if user_name:
        return f"{agent_name} connected. Hey {user_name}, how can I help?"
    return f"{agent_name} connected. How can I help?"


def _write_identity_files(identity: dict):
    """Write USER.md, SOUL.md, and IDENTITY.yaml from the setup wizard identity payload."""
    home = theora_home()
    home.mkdir(parents=True, exist_ok=True)

    user_name = identity.get("userName", "").strip()
    location = identity.get("location", "").strip()
    occupation = identity.get("occupation", "").strip()
    interests = identity.get("interests", "").strip()
    agent_name = identity.get("agentName", "THEORA").strip() or "THEORA"
    personality_id = identity.get("personality", "assistant")

    personality_map = {
        "assistant": (
            "You are a warm, capable personal assistant. You speak naturally, like "
            "a trusted colleague who knows the user well. You're direct — no filler, "
            "no over-explaining — but never cold. You proactively notice patterns in "
            "the user's data and mention things that might be useful."
        ),
        "engineer": (
            "You are a precise technical partner. You prefer concrete answers, code, "
            "and data over vague suggestions. You think step-by-step and explain your "
            "reasoning. You're comfortable with complexity and don't over-simplify."
        ),
        "coach": (
            "You are an encouraging wellness coach. You're proactive about the user's "
            "health and wellbeing, noticing patterns in their data. You celebrate "
            "progress, suggest improvements gently, and keep the tone supportive."
        ),
        "minimal": (
            "You are brief and factual. No small talk. No filler. Answer the question, "
            "report the data, execute the task. If there's nothing to say, say nothing."
        ),
    }
    soul = personality_map.get(personality_id, personality_map["assistant"])

    # USER.md
    lines = ["# About Me\n"]
    if user_name:
        lines.append(f"My name is {user_name}.")
    if location:
        lines.append(f"I live in {location}.")
    if occupation:
        lines.append(f"I work as {occupation}.")
    if interests:
        lines.append(f"\n## Interests\n{interests}")
    if any([user_name, location, occupation, interests]):
        (home / "USER.md").write_text("\n".join(lines) + "\n")

    # SOUL.md
    (home / "SOUL.md").write_text(f"# {agent_name}\n\n{soul}\n")

    # IDENTITY.yaml
    try:
        import yaml
        identity_data = {
            "name": agent_name,
            "tagline": "Your personal AI operating system — local, private, always learning.",
            "personality": soul,
            "rules": [
                "Never make up sensor data or health readings. Only report what's actually connected.",
                "If a tool call fails, explain what went wrong in plain language.",
                "Keep responses concise — 1-3 sentences for simple questions.",
                "Respect user privacy. Everything runs locally unless they explicitly ask to share.",
            ],
            "greeting_style": (
                "Keep greetings brief and contextual. If you know the user's name, use it. "
                "Don't list all your capabilities unless asked."
            ),
            "voice": {"style": "conversational", "tts_voice": "nova", "speed": 1.0},
        }
        (home / "IDENTITY.yaml").write_text(yaml.dump(identity_data, default_flow_style=False, sort_keys=False))
    except ImportError:
        import json
        (home / "IDENTITY.yaml").write_text(json.dumps({"name": agent_name, "personality": soul}, indent=2))


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


# WhatsApp Cloud API webhook (verification + inbound messages)
@app.get("/api/channels/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    """WhatsApp webhook verification (GET challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "theora-verify")
    if mode == "subscribe" and token == verify_token:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


@app.post("/api/channels/whatsapp/webhook")
async def whatsapp_webhook_inbound(request: Request):
    """Handle inbound WhatsApp messages."""
    try:
        body = await request.json()
        from channels.base import WhatsAppChannel
        channel_mgr = getattr(state, "channel_manager", None)
        if channel_mgr:
            wa = channel_mgr.get_channel("whatsapp")
            if wa and isinstance(wa, WhatsAppChannel):
                response = await wa.handle_webhook(body)
                return {"status": "ok", "response": response}
        return {"status": "no_handler"}
    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}")
        return {"status": "error", "detail": str(e)}


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
# GenUI Service Provider API
# ─────────────────────────────────────────────

@app.post("/api/genui/providers/register")
async def register_genui_provider(body: dict):
    """Register an external service provider for GenUI."""
    if not state.service_providers:
        return {"error": "Service provider registry not initialized"}
    provider = state.service_providers.register(body)
    if state.genui_engine:
        state.genui_engine.register_provider(provider)
    return {"ok": True, "provider_id": provider.provider_id, "components": list(provider.components.keys())}


@app.get("/api/genui/providers")
async def list_genui_providers():
    """List registered service providers."""
    if not state.service_providers:
        return {"providers": []}
    return {"providers": state.service_providers.list_providers()}


@app.get("/api/genui/providers/{provider_id}/surfaces")
async def list_genui_provider_surfaces(provider_id: str):
    """List provider-defined GenUI surfaces and cache status."""
    if not state.service_providers:
        return {"error": "Service provider registry not initialized"}
    provider = state.service_providers.get(provider_id)
    if not provider:
        return {"error": "Provider not found"}

    surfaces = provider.list_surfaces()
    if state.genui_engine:
        surfaces = state.genui_engine.list_provider_surfaces(provider_id)

    return {
        "provider_id": provider_id,
        "brand": provider.brand,
        "ui_rules": provider.ui_rules,
        "cache_policy": provider.cache_policy,
        "surfaces": surfaces,
    }


@app.get("/api/genui/providers/{provider_id}/surfaces/{surface_id}")
async def get_genui_provider_surface(provider_id: str, surface_id: str):
    """Get one provider surface contract plus cached layout, if compiled."""
    if not state.service_providers:
        return {"error": "Service provider registry not initialized"}
    provider = state.service_providers.get(provider_id)
    if not provider:
        return {"error": "Provider not found"}

    surface = provider.get_surface(surface_id)
    if not surface:
        return {"error": "Surface not found"}

    cached = state.genui_engine.get_cached_surface(provider_id, surface_id) if state.genui_engine else None
    return {
        "provider_id": provider_id,
        "surface_id": surface_id,
        "surface": surface,
        "cached": cached,
    }


@app.post("/api/genui/providers/{provider_id}/surfaces/compile")
async def compile_genui_provider_surface(provider_id: str, body: dict):
    """Compile a provider surface once and persist the layout."""
    if not state.genui_engine:
        return {"error": "GenUI engine not initialized"}

    surface_id = body.get("surface_id") or body.get("id", "")
    if not surface_id:
        return {"error": "surface_id is required"}

    return await state.genui_engine.compile_provider_surface(
        provider_id=provider_id,
        surface_id=surface_id,
        force=bool(body.get("force")),
    )


@app.post("/api/genui/providers/{provider_id}/surfaces/render")
async def render_genui_provider_surface(provider_id: str, body: dict):
    """Render a provider surface from the cached fixed layout."""
    if not state.genui_engine:
        return {"error": "GenUI engine not initialized"}

    surface_id = body.get("surface_id") or body.get("id", "")
    if not surface_id:
        return {"error": "surface_id is required"}

    return await state.genui_engine.render_provider_surface(
        provider_id=provider_id,
        surface_id=surface_id,
        data=body.get("data") or {},
        force_compile=bool(body.get("force")),
    )


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
        "taskflows": state.taskflows.stats() if state.taskflows else {},
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
        "taskflows": state.taskflows.stats() if state.taskflows else {},
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


@app.post("/api/llm/switch")
async def llm_switch(body: dict):
    """Hot-swap the LLM provider at runtime."""
    if not state.orchestrator or not state.orchestrator.llm:
        return {"error": "Brain not initialized"}
    provider = body.get("provider", "")
    model = body.get("model", "")
    api_key = body.get("api_key", "")
    if not provider:
        return {"error": "provider is required"}
    await state.orchestrator.llm.switch_provider(provider, model=model, api_key=api_key)
    return {
        "success": True,
        "provider": state.orchestrator.llm.provider,
        "model": state.orchestrator.llm.model,
        "available": state.orchestrator.llm.available,
    }


@app.get("/api/llm/presets")
async def llm_presets():
    if not state.orchestrator or not state.orchestrator.llm:
        return {"presets": []}
    return {"presets": state.orchestrator.llm.list_presets()}


@app.post("/api/llm/presets/apply")
async def llm_apply_preset(body: dict):
    if not state.orchestrator or not state.orchestrator.llm:
        return {"error": "Brain not initialized"}
    preset_id = body.get("preset", "")
    if not preset_id:
        return {"error": "preset is required"}
    result = await state.orchestrator.llm.apply_preset(preset_id)
    if result.get("ok"):
        state.config.update_settings("llm", "provider", result.get("provider"))
        state.config.update_settings("llm", "model", result.get("model"))
        if result.get("preset") == "ollama_vision":
            state.config.update_settings("vision", "enabled", True)
            state.config.update_settings("vision", "provider", "ollama")
            state.config.update_settings("vision", "model", result.get("model", "llava"))
    return result


@app.get("/api/voice/status")
async def voice_status():
    """Voice subsystem status."""
    realtime_available = state.realtime_proxy.available if state.realtime_proxy else False
    audio_available = state.audio.available if state.audio else False
    active_sessions = len(state.realtime_proxy._sessions) if state.realtime_proxy else 0
    return {
        "realtime_available": realtime_available,
        "audio_available": audio_available,
        "active_realtime_sessions": active_sessions,
        "wake_word_enabled": bool(state.wake_word and state.wake_word.enabled),
        "tts_voice": os.getenv("THEORA_TTS_VOICE", "nova"),
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


@app.post("/api/wiki/compile")
async def wiki_compile(body: dict | None = None):
    """Compile notes/episodes/knowledge into durable wiki pages."""
    payload = body or {}
    return state.memory.wiki_compile(
        notes_limit=int(payload.get("notes_limit", 200)),
        episodes_limit=int(payload.get("episodes_limit", 200)),
        knowledge_limit=int(payload.get("knowledge_limit", 400)),
    )


@app.get("/api/wiki/pages")
async def wiki_pages(q: str = "", kind: str = "", limit: int = 50):
    pages = state.memory.wiki_list_pages(query=q, kind=kind, limit=limit)
    return {"pages": pages}


@app.get("/api/wiki/pages/{page_id}")
async def wiki_page(page_id: str):
    page = state.memory.wiki_get_page(page_id)
    if not page:
        return {"error": f"Wiki page not found: {page_id}"}
    return page


@app.get("/api/wiki/stats")
async def wiki_stats():
    return state.memory.wiki_stats()


@app.post("/api/wiki/ingest")
async def wiki_ingest(body: dict):
    """Ingest a raw note and optionally compile wiki pages."""
    content = (body or {}).get("content", "")
    if not content:
        return {"error": "content is required"}
    tags = body.get("tags", [])
    importance = body.get("importance", "normal")
    compile_after = bool(body.get("compile_after", True))
    note = state.memory.save(content=content, tags=tags, importance=importance, source="wiki_ingest")
    compile_result = state.memory.wiki_compile() if compile_after else {"compiled": False}
    return {"note": note, "compile": compile_result}


@app.post("/api/wiki/ingest/text")
async def wiki_ingest_text(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    ingestor = MemoryIngestor(state.memory)
    try:
        return ingestor.ingest_text(
            content=(body or {}).get("content", ""),
            source_label=(body or {}).get("source_label", "ui"),
            compile_after=bool((body or {}).get("compile_after", True)),
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/wiki/ingest/pdf")
async def wiki_ingest_pdf(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    ingestor = MemoryIngestor(state.memory)
    try:
        return ingestor.ingest_pdf(
            path=(body or {}).get("path", ""),
            compile_after=bool((body or {}).get("compile_after", True)),
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/wiki/ingest/repo")
async def wiki_ingest_repo(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    raw_extensions = (body or {}).get("extensions_filter", [])
    if isinstance(raw_extensions, str):
        ext_list = [e.strip() for e in raw_extensions.split(",") if e.strip()]
    elif isinstance(raw_extensions, list):
        ext_list = [str(e).strip() for e in raw_extensions if str(e).strip()]
    else:
        ext_list = []

    ingestor = MemoryIngestor(state.memory)
    try:
        return ingestor.ingest_repo(
            path=(body or {}).get("path", ""),
            extensions_filter=ext_list or None,
            compile_after=bool((body or {}).get("compile_after", True)),
            max_files=int((body or {}).get("max_files", 300)),
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/taskflows")
async def create_taskflow(body: dict):
    """Create a persistent background TaskFlow."""
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    steps = body.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return {"error": "steps (non-empty list) is required"}
    session_id = body.get("session_id", "")
    title = body.get("title", "Background TaskFlow")
    context = body.get("context", {})
    try:
        flow = state.taskflows.create_flow(
            session_id=session_id,
            title=title,
            steps=steps,
            context=context,
        )
        return flow
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/taskflows")
async def list_taskflows(status: str = "", session_id: str = "", limit: int = 50):
    if not state.taskflows:
        return {"flows": []}
    return {"flows": state.taskflows.list_flows(status=status, session_id=session_id, limit=limit)}


@app.get("/api/taskflows/{flow_id}")
async def get_taskflow(flow_id: str):
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    flow = state.taskflows.get_flow(flow_id)
    if not flow:
        return {"error": f"TaskFlow not found: {flow_id}"}
    return flow


@app.post("/api/taskflows/{flow_id}/resume")
async def resume_taskflow(flow_id: str):
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    flow = state.taskflows.resume_flow(flow_id)
    if not flow:
        return {"error": f"TaskFlow not found: {flow_id}"}
    return flow


@app.post("/api/taskflows/{flow_id}/cancel")
async def cancel_taskflow(flow_id: str):
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    flow = state.taskflows.cancel_flow(flow_id)
    if not flow:
        return {"error": f"TaskFlow not found: {flow_id}"}
    return flow


# ─────────────────────────────────────────────
# Conversation Threads API
# ─────────────────────────────────────────────

@app.get("/api/conversations")
async def list_conversations(limit: int = 50):
    if not state.memory:
        return {"conversations": []}
    return {"conversations": state.memory.conversation_list(limit=limit)}


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    if not state.memory:
        return {"error": "Memory not initialized"}
    conv = state.memory.conversation_get(conversation_id)
    if not conv:
        return {"error": "Not found"}
    return conv


@app.post("/api/conversations/save")
async def save_conversation(body: dict):
    if not state.memory:
        return {"error": "Memory not initialized"}
    cid = body.get("id", "")
    messages = body.get("messages", [])
    title = body.get("title", "")
    if not cid:
        return {"error": "id is required"}
    return state.memory.conversation_save(cid, messages, title)


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    if not state.memory:
        return {"error": "Memory not initialized"}
    state.memory.conversation_delete(conversation_id)
    return {"ok": True}


@app.post("/api/session/snapshot")
async def create_session_snapshot(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    session_id = body.get("session_id", "")
    if not session_id:
        return {"error": "session_id is required"}
    history = state.orchestrator.conversation_history.get(session_id, []) if state.orchestrator else []
    return state.memory.snapshot_session(
        session_id=session_id,
        history=history,
        label=body.get("label", ""),
        branch_name=body.get("branch_name", "main"),
    )


@app.get("/api/session/snapshots")
async def list_session_snapshots(session_id: str = "", branch_name: str = "", limit: int = 50):
    if not state.memory:
        return {"snapshots": []}
    snapshots = state.memory.list_snapshots(
        session_id=session_id,
        branch_name=branch_name,
        limit=limit,
    )
    return {"snapshots": snapshots}


@app.get("/api/session/snapshots/{snapshot_id}")
async def get_session_snapshot(snapshot_id: str):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    snap = state.memory.get_snapshot(snapshot_id)
    if not snap:
        return {"error": f"Snapshot not found: {snapshot_id}"}
    return snap


@app.post("/api/session/branch")
async def branch_session(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    source_snapshot_id = body.get("snapshot_id", "")
    if source_snapshot_id:
        source = state.memory.get_snapshot(source_snapshot_id)
    else:
        session_id = body.get("session_id", "")
        if not session_id:
            return {"error": "session_id is required when snapshot_id is omitted"}
        history = state.orchestrator.conversation_history.get(session_id, []) if state.orchestrator else []
        auto = state.memory.snapshot_session(
            session_id=session_id,
            history=history,
            label="auto-branch-source",
            branch_name="main",
        )
        source_snapshot_id = auto["snapshot_id"]
        source = state.memory.get_snapshot(source_snapshot_id)

    if not source:
        return {"error": f"Snapshot not found: {source_snapshot_id}"}

    branch_name = body.get("branch_name", f"branch-{int(time.time())}")
    branch_session_id = body.get("target_session_id", f"{source['session_id']}:{branch_name}:{str(uuid4())[:6]}")
    state.memory.working_replace(branch_session_id, source.get("working", []))
    if state.orchestrator:
        state.orchestrator.conversation_history[branch_session_id] = source.get("history", [])
    branched_snapshot = state.memory.snapshot_session(
        session_id=branch_session_id,
        history=source.get("history", []),
        label=body.get("label", f"branch from {source_snapshot_id}"),
        branch_name=branch_name,
        source_snapshot_id=source_snapshot_id,
    )
    return {
        "status": "branched",
        "source_snapshot_id": source_snapshot_id,
        "target_session_id": branch_session_id,
        "snapshot": branched_snapshot,
    }


@app.post("/api/session/restore")
async def restore_session_snapshot(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    snapshot_id = body.get("snapshot_id", "")
    if not snapshot_id:
        return {"error": "snapshot_id is required"}
    snapshot = state.memory.get_snapshot(snapshot_id)
    if not snapshot:
        return {"error": f"Snapshot not found: {snapshot_id}"}

    session_id = body.get("session_id", snapshot["session_id"])
    as_new_session = bool(body.get("as_new_session", False))
    target_session_id = body.get("target_session_id")
    if not target_session_id:
        target_session_id = f"{session_id}:restore:{str(uuid4())[:6]}" if as_new_session else session_id

    state.memory.working_replace(target_session_id, snapshot.get("working", []))
    if state.orchestrator:
        state.orchestrator.conversation_history[target_session_id] = snapshot.get("history", [])

    restore_snapshot = state.memory.snapshot_session(
        session_id=target_session_id,
        history=snapshot.get("history", []),
        label=body.get("label", f"restore {snapshot_id}"),
        branch_name=snapshot.get("branch_name", "main"),
        source_snapshot_id=snapshot_id,
    )
    return {
        "status": "restored",
        "target_session_id": target_session_id,
        "restored_from_snapshot_id": snapshot_id,
        "snapshot": restore_snapshot,
    }


# ─────────────────────────────────────────────
# Main Client WebSocket
# ─────────────────────────────────────────────

@app.websocket("/v1/session")
async def client_session(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid4())
    state.sessions[session_id] = ws
    logger.info(f"Client connected: {session_id}")

    # Create a GatewaySession for typed protocol support
    gw_session = GatewaySession(session_id, ws, state.gateway_registry)

    # Bind session to all currently connected daemons
    for node_id in state.daemons:
        state.bind_session_to_daemon(session_id, node_id)
        state.perception.update_connected_nodes(session_id, list(state.daemons.keys()))

    # Build a personal greeting based on identity files
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

            # New typed protocol: if message has "type": "req"/"res"/"event", use GatewaySession
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
        # Trigger self-learning: extract knowledge + summarize session
        if state.orchestrator:
            try:
                await state.orchestrator.on_session_disconnect(session_id)
            except Exception as e:
                logger.warning(f"Session summarization failed: {e}")
        # Run identity maintenance cycle scoped to this session
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

                # Auto-register as HUP device via hardware mesh
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
                # Resolve hardware mesh invoke futures
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

            # ── Phone/Glasses: text command from daemon node ──
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

            # ── iOS compat: accept "frame" type as alias for "vision_frame" ──
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
    if state.taskflows:
        await state.taskflows.stop()
    logger.info("Shutdown complete.")


# ─────────────────────────────────────────────
# Bundled Web UI (served from webui/ if present)
# ─────────────────────────────────────────────

from starlette.responses import HTMLResponse, FileResponse

_webui_dir = Path(__file__).parent.parent / "webui"
_webui_ready = _webui_dir.is_dir() and (_webui_dir / "index.html").exists()

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
    ║        THEORA v1.0.0                ║
    ║   Open AI Agent · Computer Use      ║
    ║   Voice · GenUI · Hardware          ║
    ╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host=brain_bind_host(), port=brain_port(), log_level="info")
