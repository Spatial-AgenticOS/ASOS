"""PR 11 gap-fill: MCP skill projection is OFF by default and must be
operator-toggled at runtime (env var at boot or REST POST at runtime).

Locks:
* Default constructor leaves projection disabled — booting the brain
  with no opt-in does NOT silently expose skills.
* ``configure_skill_projection(enabled=True)`` flips the flag and
  ``projection_status`` reflects the truth.
* ``handle_tools_call`` refuses projected calls with a clear message
  when projection is disabled.
* REST `GET /api/mcp/projection` and `POST /api/mcp/projection`
  expose the toggle via the BrainState wiring.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from mcp.server import FeralMCPServer  # noqa: E402
from models.skill_manifest import (  # noqa: E402
    AuthConfig, BrandProfile, EndpointParam, SkillEndpoint, SkillManifest,
)


def _make_skill(skill_id):
    return SkillManifest(
        skill_id=skill_id, version="1.0.0", author="t",
        brand=BrandProfile(name=skill_id), description="x",
        auth=AuthConfig(type="none"),
        endpoints=[
            SkillEndpoint(
                id="search", method="PYTHON", url="",
                description="d", params=[EndpointParam(name="q", type="string", required=True)],
            ),
        ],
    )


class _Reg:
    def __init__(self, m):
        self.skills = {m.skill_id: m}


class _Exec:
    async def execute(self, *a, **kw):
        return {"success": True, "data": {}}


def test_projection_disabled_by_default_with_full_wiring():
    server = FeralMCPServer(skill_registry=_Reg(_make_skill("notes")), skill_executor=_Exec())
    status = server.projection_status()
    assert status["enabled"] is False
    assert status["ready"] is False
    assert status["registry_wired"] is True
    assert status["executor_wired"] is True
    tools = server.handle_tools_list()["tools"]
    assert not any(t["name"].startswith("feral_skill_") for t in tools)


def test_configure_skill_projection_flips_flag_and_reports_status():
    server = FeralMCPServer(skill_registry=_Reg(_make_skill("notes")), skill_executor=_Exec())
    out = server.configure_skill_projection(enabled=True)
    assert out["enabled"] is True
    assert out["ready"] is True
    assert out["projected_count"] >= 1
    tools = server.handle_tools_list()["tools"]
    assert any(t["name"] == "feral_skill_notes__search" for t in tools)


@pytest.mark.asyncio
async def test_call_refuses_when_projection_disabled():
    server = FeralMCPServer(skill_registry=_Reg(_make_skill("notes")), skill_executor=_Exec())
    result = await server.handle_tools_call("feral_skill_notes__search", {"q": "hi"})
    assert result.get("isError") is True
    assert "disabled" in result["content"][0]["text"].lower()


def test_rest_projection_status_and_toggle_round_trip():
    server = FeralMCPServer(skill_registry=_Reg(_make_skill("notes")), skill_executor=_Exec())

    class _State:
        mcp_server = server
        mcp_client = None
        skill_registry = _Reg(_make_skill("notes"))
        skill_executor = _Exec()

    from api.routes import mcp as mcp_routes
    with patch.object(mcp_routes, "state", _State()):
        app = FastAPI()
        app.include_router(mcp_routes.router)
        client = TestClient(app, raise_server_exceptions=False)

        # initial status: disabled
        before = client.get("/api/mcp/projection").json()
        assert before["enabled"] is False

        # enable via REST
        after = client.post("/api/mcp/projection", json={"enabled": True}).json()
        assert after["enabled"] is True
        assert after["ready"] is True

        # status reflects it
        followup = client.get("/api/mcp/projection").json()
        assert followup["enabled"] is True

        # disable
        off = client.post("/api/mcp/projection", json={"enabled": False}).json()
        assert off["enabled"] is False
