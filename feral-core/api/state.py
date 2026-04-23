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

from version import VERSION as __version__
from models.protocol import FeralMessage
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
from config.loader import ConfigLoader, feral_home, feral_data_home
from config.runtime import brain_bind_host, brain_port, brain_public_base_url, ollama_base_url
from security.vault import BlindVault, PermissionTier, ExecutionSandbox
from security.sandbox_policy import SandboxPolicy
from hardware.protocol import DeviceRegistry, DeviceManifest, HUPAction, HUPActionType, FERAL_GLASSES_MANIFEST
from mcp.server import FeralMCPServer
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
from integrations.mqtt_bridge import MQTTBridge
from integrations.notion import NotionIntegration
from integrations.webhook_receiver import WebhookReceiver, EventBus
from integrations.email_watcher import EmailWatcher
from integrations.calendar import CalendarIntegration
from integrations.email import EmailIntegration
from integrations.messaging import MessagingHub
from integrations.health_platforms import HealthAggregator, WhoopClient, OuraClient
from integrations.google_drive import GoogleDriveIntegration
from integrations.google_contacts import GoogleContactsIntegration
from integrations.microsoft365 import Microsoft365Integration
from skills.marketplace import MarketplaceClient
from gateway.protocol import MethodRegistry, GatewaySession, register_core_methods
from hardware.mesh import HardwareMesh
from identity.workspace import IdentityWorkspace
from genui.generator import GenUIEngine, ServiceProviderRegistry
from providers.catalog import ProviderCatalog, default_cache_path as _default_catalog_cache
from skills.impl.browser_use import BrowserController
from agents.session_handoff import SessionHandoffManager
from agents.identity_loader import IdentityLoader
from agents.baseline_engine import BaselineEngine
from agents.about_me import AboutMeStore
from agents.ideas_engine import IdeasEngine, IdeasStore
from agents.app_registry import (
    AppRegistry,
    HybridGenerator,
    default_apps_db_path,
    default_apps_dir,
    default_hybrid_cache_dir,
)
from security.device_pairing import DevicePairingStore
from api.boot_report import BootReport, boot_subsystem

logger = logging.getLogger("feral.brain")

VISION_MAX_FRAME_KB = int(os.environ.get("FERAL_VISION_MAX_FRAME_KB", "512"))


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
        self.mcp_server: Optional[FeralMCPServer] = None
        self.mcp_client: Optional[MCPClientManager] = None
        self.channel_manager: Optional[ChannelManager] = None
        self.voice_router: Optional[VoiceRouter] = None
        self.realtime_proxy: Optional[RealtimeProxy] = None
        self.oauth: Optional[OAuthManager] = None
        self.spotify: Optional[SpotifyIntegration] = None
        self.home_assistant: Optional[HomeAssistantIntegration] = None
        self.notion: Optional[NotionIntegration] = None
        self.calendar: Optional[CalendarIntegration] = None
        self.email: Optional[EmailIntegration] = None
        self.messaging: Optional[MessagingHub] = None
        self.health_aggregator: Optional[HealthAggregator] = None
        self.google_drive: Optional[GoogleDriveIntegration] = None
        self.google_contacts: Optional[GoogleContactsIntegration] = None
        self.microsoft365: Optional[Microsoft365Integration] = None
        self.digital_twin = None
        self.location_engine = None
        self.push_channel = None
        self.event_bus: Optional[EventBus] = None
        self.webhook_receiver: Optional[WebhookReceiver] = None
        self.marketplace: Optional[MarketplaceClient] = None
        self.sync_engine: Optional[SyncEngine] = None
        self.wasm_sandbox: Optional[WASMSandbox] = None
        self.wake_word: Optional[WakeWordDetector] = None
        self.orchestrator: Optional[Orchestrator] = None
        # ProviderCatalog — single source of truth for the LLM provider
        # inventory + model lists (see feral-core/providers/catalog.py).
        # Shared by the runtime LLMProvider, the REST /api/llm routes,
        # the CLI setup wizard, and v2 /setup page.
        self.provider_catalog: Optional[ProviderCatalog] = None
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
        self.session_handoff: Optional[SessionHandoffManager] = None
        self.baseline_engine: Optional[BaselineEngine] = None
        # AboutMe store — structured self-model of the user (see agents/about_me.py).
        # Initialised alongside BaselineEngine during state.init().
        self.about_me: Optional[AboutMeStore] = None
        # Ideas engine — "For you today" pane (see agents/ideas_engine.py).
        # Built on top of AboutMe + BaselineEngine + ConsciousnessStore.
        self.ideas_engine: Optional[IdeasEngine] = None
        # GenUI third-party app platform (see agents/app_registry.py).
        # AppRegistry indexes installed apps; HybridGenerator renders
        # authored + cached + LLM-generated surfaces.
        self.app_registry: Optional[AppRegistry] = None
        self.hybrid_genui: Optional[HybridGenerator] = None
        self.somatic_engine = None
        self.tool_genesis = None
        self.supervisor = None
        self.twin_policy = None
        self.agent_mitosis = None
        self.intent_compiler = None
        self.mqtt_bridge = None
        self.email_watcher: Optional[EmailWatcher] = None
        self.device_pairing_store: DevicePairingStore = DevicePairingStore()
        self._boot_report: BootReport = BootReport()
        # First-party agent personas and workflow packs loaded from
        # feral-core/agents/personas/ and feral-core/workflows/ at boot.
        # See feral-core/agents/persona_loader.py + Track C in
        # TRACK_C_PERSONAS_WORKFLOWS.md.
        self.personas: dict = {}
        self.workflow_packs: dict = {}
        # ConsciousnessStore (5th memory tier — in-flight operational state).
        # Initialised in state.init() after the FERAL_HOME is known.
        # See feral-core/memory/consciousness.py.
        self.consciousness = None

        # Map daemon node_id → list of sessions interested in its data
        self._daemon_session_bindings: dict[str, set[str]] = {}

        # Collectors for channel-based sessions (no WebSocket)
        self._channel_collectors: dict[str, list[str]] = {}

    @property
    def skill_executor(self):
        return self.orchestrator.executor if self.orchestrator else None

    async def init(self):
        _boot_start = time.time()
        with boot_subsystem(self._boot_report, "SkillRegistry", optional=False):
            self.skill_registry.load_builtin_skills()

        with boot_subsystem(self._boot_report, "Personas", optional=True):
            from agents.persona_loader import (
                load_personas,
                load_workflow_packs,
                default_personas_dir,
                default_workflow_packs_dir,
            )
            self.personas = load_personas(default_personas_dir())
            self.workflow_packs = load_workflow_packs(default_workflow_packs_dir())

        with boot_subsystem(self._boot_report, "Consciousness", optional=True):
            # 5th memory tier — in-flight operational state. On boot we
            # open the SQLite store and attempt to restore the last
            # snapshot file so "the agent knows where it left off"
            # survives restarts / upgrades / device handoffs.
            from memory.consciousness import (
                ConsciousnessStore,
                default_consciousness_db_path,
                default_snapshot_path,
            )
            self.consciousness = ConsciousnessStore(default_consciousness_db_path())

            # Broadcast any state mutation to every connected v2 client
            # via the existing /v1/session WebSocket. Fire-and-forget:
            # we schedule the coroutine onto the running loop so the
            # store's sync code path never blocks waiting for sends.
            def _on_consciousness_change(event_name: str, payload: dict) -> None:
                try:
                    import asyncio as _aio
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    return  # no loop (e.g. during boot) — broadcast is optional
                loop.create_task(self.broadcast_event(event_name, payload))
                # Kick IdeasEngine whenever something enters waiting_user so
                # the "Right now" pane renders a fresh nudge within seconds.
                if (
                    event_name == "consciousness_status"
                    and isinstance(payload, dict)
                    and payload.get("status") == "waiting_user"
                    and self.ideas_engine is not None
                ):
                    try:
                        self.ideas_engine.refresh_waiting_user()
                    except Exception as exc:
                        logger.debug("IdeasEngine.refresh_waiting_user failed: %s", exc)

            self.consciousness.set_on_change(_on_consciousness_change)

            snap = default_snapshot_path()
            if snap.exists():
                try:
                    import json as _json
                    restored = self.consciousness.restore(_json.loads(snap.read_text()))
                    logger.info("Consciousness: restored %d entities from %s", restored, snap)
                except Exception as exc:
                    logger.warning("Consciousness snapshot restore skipped: %s", exc)

        with boot_subsystem(self._boot_report, "ProviderCatalog", optional=False):
            # Single registry of LLM providers + live model lists.
            # Built before LLMProvider so the runtime reads its config
            # through the catalog instead of a private tuple.
            self.provider_catalog = ProviderCatalog(cache_path=_default_catalog_cache())

        from agents.llm_provider import LLMProvider
        with boot_subsystem(self._boot_report, "LLMProvider", optional=False):
            _shared_llm = LLMProvider()
            if self.provider_catalog is not None:
                _shared_llm.set_catalog(self.provider_catalog)
            try:
                _llm_cfg = dict(self.config._merged.get("llm", {})) if self.config else {}
            except Exception:
                _llm_cfg = {}
            if _llm_cfg:
                # Propagate fallback_providers + any other runtime-tunable
                # llm.* keys into the LLMProvider's internal config so
                # classify_error-triggered failover actually uses them.
                _shared_llm.set_config(_llm_cfg)
        self.learner = Learner(llm=_shared_llm, memory=self.memory)
        self.scene = SceneAnalyzer(llm=_shared_llm)
        scene_cooldown = int(os.environ.get("FERAL_SCENE_COOLDOWN", "10"))
        self.scene.set_cooldown(scene_cooldown)

        self.skill_gen = SkillGenerator(
            llm=_shared_llm,
            skill_registry=self.skill_registry,
        )

        self.vault = BlindVault()
        self.sandbox = ExecutionSandbox(
            max_tier=os.environ.get("FERAL_MAX_TIER", "active")
        )

        self.policy = SandboxPolicy.load_default()
        self.device_registry = DeviceRegistry()
        self.mcp_server = FeralMCPServer(
            device_registry=self.device_registry,
            memory=self.memory,
            perception=self.perception,
        )
        self.mcp_client = MCPClientManager()
        with boot_subsystem(self._boot_report, "MCPClientManager"):
            await self.mcp_client.load_and_connect()
        self.channel_manager = ChannelManager()

        self.oauth = OAuthManager(vault=self.vault)
        self.spotify = SpotifyIntegration(oauth_manager=self.oauth)
        self.home_assistant = HomeAssistantIntegration(oauth_manager=self.oauth)
        self.notion = NotionIntegration(oauth_manager=self.oauth)
        self.calendar = CalendarIntegration(oauth_manager=self.oauth)
        self.email = EmailIntegration(oauth_manager=self.oauth)
        self.messaging = MessagingHub()
        with boot_subsystem(self._boot_report, "GoogleDriveIntegration"):
            self.google_drive = GoogleDriveIntegration(oauth_manager=self.oauth)
        with boot_subsystem(self._boot_report, "GoogleContactsIntegration"):
            self.google_contacts = GoogleContactsIntegration(oauth_manager=self.oauth)
        with boot_subsystem(self._boot_report, "Microsoft365Integration"):
            self.microsoft365 = Microsoft365Integration(oauth_manager=self.oauth)
        with boot_subsystem(self._boot_report, "HealthAggregator"):
            whoop = WhoopClient(oauth_manager=self.oauth)
            oura = OuraClient()
            self.health_aggregator = HealthAggregator(whoop=whoop, oura=oura)
        with boot_subsystem(self._boot_report, "LocationEngine"):
            from perception.location import LocationEngine
            self.location_engine = LocationEngine()
        with boot_subsystem(self._boot_report, "PushChannel"):
            from channels.push import PushChannel
            self.push_channel = PushChannel()
        with boot_subsystem(self._boot_report, "DigitalTwin"):
            from agents.digital_twin import DigitalTwin
            _identity_loader = IdentityLoader(memory=self.memory)
            self.digital_twin = DigitalTwin(memory=self.memory, identity_loader=_identity_loader, llm=_shared_llm)

            from skills.impl.digital_twin_skill import set_twin, DigitalTwinSkillBridge
            from skills.impl import register_instance as _register_twin
            set_twin(self.digital_twin)
            _register_twin("digital_twin", DigitalTwinSkillBridge())
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
            enabled=os.getenv("FERAL_WAKE_WORD", "true").lower() in ("true", "1", "yes"),
        ))

        from skills.impl import register_instance
        if self.spotify:
            register_instance("spotify_music", self.spotify)
        if self.home_assistant:
            register_instance("smart_home_hue", self.home_assistant)
        if self.notion:
            register_instance("notion", self.notion)
        if self.calendar:
            register_instance("calendar_google", self.calendar)
        if self.email:
            register_instance("email", self.email)
        if self.messaging and self.messaging.connected:
            register_instance("messaging_sms", self.messaging)
        if self.health_aggregator:
            register_instance("health_data", self.health_aggregator)
        if self.google_drive:
            register_instance("google_drive", self.google_drive)
        if self.google_contacts:
            register_instance("google_contacts", self.google_contacts)
        if self.microsoft365:
            register_instance("microsoft365", self.microsoft365)

        with boot_subsystem(self._boot_report, "TaskFlowRuntime"):
            self.taskflows = TaskFlowRuntime(memory_store=self.memory)
            await self.taskflows.start()

        with boot_subsystem(self._boot_report, "Orchestrator", optional=False):
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
            if self.tool_genesis:
                self.orchestrator.set_tool_genesis(self.tool_genesis)
            if self.agent_mitosis:
                self.orchestrator.set_mitosis_engine(self.agent_mitosis)

        with boot_subsystem(self._boot_report, "Supervisor"):
            # One seat that sees every input the Brain acts on. Wraps the
            # orchestrator's three public entry points with an audit +
            # kill-switch layer. Keeps the orchestrator unchanged.
            from agents.supervisor import Supervisor as _Supervisor

            def _broadcast_supervisor_event(frame: dict):
                if not self.sessions:
                    return None
                async def _fan():
                    for sid in list(self.sessions.keys()):
                        try:
                            await self.send_to_session(sid, frame)
                        except Exception:
                            pass
                return _fan()

            self.supervisor = _Supervisor(broadcaster=_broadcast_supervisor_event)
            self.supervisor.wrap(self.orchestrator)

        with boot_subsystem(self._boot_report, "TwinPolicyEngine"):
            # Digital-twin policy + approval queue. The twin's execute()
            # checks this engine before acting on the user's behalf; the
            # engine in turn respects the Supervisor kill switch.
            from agents.twin_policy import TwinPolicyEngine as _TPE
            self.twin_policy = _TPE(supervisor=self.supervisor)
            if self.digital_twin is not None:
                self.digital_twin.set_policy_engine(self.twin_policy)

        with boot_subsystem(self._boot_report, "RealtimeProxy"):
            self.realtime_proxy = RealtimeProxy(
                skill_registry=self.skill_registry,
                skill_executor=self.orchestrator.executor if self.orchestrator else None,
                memory=self.memory,
                perception=self.perception,
                send_to_node=self._send_dict_to_node,
                send_to_session=self.send_to_session,
                identity_workspace=self.identity_workspace,
            )

        with boot_subsystem(self._boot_report, "VoiceRouter"):
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

        with boot_subsystem(self._boot_report, "GeminiRealtimeProxy"):
            self.gemini_proxy = GeminiRealtimeProxy(
                skill_registry=self.skill_registry,
                skill_executor=self.orchestrator.executor if self.orchestrator else None,
                memory=self.memory,
                perception=self.perception,
                send_to_node=self._send_dict_to_node,
                send_to_session=self.send_to_session,
            )
            if self.voice_router:
                self.voice_router.set_gemini_proxy(self.gemini_proxy)

        with boot_subsystem(self._boot_report, "MethodRegistry"):
            self.gateway_registry = MethodRegistry()
            register_core_methods(self.gateway_registry, self)

        with boot_subsystem(self._boot_report, "HardwareMesh"):
            self.hardware_mesh = HardwareMesh(
                device_registry=self.device_registry,
                daemons=self.daemons,
            )

        with boot_subsystem(self._boot_report, "IdentityWorkspace"):
            self.identity_workspace = IdentityWorkspace()
            self.identity_workspace.sync_tools_from_registry(self.skill_registry)

        self.screen_loop = None
        with boot_subsystem(self._boot_report, "ScreenLoop"):
            from perception.screen_loop import ScreenLoop
            self.screen_loop = ScreenLoop(
                perception=self.perception,
                memory=self.memory,
                llm=_shared_llm,
                scene_analyzer=self.scene,
            )
            import asyncio
            asyncio.create_task(self.screen_loop.start())

        self.session_handoff = None
        with boot_subsystem(self._boot_report, "SessionHandoffManager"):
            from agents.session_handoff import SessionHandoffManager
            self.session_handoff = SessionHandoffManager(
                sessions=self.sessions,
                daemons=self.daemons,
                memory=self.memory,
                send_to_session=self.send_to_session,
            )

        with boot_subsystem(self._boot_report, "GenUIEngine"):
            self.genui_engine = GenUIEngine(llm=_shared_llm)
            self.service_providers = ServiceProviderRegistry()
            if self.orchestrator:
                self.orchestrator.set_genui_engine(self.genui_engine)

        with boot_subsystem(self._boot_report, "AppRegistry"):
            # Install directory + SQLite index of third-party GenUI apps.
            # HybridGenerator wraps GenUIEngine to add the authored /
            # cached / regenerate branches the plan specifies.
            self.hybrid_genui = HybridGenerator(
                genui_engine=self.genui_engine,
                cache_dir=default_hybrid_cache_dir(),
            )
            self.app_registry = AppRegistry(
                db_path=default_apps_db_path(),
                apps_dir=default_apps_dir(),
                hybrid_generator=self.hybrid_genui,
            )

        with boot_subsystem(self._boot_report, "BrowserController"):
            self.browser = BrowserController()
            self._register_browser_skill()

        with boot_subsystem(self._boot_report, "ApprovalManager"):
            from security.exec_approvals import ApprovalManager
            self.approval_manager = ApprovalManager()

        with boot_subsystem(self._boot_report, "DockerSandbox"):
            from security.docker_sandbox import get_sandbox
            self.docker_sandbox = get_sandbox()
        # The sandbox object may import cleanly even when the Docker daemon
        # is not actually reachable — in that case we can't execute anything,
        # so mark the subsystem DEGRADED rather than the misleading green OK.
        try:
            if self.docker_sandbox is None:
                self._boot_report.mark_degraded(
                    "DockerSandbox",
                    "Docker not installed — code execution skill disabled",
                )
            elif hasattr(self.docker_sandbox, "available") and not self.docker_sandbox.available():
                self._boot_report.mark_degraded(
                    "DockerSandbox",
                    "Docker daemon not running — start Docker Desktop to enable code exec",
                )
        except Exception as _e:
            self._boot_report.mark_degraded(
                "DockerSandbox",
                f"availability probe failed: {type(_e).__name__}",
            )

        with boot_subsystem(self._boot_report, "CronService"):
            from agents.scheduler import CronService
            self.cron_service = CronService()
            self.scheduler = self.cron_service
            self.skill_registry.set_cron_service(self.cron_service)

        with boot_subsystem(self._boot_report, "BaselineEngine"):
            _baseline_db = str(feral_home() / "baselines.db")
            self.baseline_engine = BaselineEngine(db_path=_baseline_db)

        with boot_subsystem(self._boot_report, "AboutMeStore"):
            _about_me_db = str(feral_home() / "about_me.db")
            self.about_me = AboutMeStore(db_path=_about_me_db)
            self.memory.set_about_me_store(self.about_me)

        with boot_subsystem(self._boot_report, "IdeasEngine"):
            _ideas_db = str(feral_home() / "ideas.db")
            _ideas_store = IdeasStore(db_path=_ideas_db)

            def _on_ideas_updated(_ideas):
                try:
                    import asyncio as _aio
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    return
                loop.create_task(self.broadcast_event("ideas_updated", {"count": len(_ideas)}))

            try:
                _settings = self.config.get_settings() if hasattr(self.config, "get_settings") else {}
            except Exception:
                _settings = {}
            _polish_enabled = bool((_settings or {}).get("ideas_llm_polish", False))

            self.ideas_engine = IdeasEngine(
                store=_ideas_store,
                consciousness=self.consciousness,
                baseline=self.baseline_engine,
                about_me=self.about_me,
                on_ideas_updated=_on_ideas_updated,
                llm_polish_enabled=_polish_enabled,
            )
            if self.baseline_engine is not None:
                self.baseline_engine.on_alert(self.ideas_engine.handle_baseline_alert)

        with boot_subsystem(self._boot_report, "SomaticEngine"):
            from perception.somatic import SomaticEngine
            self.somatic_engine = SomaticEngine()
            if self.orchestrator:
                self.orchestrator.set_somatic_engine(self.somatic_engine)

        with boot_subsystem(self._boot_report, "ToolGenesisEngine"):
            from agents.tool_genesis import ToolGenesisEngine
            _genesis_db = str(feral_data_home() / "tool_genesis.db")
            self.tool_genesis = ToolGenesisEngine(llm=_shared_llm, db_path=_genesis_db)
            if self.orchestrator:
                self.orchestrator.set_tool_genesis(self.tool_genesis)

        with boot_subsystem(self._boot_report, "AgentMitosisEngine"):
            from agents.agent_mitosis import AgentMitosisEngine
            _mitosis_db = str(feral_data_home() / "agent_mitosis.db")
            self.agent_mitosis = AgentMitosisEngine(llm=_shared_llm, memory=self.memory, db_path=_mitosis_db)
            if self.orchestrator:
                self.orchestrator.set_mitosis_engine(self.agent_mitosis)

        with boot_subsystem(self._boot_report, "IntentCompiler"):
            from agents.intent_compiler import IntentCompiler
            _intent_db = str(feral_data_home() / "intents.db")
            self.intent_compiler = IntentCompiler(llm=_shared_llm, db_path=_intent_db)

        if self.ideas_engine is not None:
            async def _ideas_daily_brief_loop():
                while True:
                    now = time.time()
                    dt = datetime.fromtimestamp(now).astimezone()
                    target = dt.replace(hour=7, minute=30, second=0, microsecond=0)
                    if dt >= target:
                        target = target.replace(day=target.day) + _timedelta(days=1)
                    wait_s = max(60.0, (target.timestamp() - now))
                    await asyncio.sleep(wait_s)
                    try:
                        self.ideas_engine.morning_brief()
                    except Exception as exc:
                        logger.debug("Ideas morning_brief failed: %s", exc)

            from datetime import datetime, timedelta as _timedelta
            import asyncio
            asyncio.create_task(_ideas_daily_brief_loop())
            try:
                self.ideas_engine.morning_brief()
            except Exception as exc:
                logger.debug("Ideas initial morning_brief failed: %s", exc)

        self.proactive = None
        with boot_subsystem(self._boot_report, "ProactiveEngine"):
            from agents.proactive_engine import ProactiveEngine
            self.proactive = ProactiveEngine(
                perception=self.perception,
                memory=self.memory,
                orchestrator=self.orchestrator,
                llm=_shared_llm,
                calendar=self.calendar,
                health_aggregator=self.health_aggregator,
                baseline_engine=self.baseline_engine,
            )

            async def _proactive_delivery(msg):
                alert = {
                    "trigger_id": msg.trigger_id,
                    "priority": msg.priority.name,
                    "title": msg.title,
                    "body": msg.body,
                    "action": msg.action,
                    "action_payload": msg.action_payload,
                    "sdui": msg.sdui,
                    "voice_text": msg.voice_text,
                }
                await self.broadcast_event("proactive_alert", alert)

            self.proactive.on_message(_proactive_delivery)
            import asyncio
            asyncio.create_task(self.proactive.start())

        with boot_subsystem(self._boot_report, "MQTTBridge"):
            self.mqtt_bridge = MQTTBridge()
            if self.mqtt_bridge.configured:
                await self.mqtt_bridge.start()

        with boot_subsystem(self._boot_report, "EmailWatcher"):
            async def _handle_email(incoming):
                text = (
                    f'New email from {incoming.sender}: "{incoming.subject}"\n\n'
                    f"{incoming.body[:2000]}"
                )
                for sid in list(self.sessions.keys())[:1]:
                    await self.orchestrator.handle_command(
                        sid,
                        text,
                        context={
                            "source": "email",
                            "message_id": incoming.message_id,
                        },
                    )

            self.email_watcher = EmailWatcher(on_email=_handle_email)
            if self.email_watcher.configured:
                await self.email_watcher.start()

        with boot_subsystem(self._boot_report, "mDNS"):
            from services.mdns import advertise_brain, discover_phone_bridge
            from config.runtime import brain_port
            advertise_brain(port=brain_port())

            try:
                settings = self.config.get_settings() if hasattr(self.config, "get_settings") else {}
            except Exception:
                settings = {}
            phone_url = (settings or {}).get("phone_bridge_url") or os.environ.get("FERAL_PHONE_BRIDGE_URL", "")
            if phone_url == "auto":
                discovered = discover_phone_bridge(timeout=2.5)
                if discovered:
                    logger.info("mDNS: phone bridge auto-discovered at %s", discovered)
                    os.environ["FERAL_PHONE_BRIDGE_URL"] = discovered
                    try:
                        if hasattr(self.config, "set_setting"):
                            self.config.set_setting("phone_bridge_url_resolved", discovered)
                    except Exception:
                        pass
                else:
                    logger.info("mDNS: no phone bridge found on LAN (continuing without)")

        # Wire inbound channels to the orchestrator
        await self._start_channels()

        if os.environ.get("FERAL_DEMO"):
            logger.warning("FERAL_DEMO is deprecated and ignored. Use FERAL_DEV_DEMO=1 for dev-only demo mode.")

        self._demo = None
        if os.environ.get("FERAL_DEV_DEMO", "").lower() in ("1", "true", "yes"):
            with boot_subsystem(self._boot_report, "DemoMode"):
                from demo.seed import seed_demo_identity, seed_demo_memory
                from demo.simulator import DemoOrchestrator
                seed_demo_identity()
                seed_demo_memory(self.memory)
                self._demo = DemoOrchestrator()

                async def _push_demo_telemetry(data):
                    wb = data.get("wristband", {})
                    for sid in list(self.sessions):
                        frame = self.perception.get_frame(sid)
                        if frame and wb:
                            frame.heart_rate = wb.get("heart_rate_bpm", 0)
                            frame.spo2_pct = int(wb.get("spo2_pct", 0))
                            frame.skin_temperature_c = wb.get("skin_temp_c", 0.0)
                            frame.activity_state = wb.get("activity", "resting")
                        if self.somatic_engine and wb:
                            self.somatic_engine.update_biometrics(
                                sid,
                                heart_rate=float(wb.get("heart_rate_bpm", 0)),
                                spo2_pct=float(wb.get("spo2_pct", 0)),
                                skin_temp_c=float(wb.get("skin_temp_c", 0)),
                            )
                    await self.broadcast_event("dashboard_update", await _get_dashboard_data_safe())

                async def _get_dashboard_data_safe():
                    try:
                        from api.routes.dashboard import _get_dashboard_data
                        return await _get_dashboard_data()
                    except Exception:
                        return {}

                self._demo.on_telemetry(_push_demo_telemetry)
                self._demo.set_refs(self.orchestrator, self.sessions)
                import asyncio
                asyncio.create_task(self._demo.start())

        self._boot_report.total_elapsed_ms = (time.time() - _boot_start) * 1000
        self._boot_report.log_summary()

        stats = self.memory.stats()
        demo_tag = " [DEMO MODE]" if self._demo else ""
        logger.info(
            f"Brain v{__version__} initialized{demo_tag} — {len(self.skill_registry.skills)} skills, "
            f"{stats['notes']} notes, {stats['knowledge_triples']} knowledge triples, "
            f"{stats['episodes']} episodes | Self-learning: ON | Vault: {len(self.vault.list_keys()) if self.vault else 0} keys"
        )

    async def _start_channels(self):
        """Wire inbound channel messages to the orchestrator and start configured channels."""
        if not self.channel_manager or not self.orchestrator:
            return

        brain = self

        async def _channel_message_handler(channel_msg: ChannelMessage) -> ChannelResponse:
            channel_session_id = f"channel_{channel_msg.channel_type}_{channel_msg.user_id}"
            text = channel_msg.text or ""
            if not text:
                return ChannelResponse(text="")

            if brain.memory and brain.sessions:
                desktop_sid = next(iter(brain.sessions), None)
                if desktop_sid:
                    history = brain.memory.working_get(desktop_sid, limit=10)
                    if history:
                        brain.memory.working_replace(channel_session_id, list(history))

            if brain.session_handoff:
                # Messaging bridges are channels, not phones. Labelling them
                # "phone" made every Telegram/Slack/Discord session show up
                # as a permanently-connected phone even when the user never
                # paired one. Honest label = "channel" (see NODE_TYPES).
                brain.session_handoff.register_device(
                    channel_session_id,
                    "channel",
                    node_id=f"{channel_msg.channel_type}_{channel_msg.user_id}",
                )

            brain._channel_collectors[channel_session_id] = []
            try:
                await brain.orchestrator.handle_command(channel_session_id, text, context={
                    "source": "channel",
                    "channel": channel_msg.channel_type,
                    "user_id": channel_msg.user_id,
                    "username": channel_msg.username,
                })
            except Exception as e:
                logger.warning(f"Channel command failed: {e}")
                return ChannelResponse(text=f"Error: {e}")
            finally:
                collected = brain._channel_collectors.pop(channel_session_id, [])

            response_text = "\n".join(collected) if collected else "Done."
            return ChannelResponse(text=response_text)

        self.channel_manager.set_handler(_channel_message_handler)

        def _cred(key: str) -> str:
            """Read a channel credential from env, falling back to credentials.json."""
            v = os.environ.get(key, "")
            if v:
                return v
            try:
                if self.config and hasattr(self.config, "get_credential"):
                    v = self.config.get_credential(key) or ""
                    if v:
                        os.environ[key] = v
                        return v
            except Exception:
                pass
            try:
                import json as _json
                creds_path = feral_home() / "credentials.json"
                if creds_path.exists():
                    creds = _json.loads(creds_path.read_text())
                    v = creds.get(key) or ""
                    if v:
                        os.environ[key] = v
            except Exception:
                pass
            return v

        channel_configs = {
            "telegram": {
                "bot_token": _cred("FERAL_TELEGRAM_BOT_TOKEN"),
                "enabled": bool(_cred("FERAL_TELEGRAM_BOT_TOKEN")),
            },
            "discord": {
                "bot_token": _cred("FERAL_DISCORD_BOT_TOKEN"),
                "enabled": bool(_cred("FERAL_DISCORD_BOT_TOKEN")),
            },
            "slack": {
                "bot_token": _cred("FERAL_SLACK_BOT_TOKEN"),
                "app_token": _cred("FERAL_SLACK_APP_TOKEN"),
                "enabled": bool(_cred("FERAL_SLACK_BOT_TOKEN")),
            },
            "whatsapp": {
                "access_token": _cred("FERAL_WHATSAPP_ACCESS_TOKEN"),
                "phone_number_id": _cred("FERAL_WHATSAPP_PHONE_NUMBER_ID"),
                "enabled": bool(_cred("FERAL_WHATSAPP_ACCESS_TOKEN") and _cred("FERAL_WHATSAPP_PHONE_NUMBER_ID")),
            },
        }

        started = []
        for ch_type, ch_config in channel_configs.items():
            if ch_config.get("enabled"):
                try:
                    await self.channel_manager.start_channel(ch_type, ch_config)
                    started.append(ch_type)
                except Exception as e:
                    logger.warning(f"Channel {ch_type} start failed: {e}")

        if started:
            logger.info(f"Channels started: {', '.join(started)}")
        else:
            logger.debug("No messaging channels configured (set FERAL_TELEGRAM_BOT_TOKEN etc.)")

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
                        url=endpoint.get("url", f"feral://browser/{endpoint_id}"),
                        description=str(endpoint.get("description", "")),
                        params=params,
                        returns_description=str(endpoint.get("returns_description", "Browser action result")),
                        ui_hint=endpoint.get("ui_hint"),
                    )
                )

            manifest = SkillManifest(
                skill_id=str(raw_manifest.get("skill_id", "browser")),
                version=str(raw_manifest.get("version", "1.0.0")),
                author="feral-core",
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
        """Load API keys from ~/.feral/credentials.json into environment.

        If ``credentials.json`` is missing OR corrupt we fall back to
        reading every known env var out of the BlindVault directly.
        The vault is the authoritative store written by
        ``/api/llm/providers/{id}/configure`` and ``/api/config/credentials``;
        ``credentials.json`` is the plaintext mirror used for boot-time
        convenience. Keeping both loadable means a single-file corruption
        never locks a user out of their provider keys.
        """
        env_keys = [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
            "GROQ_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
            "TOGETHER_API_KEY", "FIREWORKS_API_KEY",
            "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY",
            "TAVILY_API_KEY", "BRAVE_API_KEY", "EXA_API_KEY",
            "SERPER_API_KEY", "GITHUB_TOKEN", "SPOTIFY_CLIENT_ID",
            "PERPLEXITY_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID",
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            # Messaging channels
            "FERAL_TELEGRAM_BOT_TOKEN",
            "FERAL_SLACK_BOT_TOKEN", "FERAL_SLACK_APP_TOKEN", "FERAL_SLACK_SIGNING_SECRET",
            "FERAL_DISCORD_BOT_TOKEN",
            "FERAL_WHATSAPP_PHONE_NUMBER_ID", "FERAL_WHATSAPP_ACCESS_TOKEN",
            "FERAL_WHATSAPP_VERIFY_TOKEN", "FERAL_WHATSAPP_APP_SECRET",
        ]
        loaded: list[str] = []
        creds: dict = {}
        creds_path = feral_home() / "credentials.json"
        creds_corrupt = False
        if creds_path.exists():
            try:
                import json as _json
                creds = _json.loads(creds_path.read_text())
            except Exception as exc:
                creds_corrupt = True
                logger.warning(
                    "credentials.json is corrupt (%s) — falling back to vault", exc,
                )

        for key in env_keys:
            if creds.get(key) and not os.environ.get(key):
                os.environ[key] = creds[key]
                loaded.append(key)
        if creds.get("web_search") and not os.environ.get("TAVILY_API_KEY"):
            os.environ["TAVILY_API_KEY"] = creds["web_search"]
            loaded.append("TAVILY_API_KEY")

        # Vault fallback — only for keys still missing from env.
        if creds_corrupt or not loaded:
            try:
                from security.vault import BlindVault
                vault = BlindVault()
                for key in env_keys:
                    if os.environ.get(key):
                        continue
                    val = vault.retrieve(key) if hasattr(vault, "retrieve") else None
                    if val:
                        os.environ[key] = val
                        loaded.append(key + "(vault)")
            except Exception as exc:
                logger.debug("vault fallback during boot failed: %s", exc)

        if loaded:
            logger.info(f"Loaded credentials: {', '.join(loaded)}")

    async def send_to_session(self, session_id: str, msg: FeralMessage):
        ws = self.sessions.get(session_id)
        if ws:
            await ws.send_json(msg.model_dump())
        elif session_id in self._channel_collectors:
            payload = msg.payload or {}
            text = payload.get("text", "")
            if text:
                self._channel_collectors[session_id].append(text)

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

    async def send_to_daemon(self, node_id: str, msg: FeralMessage):
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
