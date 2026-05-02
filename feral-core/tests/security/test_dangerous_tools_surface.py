"""Focused tests for the dangerous-tool surface deny-list and surface
metadata propagation through the orchestrator/ToolRunner stack.

Two contracts are exercised here:

1. ``security.dangerous_tools.is_tool_allowed`` honours BOTH naming
   conventions used in the codebase — legacy dotted (``shell.exec``) and
   modern skill__endpoint (``desktop_control__shell_command``) — so a
   single deny-list entry catches every shape the gateway might see.
2. ``ToolRunner.enforce_safety`` and ``execute_tool_call_for_llm`` honour
   per-call ``surface`` overrides AND the per-session surface map populated
   by ``Orchestrator._stamp_session_surface``, so a tool that is only
   denied on ``http_api`` is correctly blocked when invoked from the REST
   surface and correctly allowed (modulo per-tool consent) when invoked
   from the websocket surface.

These tests deliberately avoid spinning up a full server; they exercise
the safety library and the runner unit so the gating logic is contracted
in isolation and stays fast.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.tool_runner import ToolRunner
from security.dangerous_tools import (
    DangerLevel,
    SURFACE_DENY_LISTS,
    denied_tools_for_surface,
    get_danger_level,
    is_tool_allowed,
    requires_approval,
    resolve_surface_from_context,
)
from security.exec_approvals import ApprovalManager


# ---------------------------------------------------------------------------
# Naming-agnostic deny-list matching
# ---------------------------------------------------------------------------


class TestDenyListNamingCompatibility:
    """``shell.exec`` and ``shell__exec`` must hit the same policy entry."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "shell.exec",
            "shell__exec",
            "system.run",
            "system__run",
            "docker.exec",
            "docker__exec",
            "browser.evaluate",
            "browser__evaluate",
            "fs.delete",
            "fs__delete",
            "process.spawn",
            "process__spawn",
        ],
    )
    def test_http_api_denies_dotted_and_underscore_form(self, tool_name):
        assert is_tool_allowed(tool_name, "http_api") is False, (
            f"deny-list FAILED: {tool_name!r} should be denied on http_api"
        )

    @pytest.mark.parametrize(
        "tool_name",
        [
            "desktop_control__shell_command",
            "desktop_control__shell",
            "computer_use__bash",
            "code_interpreter__execute",
        ],
    )
    def test_modern_skill_endpoint_ids_blocked_on_http_api(self, tool_name):
        """Tools named with the modern ``skill__endpoint`` convention that
        carry shell/code-exec semantics must be explicitly denied on the
        remote http_api surface."""
        assert is_tool_allowed(tool_name, "http_api") is False

    def test_websocket_still_only_denies_docker(self):
        """The interactive operator channel intentionally lets shell tools
        through — they are still gated by per-tool consent. Only the
        host-level container escape stays a hard surface deny."""
        assert is_tool_allowed("docker.exec", "websocket") is False
        assert is_tool_allowed("docker__exec", "websocket") is False
        assert is_tool_allowed("shell.exec", "websocket") is True
        assert is_tool_allowed("desktop_control__shell_command", "websocket") is True

    def test_local_cli_unrestricted(self):
        for tool in ("shell.exec", "system__run", "docker__exec"):
            assert is_tool_allowed(tool, "local_cli") is True

    def test_unknown_surface_passes_through(self):
        """Unknown surfaces are treated as unrestricted (no deny entry)."""
        assert is_tool_allowed("shell.exec", "totally_unknown_surface") is True

    def test_unknown_tool_is_allowed(self):
        assert is_tool_allowed("notes_memory__search", "http_api") is True

    def test_bare_endpoint_does_not_promote_unrelated_skill(self):
        """Adding ``shell.exec`` must not silently deny ``svc__exec`` for an
        unrelated skill — deny entries are specific, not pattern-prefix
        matches on the bare endpoint."""
        assert is_tool_allowed("payments__exec", "http_api") is True
        assert is_tool_allowed("notes_memory__delete_note", "http_api") is True

    def test_danger_level_respects_both_namings(self):
        assert get_danger_level("shell.exec") == DangerLevel.CRITICAL
        assert get_danger_level("shell__exec") == DangerLevel.CRITICAL
        assert get_danger_level("desktop_control__shell_command") == DangerLevel.CRITICAL
        assert requires_approval("computer_use__bash") is True

    def test_denied_tools_for_surface_includes_modern_ids(self):
        denies = denied_tools_for_surface("http_api")
        assert "desktop_control__shell_command" in denies
        assert "shell.exec" in denies


# ---------------------------------------------------------------------------
# Surface resolution from handle_command context
# ---------------------------------------------------------------------------


class TestResolveSurfaceFromContext:
    """``resolve_surface_from_context`` maps ``context["source"]`` strings
    to the right surface so deeper safety checks see the truth."""

    @pytest.mark.parametrize(
        "source,expected",
        [
            ("webhook", "http_api"),
            ("phone_surface", "http_api"),
            ("channel", "http_api"),
            ("cron", "http_api"),
            ("proactive", "http_api"),
            ("voice", "websocket"),
            ("voice_text", "websocket"),
            ("voice_chained", "websocket"),
            ("voice_realtime", "websocket"),
            ("node_text", "websocket"),
            ("gesture", "websocket"),
            ("vision_ask", "websocket"),
            ("cli", "local_cli"),
            ("local_cli", "local_cli"),
        ],
    )
    def test_known_sources_map(self, source, expected):
        assert resolve_surface_from_context({"source": source}) == expected

    def test_explicit_surface_key_wins(self):
        assert (
            resolve_surface_from_context({"surface": "http_api", "source": "voice"})
            == "http_api"
        )

    def test_unknown_source_falls_back_to_default(self):
        assert resolve_surface_from_context({"source": "mystery"}) == "websocket"

    def test_none_or_empty_context_uses_default(self):
        assert resolve_surface_from_context(None) == "websocket"
        assert resolve_surface_from_context({}) == "websocket"

    def test_default_override(self):
        assert resolve_surface_from_context(None, default="local_cli") == "local_cli"


# ---------------------------------------------------------------------------
# ToolRunner: surface override and per-session surface lookup
# ---------------------------------------------------------------------------


def _make_runner(*, autonomy_mode: str = "loose") -> ToolRunner:
    """Build a ToolRunner with a lightweight mock orchestrator."""
    orch = MagicMock()
    orch.daemons = {}
    orch.skills = MagicMock()
    orch.skills.skills = {}
    orch.executor = AsyncMock()
    orch.llm = MagicMock()
    orch._mcp_client = None
    orch._send_text = AsyncMock()
    orch._max_iterations = 8
    orch._session_surfaces = {}
    runner = ToolRunner(orch, autonomy_mode=autonomy_mode)
    runner._approval_mgr = ApprovalManager(db_path=":memory:")
    return runner


class TestEnforceSafetySurfaceArg:
    """``enforce_safety`` already accepts a ``surface`` kwarg; the new
    contract is that the underlying matcher uses naming-agnostic
    candidates so modern tool ids hit the same deny list."""

    def test_modern_tool_blocked_on_http_api(self):
        runner = _make_runner()
        result = runner.enforce_safety(
            "desktop_control__shell_command",
            {"cmd": "rm -rf /"},
            session_id="s1",
            surface="http_api",
        )
        assert result is not None
        assert "Surface Policy" in result.get("error", "")
        assert result.get("safety_level") == "deny"

    def test_modern_tool_allowed_on_websocket_passes_surface_gate(self):
        """``desktop_control__shell_command`` is NOT on the websocket
        surface deny-list. ``enforce_safety`` should fall through to the
        per-tool consent flow rather than refusing on the surface gate."""
        runner = _make_runner(autonomy_mode="hybrid")
        result = runner.enforce_safety(
            "desktop_control__shell_command",
            {"cmd": "ls"},
            session_id="s1",
            surface="websocket",
        )
        assert result is not None
        # Hybrid mode + CONFIRM-class tool ⇒ pending approval, NOT a
        # surface-policy denial.
        assert result.get("status") == "pending_approval"
        assert "Surface Policy" not in result.get("error", "")

    def test_legacy_dotted_name_still_blocked(self):
        runner = _make_runner()
        result = runner.enforce_safety(
            "system.run", {}, session_id="s1", surface="http_api",
        )
        assert result is not None
        assert "Surface Policy" in result.get("error", "")


class TestSessionSurfacePropagation:
    """``execute_tool_call_for_llm`` resolves surface from the parent
    orchestrator's ``_session_surfaces`` map when no explicit kwarg is
    passed, so REST callers don't silently fall back to websocket."""

    async def test_http_api_session_blocks_modern_shell_tool(self):
        runner = _make_runner(autonomy_mode="hybrid")
        runner._orch._session_surfaces["s1"] = "http_api"

        result = await runner.execute_tool_call_for_llm(
            "s1",
            {"name": "desktop_control__shell_command", "args": {"cmd": "id"}},
            [],
        )
        assert result.get("safety_level") == "deny"
        assert "Surface Policy" in result.get("error", "")

    async def test_websocket_session_does_not_trigger_surface_deny(self):
        """Same call from the interactive websocket surface should NOT
        fail the surface gate; the per-tool consent flow handles it."""
        runner = _make_runner(autonomy_mode="hybrid")
        runner._orch._session_surfaces["s1"] = "websocket"

        result = await runner.execute_tool_call_for_llm(
            "s1",
            {"name": "desktop_control__shell_command", "args": {"cmd": "id"}},
            [],
        )
        # Pending approval, not surface deny.
        assert result.get("status") == "pending_approval"

    async def test_explicit_surface_kwarg_overrides_session_map(self):
        runner = _make_runner(autonomy_mode="hybrid")
        runner._orch._session_surfaces["s1"] = "websocket"

        result = await runner.execute_tool_call_for_llm(
            "s1",
            {"name": "desktop_control__shell_command", "args": {"cmd": "id"}},
            [],
            surface="http_api",
        )
        assert result.get("safety_level") == "deny"

    async def test_default_unstamped_session_falls_back_to_websocket(self):
        """No session entry ⇒ historical websocket default — preserves
        backward compatibility for callers that haven't been threaded
        through yet."""
        runner = _make_runner(autonomy_mode="hybrid")
        # No entry in _session_surfaces.
        result = await runner.execute_tool_call_for_llm(
            "s1",
            {"name": "docker__exec", "args": {}},
            [],
        )
        # ``docker.exec`` IS on the websocket deny list, so this still
        # short-circuits at the surface gate.
        assert result.get("safety_level") == "deny"
        assert "Surface Policy" in result.get("error", "")


class TestSurfaceDenyListsContract:
    """Lock in the deny list shape so future edits don't silently drop
    enforcement for modern shell tool ids."""

    def test_http_api_contains_required_entries(self):
        denies = SURFACE_DENY_LISTS["http_api"]
        for required in (
            "system.run",
            "docker.exec",
            "browser.evaluate",
            "shell.exec",
            "desktop_control__shell_command",
            "computer_use__bash",
            "code_interpreter__execute",
        ):
            assert required in denies, f"http_api deny set missing {required!r}"

    def test_websocket_contains_docker_only(self):
        denies = SURFACE_DENY_LISTS["websocket"]
        assert "docker.exec" in denies

    def test_local_cli_remains_empty(self):
        assert SURFACE_DENY_LISTS["local_cli"] == set()
