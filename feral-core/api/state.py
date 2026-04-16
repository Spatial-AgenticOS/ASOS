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

from _version import __version__
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
from skills.impl.browser_use import BrowserController
from agents.session_handoff import SessionHandoffManager
from agents.identity_loader import IdentityLoader
from agents.baseline_engine import BaselineEngine
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
        self.somatic_engine = None
        self.tool_genesis = None
        self.agent_mitosis = None
        self.intent_compiler = None
        self.mqtt_bridge = None
        self.email_watcher: Optional[EmailWatcher] = None
        self.device_pairing_store: DevicePairingStore = DevicePairingStore()
        self._boot_report: BootReport = BootReport()

        # Map daemon node_id → list of sessions interested in its data
        self._daemon_session_bindings: dict[str, set[str]] = {}

        # Collectors for channel-based sessions (no WebSocket)
        self._channel_collectors: dict[str, list[str]] = {}

    @property
    def skill_executor(self):
        return self.orchestrator.executor if self.orchestrator else None

    async def init(self):
        _boot_start = time.time()
        self.skill_registry.load_builtin_skills()

        from agents.llm_provider import LLMProvider
        _shared_llm = LLMProvider()
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

        self.realtime_proxy = RealtimeProxy(
            skill_registry=self.skill_registry,
            skill_executor=self.orchestrator.executor if self.orchestrator else None,
            memory=self.memory,
            perception=self.perception,
            send_to_node=self._send_dict_to_node,
            send_to_session=self.send_to_session,
            identity_workspace=self.identity_workspace,
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
        self.voice_router.set_gemini_proxy(self.gemini_proxy)

        self.gateway_registry = MethodRegistry()
        register_core_methods(self.gateway_registry, self)

        self.hardware_mesh = HardwareMesh(
            device_registry=self.device_registry,
            daemons=self.daemons,
        )

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

        self.genui_engine = GenUIEngine(llm=_shared_llm)
        self.service_providers = ServiceProviderRegistry()
        if self.orchestrator:
            self.orchestrator.set_genui_engine(self.genui_engine)

        self.browser = BrowserController()
        self._register_browser_skill()

        with boot_subsystem(self._boot_report, "ApprovalManager"):
            from security.exec_approvals import ApprovalManager
            self.approval_manager = ApprovalManager()

        with boot_subsystem(self._boot_report, "DockerSandbox"):
            from security.docker_sandbox import get_sandbox
            self.docker_sandbox = get_sandbox()

        with boot_subsystem(self._boot_report, "CronService"):
            from agents.scheduler import CronService
            self.cron_service = CronService()
            self.scheduler = self.cron_service
            self.skill_registry.set_cron_service(self.cron_service)

        with boot_subsystem(self._boot_report, "BaselineEngine"):
            _baseline_db = str(feral_home() / "baselines.db")
            self.baseline_engine = BaselineEngine(db_path=_baseline_db)

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
            from services.mdns import advertise_brain
            from config.runtime import brain_port
            advertise_brain(port=brain_port())

        # Wire inbound channels to the orchestrator
        await self._start_channels()

        self._demo = None
        if os.environ.get("FERAL_DEMO", "").lower() in ("1", "true", "yes"):
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
                import asyncio
                asyncio.create_task(self._demo.start())
                asyncio.create_task(self._push_demo_health_telemetry())

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
                brain.session_handoff.register_device(
                    channel_session_id,
                    "phone",
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

        channel_configs = {
            "telegram": {
                "bot_token": os.environ.get("FERAL_TELEGRAM_BOT_TOKEN", ""),
                "enabled": bool(os.environ.get("FERAL_TELEGRAM_BOT_TOKEN")),
            },
            "discord": {
                "bot_token": os.environ.get("FERAL_DISCORD_BOT_TOKEN", ""),
                "enabled": bool(os.environ.get("FERAL_DISCORD_BOT_TOKEN")),
            },
            "slack": {
                "bot_token": os.environ.get("FERAL_SLACK_BOT_TOKEN", ""),
                "app_token": os.environ.get("FERAL_SLACK_APP_TOKEN", ""),
                "enabled": bool(os.environ.get("FERAL_SLACK_BOT_TOKEN")),
            },
            "whatsapp": {
                "access_token": os.environ.get("FERAL_WHATSAPP_ACCESS_TOKEN", ""),
                "phone_number_id": os.environ.get("FERAL_WHATSAPP_PHONE_NUMBER_ID", ""),
                "enabled": bool(os.environ.get("FERAL_WHATSAPP_ACCESS_TOKEN")),
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
        """Load API keys from ~/.feral/credentials.json into environment if not already set."""
        creds_path = feral_home() / "credentials.json"
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

    async def _push_demo_health_telemetry(self):
        """Generate realistic synthetic biometric data for demo/health mode."""
        import asyncio
        import math
        import random

        t = 0
        while True:
            await asyncio.sleep(5)
            t += 5

            if not self.sessions:
                continue

            base_hr = 72 + 10 * math.sin(t / 300) + random.gauss(0, 2)
            hr = max(55, min(110, int(base_hr)))

            if random.random() < 0.01:
                hr = random.randint(95, 115)

            spo2 = max(93, min(100, int(97 + random.gauss(0, 0.8))))
            skin_temp = round(36.5 + 0.3 * math.sin(t / 600) + random.gauss(0, 0.1), 1)

            hour = (time.localtime().tm_hour + t // 3600) % 24
            if 9 <= hour <= 17:
                activity = random.choice(["sedentary", "sedentary", "sedentary", "walking", "active"])
            else:
                activity = random.choice(["sedentary", "sedentary", "resting"])

            activity_level = {"sedentary": 0.1, "walking": 0.5, "active": 0.8, "resting": 0.0}.get(activity, 0.1)

            sensor_data = {
                "vitals": {"ppg_heart_rate": hr, "spo2": spo2},
                "environment": {"skin_temperature": skin_temp, "ambient_light": random.randint(100, 800)},
                "activity": {"state": activity},
            }

            for sid in list(self.sessions.keys()):
                self.perception.update_sensors(sid, sensor_data)

            if self.somatic_engine:
                for sid in list(self.sessions.keys()):
                    self.somatic_engine.update_biometrics(
                        sid, heart_rate=hr, spo2_pct=spo2,
                        skin_temp_c=skin_temp, activity_level=activity_level,
                    )

            if self.proactive:
                for sid in list(self.sessions.keys()):
                    try:
                        await self.proactive.evaluate(sid)
                    except Exception:
                        pass

            if self.orchestrator:
                for sid in list(self.sessions.keys()):
                    try:
                        await self.orchestrator._emit_brain_event(sid, "device_telemetry", {
                            "source": "demo", "hr": hr, "spo2": spo2, "temp": skin_temp, "activity": activity,
                        })
                    except Exception:
                        pass

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
