"""
Shared brain state singleton.

Every route module and the main server import ``state`` from here.
"""

import logging
import os
import time
from collections import deque
from typing import Optional

from fastapi import WebSocket

from models.protocol import TheoraMessage
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

logger = logging.getLogger("theora.brain")

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


class BrainState:
    def __init__(self):
        self._load_stored_credentials()
        self.config = ConfigLoader()
        self.config.discover()
        for env_key, env_value in self.config.export_as_env().items():
            os.environ[env_key] = env_value
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
        self.scheduler = None
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

        import socket
        sync_node_id = f"{socket.gethostname()}-{os.getpid()}"
        self.sync_engine = SyncEngine(node_id=sync_node_id, memory_store=self.memory)
        self.memory.set_sync_engine(self.sync_engine)
        await self.sync_engine.start_discovery()

        self.wasm_sandbox = WASMSandbox()

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

        self.gemini_proxy = GeminiRealtimeProxy(
            skill_registry=self.skill_registry,
            skill_executor=self.orchestrator.executor if self.orchestrator else None,
            memory=self.memory,
            perception=self.perception,
            send_to_node=self._send_dict_to_node,
            send_to_session=self.send_to_session,
        )

        self.gateway_registry = MethodRegistry()
        register_core_methods(self.gateway_registry, self)

        self.hardware_mesh = HardwareMesh(
            device_registry=self.device_registry,
            daemons=self.daemons,
        )

        self.identity_workspace = IdentityWorkspace()
        self.identity_workspace.sync_tools_from_registry(self.skill_registry)

        self.genui_engine = GenUIEngine(llm=_shared_llm)
        self.service_providers = ServiceProviderRegistry()
        if self.orchestrator:
            self.orchestrator.set_genui_engine(self.genui_engine)

        self.browser = BrowserController()
        self._register_browser_skill()

        try:
            from security.exec_approvals import ApprovalManager
            self.approval_manager = ApprovalManager()
            logger.info("Exec approval manager initialized")
        except Exception as e:
            logger.debug(f"Exec approvals skipped: {e}")

        try:
            from security.docker_sandbox import get_sandbox
            self.docker_sandbox = get_sandbox()
            if self.docker_sandbox:
                logger.info("Docker sandbox available")
        except Exception:
            pass

        try:
            from agents.scheduler import CronService
            self.cron_service = CronService()
            self.scheduler = self.cron_service
            self.skill_registry._cron_service = self.cron_service
            logger.info("Cron scheduler initialized")
        except Exception as e:
            logger.debug(f"Cron scheduler skipped: {e}")

        stats = self.memory.stats()
        logger.info(
            f"Brain v1.2.0 initialized — {len(self.skill_registry.skills)} skills, "
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
                def __init__(self, state_ref: "BrainState"):
                    self.skill_id = manifest.skill_id
                    self._state = state_ref

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

    async def broadcast_event(self, event_type: str, data: dict):
        """Push a state update to all connected WebSocket clients."""
        msg = {"type": "state_push", "event": event_type, "data": data}
        dead = []
        for sid, ws in self.sessions.items():
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self.sessions.pop(sid, None)

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


def _log_activity(action: str, detail: str = ""):
    """Log an activity to the brain's activity feed."""
    state.activity_log.append({
        "action": action,
        "detail": detail,
        "timestamp": time.time(),
    })
