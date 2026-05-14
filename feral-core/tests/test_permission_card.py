"""Phase 6 (audit-r10 overhaul) — permission_card flow.

Three layers under test:
1. ``parse_permission_error`` + ``build_permission_card`` — pure
   string → dict transforms. No I/O.
2. ``card_for_action_result`` — adapter that inspects a HUP envelope.
3. ``ToolRunner.execute_capability_action`` end-to-end — when the
   node returns ``permission_denied:<NSKey>``, the orchestrator's
   ``send`` is called with a ``FeralMessage(type="sdui", ...)``
   carrying the card root.
"""
from __future__ import annotations

import pytest

from agents.permission_card import (
    PERMISSION_CATALOG,
    build_permission_card,
    card_for_action_result,
    parse_permission_error,
)


# ─── Parsing ──────────────────────────────────────────────────────


class TestParsePermissionError:
    def test_matches_canonical_shape(self):
        assert parse_permission_error("permission_denied:NSContactsUsageDescription") \
            == "NSContactsUsageDescription"

    def test_strips_whitespace(self):
        # Skills written quickly sometimes have a stray space.
        assert parse_permission_error("permission_denied: NSContactsUsageDescription") \
            == "NSContactsUsageDescription"

    def test_returns_none_for_unrelated_errors(self):
        assert parse_permission_error("phone.call.start: device cannot open URL") is None
        assert parse_permission_error("capability_unavailable: ...") is None

    def test_returns_none_for_missing_key(self):
        # `permission_denied:` with nothing after is not a usable card.
        assert parse_permission_error("permission_denied:") is None
        assert parse_permission_error("permission_denied:   ") is None

    def test_handles_none_and_empty(self):
        assert parse_permission_error(None) is None
        assert parse_permission_error("") is None


# ─── Building ─────────────────────────────────────────────────────


class TestBuildPermissionCard:
    def test_known_key_uses_catalog_copy(self):
        card = build_permission_card(
            "NSContactsUsageDescription",
            skill_id="contacts",
            action="phone.contact.lookup",
            original_error="permission_denied:NSContactsUsageDescription",
        )
        assert card["type"] == "permission_card"
        assert card["permission_key"] == "NSContactsUsageDescription"
        assert card["title"] == PERMISSION_CATALOG["NSContactsUsageDescription"]["title"]
        assert card["ios_deeplink"] == "app-settings:"
        assert card["skill_id"] == "contacts"
        assert card["action"] == "phone.contact.lookup"
        assert card["retryable"] is True
        assert card["_original_error"] == "permission_denied:NSContactsUsageDescription"

    def test_health_key_uses_health_deeplink(self):
        # Apple Health has a dedicated deeplink — pin it so future
        # catalog edits don't silently lose this affordance.
        card = build_permission_card("NSHealthShareUsageDescription")
        assert card["ios_deeplink"] == "x-apple-health://"

    def test_unknown_key_falls_back_to_generic_card(self):
        card = build_permission_card("NSSomeFutureFrameworkUsageDescription")
        assert card["type"] == "permission_card"
        assert card["permission_key"] == "NSSomeFutureFrameworkUsageDescription"
        assert "FERAL needs" in card["title"]
        assert card["ios_deeplink"] == "app-settings:"


# ─── Adapter ─────────────────────────────────────────────────────


class TestCardForActionResult:
    def test_returns_card_for_permission_denied_envelope(self):
        result = {
            "success": False,
            "status_code": 403,
            "error": "permission_denied:NSAppleMusicUsageDescription",
            "data": None,
        }
        card = card_for_action_result(result, skill_id="music", action="phone.music.play")
        assert card is not None
        assert card["permission_key"] == "NSAppleMusicUsageDescription"
        assert card["action"] == "phone.music.play"

    def test_returns_none_for_success(self):
        assert card_for_action_result({"success": True, "data": {}}) is None

    def test_returns_none_for_other_errors(self):
        result = {"success": False, "error": "phone.call.start: missing param"}
        assert card_for_action_result(result) is None

    def test_returns_none_for_non_dict(self):
        assert card_for_action_result("not a dict") is None
        assert card_for_action_result(None) is None


# ─── End-to-end: tool runner emits the card frame ────────────────


class _RecordingOrchestrator:
    """Captures every ``send(session_id, FeralMessage)`` call so the
    test can assert the card frame was emitted with the right shape.
    """

    def __init__(self, registry):
        self.daemons: dict = {}
        self.capability_registry = registry
        self.sent: list = []

    async def send(self, session_id, message):
        self.sent.append((session_id, message))


@pytest.mark.asyncio
async def test_execute_capability_action_emits_permission_card(monkeypatch):
    from agents.tool_runner import ToolRunner
    from memory.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry()
    reg.register_node(
        "iphone-1", node_type="phone", platform="ios",
        skills=[{"actions": [{"name": "phone.contact.lookup"}]}],
    )
    orch = _RecordingOrchestrator(reg)
    orch.daemons["iphone-1"] = object()  # presence-only stub
    runner = ToolRunner(orch)

    async def fake_dispatch(session_id, node_id, action, args, timeout=30.0):
        return {
            "success": False,
            "status_code": 403,
            "error": "permission_denied:NSContactsUsageDescription",
            "data": None,
        }

    monkeypatch.setattr(runner, "execute_daemon_command_with_ack", fake_dispatch)

    result = await runner.execute_capability_action(
        session_id="primary",
        action="phone.contact.lookup",
        args={"query": "John"},
    )

    # Wire result is preserved untouched — the LLM still sees the
    # truth, including the structured permission_denied prefix.
    assert result["success"] is False
    assert result["error"] == "permission_denied:NSContactsUsageDescription"

    # And exactly one SDUI frame was emitted to the client with the
    # permission_card root.
    sdui_frames = [m for _, m in orch.sent if m.type == "sdui"]
    assert len(sdui_frames) == 1
    root = sdui_frames[0].payload["root"]
    assert root["type"] == "permission_card"
    assert root["permission_key"] == "NSContactsUsageDescription"
    assert root["action"] == "phone.contact.lookup"


@pytest.mark.asyncio
async def test_execute_capability_action_no_card_on_other_failures(monkeypatch):
    """Regression: only permission_denied:* triggers a card — other
    failures (timeout, missing param, schema) must NOT mint a card
    or the chat fills with spurious Settings prompts."""
    from agents.tool_runner import ToolRunner
    from memory.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry()
    reg.register_node(
        "iphone-1", node_type="phone", platform="ios",
        skills=[{"actions": [{"name": "phone.call.start"}]}],
    )
    orch = _RecordingOrchestrator(reg)
    orch.daemons["iphone-1"] = object()
    runner = ToolRunner(orch)

    async def fake_dispatch(session_id, node_id, action, args, timeout=30.0):
        return {
            "success": False,
            "status_code": 400,
            "error": "phone.call.start requires `number` or `facetime_id`",
            "data": None,
        }

    monkeypatch.setattr(runner, "execute_daemon_command_with_ack", fake_dispatch)

    await runner.execute_capability_action(
        session_id="primary",
        action="phone.call.start",
        args={},
    )

    sdui_frames = [m for _, m in orch.sent if m.type == "sdui"]
    assert sdui_frames == []
