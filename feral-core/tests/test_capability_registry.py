"""Phase 5 (audit-r10 overhaul) — capability registry + API + routing.

Three concerns under test, ordered by blast radius:

1.  ``CapabilityRegistry`` lifecycle — node register / unregister
    behave as advertised, queries return the right surface.
2.  ``GET /api/capabilities`` REST surface — brain-host + node merge,
    correct envelope shape, no auth assumptions (LAN-public).
3.  ``ToolRunner.execute_capability_action`` — routes by registry
    when a handler exists, returns a structured
    ``capability_unavailable`` envelope when not. The "no handler"
    branch is the moral payoff of Phase 5 — the brain stops timing
    out HUP futures and starts answering truthfully.
"""
from __future__ import annotations

import pytest

from memory.capability_registry import CapabilityRegistry, _surface_for_node_type


# ─── Registry lifecycle ──────────────────────────────────────────


class TestCapabilityRegistryLifecycle:
    def test_register_records_node_and_skills(self):
        reg = CapabilityRegistry()
        reg.register_node(
            "iphone-1",
            node_type="phone",
            platform="ios",
            skills=[
                {
                    "id": "phone_call",
                    "name": "Phone Call",
                    "description": "...",
                    "actions": [
                        {"name": "phone.call.start", "summary": "...",
                         "requiresPermission": None}
                    ],
                }
            ],
        )
        assert reg.connected_node_ids() == ["iphone-1"]
        assert reg.has_node_type("phone") is True
        assert reg.has_node_type("glasses") is False

    def test_find_handler_returns_phone_actuator_surface(self):
        reg = CapabilityRegistry()
        reg.register_node(
            "iphone-1",
            node_type="phone",
            platform="ios",
            skills=[{"actions": [{"name": "phone.call.start"}]}],
        )
        handler = reg.find_handler("phone.call.start")
        assert handler is not None
        assert handler.node_id == "iphone-1"
        assert handler.surface == "phone_actuator"
        assert handler.node_type == "phone"
        assert handler.platform == "ios"

    def test_find_handler_returns_none_for_unknown_action(self):
        reg = CapabilityRegistry()
        reg.register_node(
            "iphone-1",
            node_type="phone",
            platform="ios",
            skills=[{"actions": [{"name": "phone.call.start"}]}],
        )
        assert reg.find_handler("desktop.screenshot") is None
        assert reg.find_handler("") is None

    def test_unregister_clears_node(self):
        reg = CapabilityRegistry()
        reg.register_node(
            "iphone-1", node_type="phone", platform="ios",
            skills=[{"actions": [{"name": "phone.call.start"}]}],
        )
        reg.unregister_node("iphone-1")
        assert reg.connected_node_ids() == []
        assert reg.find_handler("phone.call.start") is None
        assert reg.has_node_type("phone") is False

    def test_register_overwrites_prior_record(self):
        # A reconnect must replace not append — otherwise restart loops
        # leak stale skill entries forever.
        reg = CapabilityRegistry()
        reg.register_node(
            "iphone-1", node_type="phone", platform="ios",
            skills=[{"actions": [{"name": "phone.call.start"}]}],
        )
        reg.register_node(
            "iphone-1", node_type="phone", platform="ios",
            skills=[{"actions": [{"name": "phone.music.play"}]}],
        )
        assert reg.find_handler("phone.call.start") is None
        assert reg.find_handler("phone.music.play") is not None

    def test_snapshot_nodes_round_trips_skills(self):
        reg = CapabilityRegistry()
        reg.register_node(
            "iphone-1", node_type="phone", platform="ios",
            skills=[
                {
                    "id": "phone_call",
                    "name": "Phone Call",
                    "actions": [{"name": "phone.call.start"}],
                }
            ],
        )
        snap = reg.snapshot_nodes()
        assert len(snap) == 1
        assert snap[0]["node_id"] == "iphone-1"
        assert snap[0]["surface"] == "phone_actuator"
        assert snap[0]["skills"][0]["id"] == "phone_call"

    def test_surface_mapping_covers_known_kinds(self):
        # The mapping is the single seam between HUP node_type and
        # dangerous_tools execution surfaces — pin it.
        assert _surface_for_node_type("phone") == "phone_actuator"
        assert _surface_for_node_type("tablet") == "phone_actuator"
        assert _surface_for_node_type("glasses") == "glasses_actuator"
        assert _surface_for_node_type("desktop") == "brain_host"
        assert _surface_for_node_type("server") == "brain_host"
        assert _surface_for_node_type("wearable") == "node_actuator"
        assert _surface_for_node_type("unknown_kind") == "node_actuator"
        assert _surface_for_node_type("") == "node_actuator"


# ─── ToolRunner capability-aware routing ─────────────────────────


class _StubOrchestrator:
    """Bare-minimum stand-in for the Orchestrator's surface that
    ``ToolRunner.execute_capability_action`` touches."""

    def __init__(self, registry):
        self.daemons: dict = {}
        self.capability_registry = registry


@pytest.mark.asyncio
async def test_execute_capability_action_returns_unavailable_when_no_handler():
    from agents.tool_runner import ToolRunner

    reg = CapabilityRegistry()  # empty
    orch = _StubOrchestrator(reg)
    runner = ToolRunner(orch)

    result = await runner.execute_capability_action(
        session_id="primary",
        action="phone.call.start",
        args={"number": "+15551234"},
    )
    assert result["success"] is False
    assert result["status_code"] == 404
    assert "capability_unavailable" in result["error"]
    # The truthful envelope must point at WHY — operator complaint #8
    # is exactly "the app said it tried and silently failed".
    assert "phone.call.start" in result["error"]


# ─── GET /api/capabilities ───────────────────────────────────────


def test_capabilities_endpoint_returns_brain_host_and_nodes(monkeypatch):
    """End-to-end through FastAPI: register two nodes, verify the
    JSON envelope merges brain-host skills with the live node catalog.
    """
    from unittest.mock import MagicMock
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    fake_state = MagicMock()
    fake_state.primary_session_id = "primary-1"
    # Brain-host skill manifest — use a duck-typed object so the
    # serializer's getattr path is exercised. The empty dict at the
    # other end pins the dict branch too.
    class _Manifest:
        name = "Read"
        description = "Read a file."
        category = "io"

    fake_state.skill_registry = MagicMock()
    fake_state.skill_registry.skills = {
        "read_file": _Manifest(),
        "noop": {"name": "Noop", "description": "no-op", "category": "test"},
    }
    fake_state.capability_registry = CapabilityRegistry()
    fake_state.capability_registry.register_node(
        "iphone-1", node_type="phone", platform="ios",
        skills=[
            {
                "id": "phone_call",
                "name": "Phone Call",
                "description": "...",
                "actions": [
                    {"name": "phone.call.start", "summary": "...",
                     "requiresPermission": None}
                ],
            }
        ],
    )

    with patch("api.routes.capabilities.state", fake_state):
        from api.routes.capabilities import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/api/capabilities")
        assert resp.status_code == 200
        body = resp.json()
        assert body["primary_session_id"] == "primary-1"
        assert body["connected_node_count"] == 1
        # Brain-host: both manifest shapes present.
        brain_ids = {entry["id"] for entry in body["brain_host"]}
        assert brain_ids == {"read_file", "noop"}
        # Nodes: structure matches the registry snapshot shape.
        assert body["nodes"][0]["node_id"] == "iphone-1"
        assert body["nodes"][0]["surface"] == "phone_actuator"
        assert body["nodes"][0]["skills"][0]["actions"][0]["name"] == "phone.call.start"

        # Probe endpoint — present action → available.
        resp = client.get("/api/capabilities/has", params={"action": "phone.call.start"})
        assert resp.json()["available"] is True

        # Missing action → not available, no handler key.
        resp = client.get("/api/capabilities/has", params={"action": "phone.unknown.foo"})
        assert resp.json()["available"] is False

        # Node-type probe.
        resp = client.get("/api/capabilities/has", params={"node_type": "phone"})
        assert resp.json()["available"] is True
        resp = client.get("/api/capabilities/has", params={"node_type": "glasses"})
        assert resp.json()["available"] is False


@pytest.mark.asyncio
async def test_execute_capability_action_routes_to_registered_node(monkeypatch):
    from agents.tool_runner import ToolRunner

    reg = CapabilityRegistry()
    reg.register_node(
        "iphone-1", node_type="phone", platform="ios",
        skills=[{"actions": [{"name": "phone.call.start"}]}],
    )
    orch = _StubOrchestrator(reg)
    orch.daemons["iphone-1"] = object()  # presence-only stub
    runner = ToolRunner(orch)

    captured: dict = {}

    async def fake_execute_with_ack(
        session_id, node_id, action, args, timeout=30.0
    ):
        captured.update(dict(
            session_id=session_id, node_id=node_id,
            action=action, args=args, timeout=timeout,
        ))
        return {"success": True, "status_code": 200, "data": {"ok": True}}

    monkeypatch.setattr(runner, "execute_daemon_command_with_ack", fake_execute_with_ack)

    result = await runner.execute_capability_action(
        session_id="primary",
        action="phone.call.start",
        args={"number": "+15551234"},
    )
    assert result == {"success": True, "status_code": 200, "data": {"ok": True}}
    assert captured["node_id"] == "iphone-1"
    assert captured["action"] == "phone.call.start"
    assert captured["args"] == {"number": "+15551234"}
