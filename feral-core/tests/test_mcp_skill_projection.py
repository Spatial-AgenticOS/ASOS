"""
PR 11: external MCP clients can now see and call a *safe subset* of
FERAL skills, but only when (a) the manifest-aware resolver verdicts
AUTO and (b) the tool isn't on the ``mcp`` surface deny list.

The matrix locked in below:

* Without ``skill_registry`` / ``skill_executor``, the projection
  silently does nothing (default opt-out).
* A read-only endpoint (substring or manifest hint) shows up as
  ``feral_skill_<skill>__<endpoint>`` in ``tools/list``.
* ``computer_use__bash`` is denied on the MCP surface even when the
  registry has it.
* CONFIRM tools (e.g. manifest ``safety_tier="confirm"``) do not
  appear — external MCP clients cannot satisfy a CONFIRM gate.
* ``tools/call`` to a projected skill dispatches through the executor
  with the right args; a CONFIRM-tier manifest refuses at call time
  even if the cached ``tools/list`` had no entry.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from models.skill_manifest import (  # noqa: E402
    AuthConfig, BrandProfile, EndpointParam, SkillEndpoint, SkillManifest,
)


def _make_skill(skill_id: str, endpoint_overrides: dict | None = None) -> SkillManifest:
    return SkillManifest(
        skill_id=skill_id,
        version="1.0.0",
        author="test",
        brand=BrandProfile(name=skill_id),
        description="fixture",
        auth=AuthConfig(type="none"),
        endpoints=[
            SkillEndpoint(
                id="search",
                method="PYTHON",
                url="",
                description="search the fixture",
                params=[
                    EndpointParam(name="q", type="string", required=True),
                ],
                **(endpoint_overrides or {}),
            ),
        ],
    )


class _FakeRegistry:
    def __init__(self, manifests: list[SkillManifest]):
        self.skills = {m.skill_id: m for m in manifests}


class _FakeExecutor:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, name, args, skill, endpoint):
        self.calls.append((name, dict(args)))
        return {"success": True, "data": {"name": name, "args": args}, "error": None}


# ── tools/list projection ──────────────────────────────────────────────


def test_projection_disabled_when_no_skill_registry():
    from mcp.server import FeralMCPServer

    server = FeralMCPServer()
    tools = server.handle_tools_list()["tools"]
    assert not any(t["name"].startswith("feral_skill_") for t in tools)


def test_projection_exposes_auto_read_only_endpoints():
    from mcp.server import FeralMCPServer

    skill = _make_skill("notes_memory")  # substring "search" -> AUTO via legacy
    server = FeralMCPServer(
        skill_registry=_FakeRegistry([skill]),
        skill_executor=_FakeExecutor(),
    )
    server.configure_skill_projection(enabled=True)
    tools = server.handle_tools_list()["tools"]
    names = {t["name"] for t in tools}
    assert "feral_skill_notes_memory__search" in names

    projected = next(t for t in tools if t["name"] == "feral_skill_notes_memory__search")
    schema = projected["inputSchema"]
    assert schema["type"] == "object"
    assert "q" in schema["properties"]
    assert "q" in schema["required"]


def test_projection_skips_confirm_manifest():
    from mcp.server import FeralMCPServer

    confirm_skill = _make_skill("safe_search", {"safety_tier": "confirm"})
    server = FeralMCPServer(
        skill_registry=_FakeRegistry([confirm_skill]),
        skill_executor=_FakeExecutor(),
    )
    server.configure_skill_projection(enabled=True)
    tools = server.handle_tools_list()["tools"]
    assert not any(t["name"] == "feral_skill_safe_search__search" for t in tools)


def test_projection_skips_mcp_surface_denied_tools():
    """`computer_use__bash` is on the MCP deny list and must NOT be
    projected even if the manifest somehow declares it safe."""
    from mcp.server import FeralMCPServer

    cu = _make_skill("computer_use", {"safety_tier": "safe"})
    cu.endpoints[0].id = "bash"  # type: ignore[attr-defined]
    server = FeralMCPServer(
        skill_registry=_FakeRegistry([cu]),
        skill_executor=_FakeExecutor(),
    )
    server.configure_skill_projection(enabled=True)
    tools = server.handle_tools_list()["tools"]
    assert not any(t["name"] == "feral_skill_computer_use__bash" for t in tools)


# ── tools/call dispatch ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_projected_call_dispatches_to_executor():
    from mcp.server import FeralMCPServer

    skill = _make_skill("notes_memory")
    executor = _FakeExecutor()
    server = FeralMCPServer(
        skill_registry=_FakeRegistry([skill]),
        skill_executor=executor,
    )
    server.configure_skill_projection(enabled=True)
    result = await server.handle_tools_call(
        "feral_skill_notes_memory__search",
        {"q": "hello"},
    )
    assert result.get("isError") is not True
    assert executor.calls == [("notes_memory__search", {"q": "hello"})]
    body = result["content"][0]["text"]
    assert json.loads(body)["success"] is True


@pytest.mark.asyncio
async def test_projected_call_refuses_confirm_at_call_time():
    """Even if a cached `tools/list` previously held the entry, a
    manifest update that bumps the tier to CONFIRM must take effect
    on the very next call."""
    from mcp.server import FeralMCPServer

    confirm_skill = _make_skill("safe_search", {"safety_tier": "confirm"})
    server = FeralMCPServer(
        skill_registry=_FakeRegistry([confirm_skill]),
        skill_executor=_FakeExecutor(),
    )
    server.configure_skill_projection(enabled=True)
    result = await server.handle_tools_call(
        "feral_skill_safe_search__search",
        {"q": "x"},
    )
    assert result.get("isError") is True
    assert "requires confirm" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_projected_call_refuses_mcp_denied_tool():
    from mcp.server import FeralMCPServer

    cu = _make_skill("computer_use", {"safety_tier": "safe"})
    cu.endpoints[0].id = "bash"  # type: ignore[attr-defined]
    server = FeralMCPServer(
        skill_registry=_FakeRegistry([cu]),
        skill_executor=_FakeExecutor(),
    )
    server.configure_skill_projection(enabled=True)
    result = await server.handle_tools_call(
        "feral_skill_computer_use__bash",
        {"command": "rm -rf /"},
    )
    assert result.get("isError") is True
    assert "denied" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_projected_call_unknown_endpoint_returns_error():
    from mcp.server import FeralMCPServer

    server = FeralMCPServer(
        skill_registry=_FakeRegistry([_make_skill("notes_memory")]),
        skill_executor=_FakeExecutor(),
    )
    server.configure_skill_projection(enabled=True)
    result = await server.handle_tools_call(
        "feral_skill_notes_memory__no_such_endpoint",
        {"q": "x"},
    )
    assert result.get("isError") is True


_ = asyncio
