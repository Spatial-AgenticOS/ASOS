"""Tests for handle_ui_event(app_id=...) — app-scoped action dispatch.

These exercise `feral-core/agents/ui_handlers.py::_handle_app_action`
against a real `AppRegistry` with a faked orchestrator so the scoping
+ contract validation paths are proven end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.app_registry import AppRegistry, HybridGenerator
from agents.ui_handlers import handle_ui_event
from models.app_manifest import ActionSpec, AppManifest, SurfaceSpec
from models.skill_manifest import BrandProfile


def _build_manifest() -> AppManifest:
    return AppManifest(
        app_id="demo-app",
        brand=BrandProfile(name="Demo"),
        surfaces=[
            SurfaceSpec(
                surface_id="home",
                kind="authored",
                template_root={"type": "Text", "value": "home"},
                action_contract=[
                    ActionSpec(action_id="open_thread", handler="navigate", target="thread"),
                    ActionSpec(action_id="send", handler="app_event"),
                    ActionSpec(action_id="run_tool", handler="skill_call", target="demo_skill/ping"),
                    ActionSpec(action_id="close_modal", handler="close"),
                    ActionSpec(action_id="bump", handler="patch"),
                ],
            ),
            SurfaceSpec(
                surface_id="thread",
                kind="authored",
                template_root={"type": "Text", "value": "thread"},
                action_contract=[],
            ),
        ],
        entry_surface_id="home",
    )


@pytest.fixture
def registry(tmp_path):
    reg = AppRegistry(
        db_path=str(tmp_path / "apps.db"),
        apps_dir=tmp_path / "apps",
    )
    reg.set_hybrid_generator(HybridGenerator(cache_dir=tmp_path / "cache"))
    src = tmp_path / "src"
    src.mkdir()
    (src / "manifest.json").write_text(_build_manifest().model_dump_json())
    reg.install_from_dir(src)
    return reg


@pytest.fixture
def orchestrator():
    mock = MagicMock()
    mock._send_text = AsyncMock()
    mock._execute_tool_call = AsyncMock()
    mock.handle_command = AsyncMock()
    mock.send = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_unknown_app_replies_polite_not_handle_command(orchestrator):
    mock_state = MagicMock()
    mock_state.app_registry = None
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="send",
            event="tap",
            app_id="whatever",
        )
    orchestrator._send_text.assert_awaited_once()
    orchestrator.handle_command.assert_not_called()


@pytest.mark.asyncio
async def test_uninstalled_app_replies_polite(orchestrator):
    mock_state = MagicMock()
    # registry exists but `get` returns None.
    reg = MagicMock()
    reg.get.return_value = None
    mock_state.app_registry = reg
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="send",
            event="tap",
            app_id="ghost",
        )
    orchestrator._send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_action_rejected(registry, orchestrator):
    mock_state = MagicMock()
    mock_state.app_registry = registry
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="evil_action",
            event="tap",
            app_id="demo-app",
            screen_id="demo-app:home:s1",
        )
    orchestrator._send_text.assert_awaited_once()
    orchestrator.handle_command.assert_not_called()
    orchestrator._execute_tool_call.assert_not_called()


@pytest.mark.asyncio
async def test_navigate_action_pushes_sdui(registry, orchestrator):
    mock_state = MagicMock()
    mock_state.app_registry = registry
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="open_thread",
            event="tap",
            app_id="demo-app",
            screen_id="demo-app:home:s1",
        )
    orchestrator.send.assert_awaited_once()
    msg = orchestrator.send.await_args.args[1]
    assert msg.type == "sdui"
    assert msg.payload["screen_id"].startswith("demo-app:thread:")
    assert msg.payload["root"]["value"] == "thread"


@pytest.mark.asyncio
async def test_skill_call_routes_to_tool_executor(registry, orchestrator):
    mock_state = MagicMock()
    mock_state.app_registry = registry
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="run_tool",
            event="tap",
            value={"foo": "bar"},
            app_id="demo-app",
            screen_id="demo-app:home:s1",
        )
    orchestrator._execute_tool_call.assert_awaited_once()
    call_args = orchestrator._execute_tool_call.await_args
    tool_call = call_args.args[1]
    assert tool_call["name"] == "demo_skill/ping"
    assert tool_call["args"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_app_event_falls_through_to_handle_command(registry, orchestrator):
    mock_state = MagicMock()
    mock_state.app_registry = registry
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="send",
            event="tap",
            value={"text": "hi"},
            app_id="demo-app",
            screen_id="demo-app:home:s1",
        )
    orchestrator.handle_command.assert_awaited_once()
    prompt = orchestrator.handle_command.await_args.args[1]
    assert "demo-app" in prompt and "send" in prompt


@pytest.mark.asyncio
async def test_close_action_acks_without_skill_call(registry, orchestrator):
    mock_state = MagicMock()
    mock_state.app_registry = registry
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="close_modal",
            event="tap",
            app_id="demo-app",
            screen_id="demo-app:home:s1",
        )
    orchestrator._send_text.assert_awaited_once()
    orchestrator._execute_tool_call.assert_not_called()


@pytest.mark.asyncio
async def test_patch_action_logs_and_noops(registry, orchestrator):
    mock_state = MagicMock()
    mock_state.app_registry = registry
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="bump",
            event="tap",
            app_id="demo-app",
            screen_id="demo-app:home:s1",
        )
    orchestrator._execute_tool_call.assert_not_called()
    orchestrator.handle_command.assert_not_called()


@pytest.mark.asyncio
async def test_app_path_does_not_trigger_legacy_call_prefix_routing(registry, orchestrator):
    """call_ prefix is a first-party skill shortcut; must NOT hijack app events."""
    mock_state = MagicMock()
    mock_state.app_registry = registry
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="call_demo_skill/ping",
            event="tap",
            app_id="demo-app",
            screen_id="demo-app:home:s1",
        )
    # Action 'call_demo_skill/ping' is not in the surface contract;
    # the app path rejects, never calls _execute_tool_call.
    orchestrator._execute_tool_call.assert_not_called()
    orchestrator._send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_app_event_preserves_legacy_prefix_routing(orchestrator):
    """Without app_id, the legacy call_ prefix still dispatches."""
    mock_state = MagicMock()
    mock_state.app_registry = None
    with patch("api.state.state", mock_state):
        await handle_ui_event(
            orchestrator,
            session_id="s1",
            action_id="call_demo_skill/ping",
            event="tap",
        )
    orchestrator._execute_tool_call.assert_awaited_once()
