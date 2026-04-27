"""
A2 — self_introspection skill must surface the real skill registry, device
registry, and mitosis engine (not silently empty lists caused by the old
``state.skills`` / ``state.node_registry`` / ``state.mitosis_engine``
AttributeError swallow paths).
"""
from __future__ import annotations

from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest

from skills.impl.self_introspection import SelfIntrospectionSkill


class _FakeEndpoint:
    def __init__(self, eid: str):
        self.id = eid
        self.description = f"desc-{eid}"
        self.params = []


class _FakeSkill:
    def __init__(self, skill_id: str, endpoints: list[str]):
        self.skill_id = skill_id
        self.description = f"desc of {skill_id}"
        self.brand = SimpleNamespace(name=skill_id.replace("_", " ").title())
        self.endpoints = [_FakeEndpoint(e) for e in endpoints]


class _FakeRegistry:
    def __init__(self, skills: dict):
        self.skills = skills


class _FakeDeviceRegistry:
    """Mirrors hardware/protocol.py::DeviceRegistry surface used by the skill."""

    def __init__(self, devices: list[dict]):
        self._devices = devices

    def list_devices(self):
        return [
            SimpleNamespace(
                device_id=d["device_id"],
                device_type=d.get("device_type", "unknown"),
                name=d.get("name", ""),
                capabilities=[SimpleNamespace(category=c) for c in d.get("capabilities", [])],
                last_seen=d.get("last_seen"),
            )
            for d in self._devices
        ]


def _state_with(skill_registry, device_registry=None, agent_mitosis=None, channel_manager=None):
    """Build a BrainState-like object. Tests patch the module-level ``state``
    lookup used by ``SelfIntrospectionSkill._state``."""
    s = SimpleNamespace(
        skill_registry=skill_registry,
        device_registry=device_registry,
        agent_mitosis=agent_mitosis,
        channel_manager=channel_manager,
        config=None,
    )
    return s


@pytest.mark.asyncio
async def test_list_capabilities_returns_real_skills(monkeypatch):
    """The regression: ``state.skills.skills`` used to AttributeError and
    this skill returned ``{"skills": [], "success": True}``. Now it must
    surface exactly the registered skills."""
    registry = _FakeRegistry({
        "web_search": _FakeSkill("web_search", ["query"]),
        "desktop_control": _FakeSkill("desktop_control", ["open_app", "shell_command"]),
    })
    fake_state = _state_with(registry)

    monkeypatch.setattr(SelfIntrospectionSkill, "_state", staticmethod(lambda: fake_state))
    skill = SelfIntrospectionSkill()

    result = await skill.execute("list_capabilities", {}, {})
    assert result["success"] is True
    data = result["data"]
    ids = {s["skill_id"] for s in data["skills"]}
    assert ids == {"web_search", "desktop_control"}
    dc = next(s for s in data["skills"] if s["skill_id"] == "desktop_control")
    endpoint_ids = {e["id"] for e in dc["endpoints"]}
    assert {"open_app", "shell_command"}.issubset(endpoint_ids)


@pytest.mark.asyncio
async def test_list_capabilities_reads_device_registry(monkeypatch):
    registry = _FakeRegistry({"web_search": _FakeSkill("web_search", ["query"])})
    devices = _FakeDeviceRegistry([
        {"device_id": "node-1", "device_type": "glasses", "capabilities": ["vision", "audio"]},
        {"device_id": "node-2", "device_type": "wristband", "capabilities": ["hr"]},
    ])
    fake_state = _state_with(registry, device_registry=devices)
    monkeypatch.setattr(SelfIntrospectionSkill, "_state", staticmethod(lambda: fake_state))

    skill = SelfIntrospectionSkill()
    result = await skill.execute("list_capabilities", {}, {})
    ids = {d["node_id"] for d in result["data"]["connected_devices"]}
    assert ids == {"node-1", "node-2"}
    node1 = next(d for d in result["data"]["connected_devices"] if d["node_id"] == "node-1")
    assert node1["type"] == "glasses"
    assert "vision" in node1["capabilities"]


@pytest.mark.asyncio
async def test_describe_skill_uses_skill_registry(monkeypatch):
    registry = _FakeRegistry({
        "desktop_control": _FakeSkill("desktop_control", ["open_app"]),
    })
    fake_state = _state_with(registry)
    monkeypatch.setattr(SelfIntrospectionSkill, "_state", staticmethod(lambda: fake_state))

    skill = SelfIntrospectionSkill()
    ok = await skill.execute("describe_skill", {"skill_id": "desktop_control"}, {})
    assert ok["success"] is True
    assert ok["data"]["skill_id"] == "desktop_control"

    missing = await skill.execute("describe_skill", {"skill_id": "no_such"}, {})
    assert missing["success"] is False
    assert missing["status_code"] == 404


@pytest.mark.asyncio
async def test_list_specialists_reads_agent_mitosis(monkeypatch):
    registry = _FakeRegistry({})
    mitosis = MagicMock()
    mitosis.list_specialists.return_value = [
        SimpleNamespace(id="sp1", domain="code", allowed_skills=["web_search"], confidence=0.8),
    ]
    fake_state = _state_with(registry, agent_mitosis=mitosis)
    monkeypatch.setattr(SelfIntrospectionSkill, "_state", staticmethod(lambda: fake_state))

    skill = SelfIntrospectionSkill()
    result = await skill.execute("list_specialists", {}, {})
    assert result["success"] is True
    assert result["data"]["specialists"][0]["id"] == "sp1"
