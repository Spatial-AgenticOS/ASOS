"""End-to-end test: start server, connect WebSocket, send message, verify response."""
import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def mock_brain_state():
    """Create a mock BrainState with minimal subsystems for E2E testing."""
    from api.state import BrainState
    state = BrainState()
    state.sessions = {}
    state.daemons = {}
    state.orchestrator = MagicMock()
    state.orchestrator.handle_command = AsyncMock()
    state.orchestrator.handle_command_stream = AsyncMock()
    state.orchestrator.on_session_disconnect = AsyncMock()
    state.memory = MagicMock()
    state.memory.conversation_list.return_value = []
    state.memory.episode_recent.return_value = []
    state.memory.stats.return_value = {"notes": 0, "episodes": 0}
    state.memory.knowledge_query.return_value = []
    state.memory.wiki_list_pages.return_value = []
    state.memory.wiki_stats.return_value = {"pages": 0}
    state.memory.log_recent.return_value = []
    state.memory.working_push = MagicMock()
    state.memory.working_get = MagicMock(return_value=[])
    state.skill_registry = MagicMock()
    state.skill_registry.skills = {}
    state.skill_registry.list_skills.return_value = []
    state.config_loader = MagicMock()
    state.config_loader.client_safe_dict.return_value = {}
    state.config_loader.export_as_env.return_value = {}
    state.llm = MagicMock()
    state.llm.status.return_value = {"available": False}
    state.identity_workspace = MagicMock()
    state.identity_workspace.read_soul.return_value = "soul"
    state.identity_workspace.read_memory.return_value = ""
    state.identity_workspace.maintenance_cycle = AsyncMock()
    state.baseline_engine = MagicMock()
    state.baseline_engine.summary.return_value = {"metrics_tracked": 0, "recent_alerts": 0, "categories": []}
    state.baseline_engine.get_all_baselines.return_value = []
    state.baseline_engine.get_alerts.return_value = []
    state.perception = MagicMock()
    state.perception.get_frame.return_value = MagicMock(
        heart_rate=0, spo2_pct=0, skin_temperature_c=0, battery_pct=100,
        activity_state="unknown", connected_nodes=[]
    )
    state.channel_manager = MagicMock()
    state.channel_manager.stats.return_value = {}
    state.gateway_registry = MagicMock()
    state.skill_gen = None
    state.bind_session_to_daemon = MagicMock()
    state.voice_router = None
    state.gemini_proxy = None
    state.somatic_engine = None

    from api.boot_report import BootReport
    state._boot_report = BootReport()
    return state


class TestE2EHealthAndDashboard:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, mock_brain_state):
        with patch("api.server.state", mock_brain_state), \
             patch("api.routes.dashboard.state", mock_brain_state), \
             patch("api.routes.config.state", mock_brain_state), \
             patch("api.routes.skills.state", mock_brain_state), \
             patch("api.routes.memory.state", mock_brain_state), \
             patch("api.routes.baseline.state", mock_brain_state), \
             patch("api.routes.security_and_hardware.state", mock_brain_state), \
             patch("api.routes.identity_nodes_sync.state", mock_brain_state), \
             patch("api.routes.devices.state", mock_brain_state), \
             patch("api.routes.timeline.state", mock_brain_state):
            from api.server import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.get("/health")
                assert r.status_code == 200
                data = r.json()
                assert data["status"] == "ok"
                assert "boot" in data

    @pytest.mark.asyncio
    async def test_dashboard_returns_data(self, mock_brain_state):
        with patch("api.server.state", mock_brain_state), \
             patch("api.routes.dashboard.state", mock_brain_state), \
             patch("api.routes.config.state", mock_brain_state), \
             patch("api.routes.skills.state", mock_brain_state), \
             patch("api.routes.memory.state", mock_brain_state), \
             patch("api.routes.baseline.state", mock_brain_state), \
             patch("api.routes.security_and_hardware.state", mock_brain_state), \
             patch("api.routes.identity_nodes_sync.state", mock_brain_state), \
             patch("api.routes.devices.state", mock_brain_state), \
             patch("api.routes.timeline.state", mock_brain_state):
            from api.server import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.get("/api/dashboard")
                assert r.status_code == 200
                data = r.json()
                assert "memory" in data or "sessions" in data


class TestE2EWebSocket:
    def test_websocket_session_connect_and_send(self, mock_brain_state):
        from starlette.testclient import TestClient
        mock_brain_state.audio = MagicMock()
        mock_brain_state.memory.working_clear = MagicMock()
        with patch("api.server.state", mock_brain_state), \
             patch("api.state.state", mock_brain_state), \
             patch("api.routes.dashboard.state", mock_brain_state), \
             patch("api.routes.config.state", mock_brain_state), \
             patch("api.routes.skills.state", mock_brain_state), \
             patch("api.routes.memory.state", mock_brain_state), \
             patch("api.routes.baseline.state", mock_brain_state), \
             patch("api.routes.security_and_hardware.state", mock_brain_state), \
             patch("api.routes.identity_nodes_sync.state", mock_brain_state), \
             patch("api.routes.devices.state", mock_brain_state), \
             patch("api.routes.timeline.state", mock_brain_state), \
             patch("api.server._build_greeting", return_value="Hello"):
            from api.server import app
            client = TestClient(app, raise_server_exceptions=False)
            with client.websocket_connect("/v1/session") as ws:
                greeting = ws.receive_json()
                assert greeting["type"] == "text_response"
                ws.send_json({"hop": "client", "type": "text_command", "payload": {"text": "hello", "context": {}}})
                time.sleep(0.2)
            mock_brain_state.orchestrator.handle_command_stream.assert_called()
