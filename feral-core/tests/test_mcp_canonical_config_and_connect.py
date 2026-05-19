"""Tests for audit-r12 D7: canonical ``MCPServerConfig`` + missing
per-server connect/disconnect API.

Before D7, ``MCPServerRegistry.connect_server`` called
``self._mcp_client.connect(server_id=..., command=..., args=...,
env=...)`` — a method that didn't exist on
:class:`mcp.client.MCPClientManager`. Both the registry and the
``POST /api/mcp/connect`` route silently fell into ``AttributeError``
(swallowed by a ``try/except`` that returned ``{error: ...}`` with no
diagnostic) or by-passed the manager's degrade/retry bookkeeping
entirely.

This suite pins the contract so that bug class can't come back.
"""

from __future__ import annotations

import sys
import inspect
from pathlib import Path
from typing import Any

import pytest

_FERAL_CORE = Path(__file__).resolve().parent.parent
if str(_FERAL_CORE) not in sys.path:
    sys.path.insert(0, str(_FERAL_CORE))

from mcp.client import (  # noqa: E402
    MCPClientManager,
    MCPServerConfig,
    MCPServerConnection,
)
from mcp.registry import MCPServerRegistry  # noqa: E402


# ─────────────────────────────────────────────
# Static API contract — the methods the registry calls MUST exist
# with the right signature. Test fails at collection if not.
# ─────────────────────────────────────────────


def test_client_manager_exposes_canonical_connect_disconnect_api():
    # The registry calls these; if they vanish, every "Connect server"
    # UI action in /api/mcp/registry would silently 500. This pins the
    # contract.
    assert hasattr(MCPClientManager, "connect_server"), \
        "MCPClientManager must expose connect_server(config)"
    assert hasattr(MCPClientManager, "disconnect_server"), \
        "MCPClientManager must expose disconnect_server(name)"
    sig_connect = inspect.signature(MCPClientManager.connect_server)
    assert "config" in sig_connect.parameters
    sig_disconnect = inspect.signature(MCPClientManager.disconnect_server)
    assert "name" in sig_disconnect.parameters


def test_legacy_aliases_still_present_for_back_compat():
    # The old (broken) registry code path used .connect()/.disconnect().
    # Keeping the shape alive as aliases means in-flight third-party
    # forks don't regress until they migrate.
    assert hasattr(MCPClientManager, "connect")
    assert hasattr(MCPClientManager, "disconnect")


# ─────────────────────────────────────────────
# Canonical config validation
# ─────────────────────────────────────────────


def test_mcp_server_config_minimal_valid():
    cfg = MCPServerConfig(name="github")
    assert cfg.name == "github"
    assert cfg.transport == "stdio"
    assert cfg.command == ""
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.enabled is True


def test_mcp_server_config_round_trips_to_connection_kwargs():
    cfg = MCPServerConfig(
        name="github",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PAT": "ghp_x"},
        transport="stdio",
    )
    out = cfg.to_connection_kwargs()
    assert out == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PAT": "ghp_x"},
        "enabled": True,
    }


def test_mcp_server_config_rejects_missing_name():
    with pytest.raises(Exception):
        MCPServerConfig()  # type: ignore[call-arg]


def test_connection_accepts_canonical_model():
    cfg = MCPServerConfig(name="demo", command="echo", args=["hi"])
    conn = MCPServerConnection("demo", cfg)
    assert conn.name == "demo"
    assert conn.transport == "stdio"
    assert conn.config["command"] == "echo"
    assert conn.config["args"] == ["hi"]


def test_connection_accepts_legacy_dict_for_backcompat():
    # Existing ``mcp_servers.json`` files (and the existing
    # test_mcp_client_resilience suite) pass a dict; this MUST keep
    # working unchanged.
    conn = MCPServerConnection("demo", {"transport": "stdio", "command": "echo"})
    assert conn.name == "demo"
    assert conn.transport == "stdio"


# ─────────────────────────────────────────────
# Manager.connect_server + disconnect_server actually do their job
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_server_idempotent_on_name(monkeypatch):
    # Two calls with the same name MUST replace the connection rather
    # than leak (the spec says config changes — e.g. new env vars —
    # must take effect on the second call).
    mgr = MCPClientManager(config_path="/tmp/d7-unused.json")

    connect_calls = 0
    disconnect_calls = 0

    async def fake_connect(self):  # noqa: ANN001
        nonlocal connect_calls
        connect_calls += 1
        self._connected = True
        return True

    async def fake_disconnect(self):  # noqa: ANN001
        nonlocal disconnect_calls
        disconnect_calls += 1
        self._connected = False

    monkeypatch.setattr(MCPServerConnection, "connect", fake_connect)
    monkeypatch.setattr(MCPServerConnection, "disconnect", fake_disconnect)
    # We don't need retries here; one shot.
    mgr._connect_max_attempts = 1

    cfg = MCPServerConfig(name="demo", command="true")
    ok1 = await mgr.connect_server(cfg)
    ok2 = await mgr.connect_server(cfg)
    assert ok1 and ok2
    assert connect_calls == 2
    assert disconnect_calls == 1
    assert "demo" in mgr._servers


@pytest.mark.asyncio
async def test_disconnect_server_returns_false_for_unknown(monkeypatch):
    mgr = MCPClientManager(config_path="/tmp/d7-unused.json")
    out = await mgr.disconnect_server("never-connected")
    assert out is False


@pytest.mark.asyncio
async def test_disconnect_server_returns_true_when_active(monkeypatch):
    mgr = MCPClientManager(config_path="/tmp/d7-unused.json")

    async def fake_connect(self):  # noqa: ANN001
        self._connected = True
        return True

    async def fake_disconnect(self):  # noqa: ANN001
        self._connected = False

    monkeypatch.setattr(MCPServerConnection, "connect", fake_connect)
    monkeypatch.setattr(MCPServerConnection, "disconnect", fake_disconnect)
    mgr._connect_max_attempts = 1

    cfg = MCPServerConfig(name="demo", command="true")
    assert await mgr.connect_server(cfg) is True
    assert "demo" in mgr._servers
    out = await mgr.disconnect_server("demo")
    assert out is True
    assert "demo" not in mgr._servers


@pytest.mark.asyncio
async def test_legacy_connect_kwargs_alias_still_works(monkeypatch):
    # Back-compat: MCPServerRegistry pre-r12 called
    # manager.connect(server_id=, command=, args=, env=). That shape
    # should still work via the legacy alias so any old fork doesn't
    # break on upgrade.
    mgr = MCPClientManager(config_path="/tmp/d7-unused.json")

    async def fake_connect(self):  # noqa: ANN001
        self._connected = True
        return True

    monkeypatch.setattr(MCPServerConnection, "connect", fake_connect)
    mgr._connect_max_attempts = 1

    ok = await mgr.connect(server_id="demo", command="true", args=[], env={})
    assert ok is True
    assert "demo" in mgr._servers


@pytest.mark.asyncio
async def test_legacy_connect_alias_requires_name():
    mgr = MCPClientManager(config_path="/tmp/d7-unused.json")
    with pytest.raises(TypeError, match="server_id"):
        await mgr.connect(command="true")  # type: ignore[misc]


# ─────────────────────────────────────────────
# Registry routes through the manager via the canonical model
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_connect_server_routes_through_canonical_api(monkeypatch):
    captured: dict[str, Any] = {}

    class _StubManager:
        async def connect_server(self, config):  # noqa: ANN001
            captured["config"] = config
            return True

        async def disconnect_server(self, name):  # noqa: ANN001
            captured["disconnected"] = name
            return True

    reg = MCPServerRegistry(mcp_client=_StubManager())
    out = await reg.connect_server("github")
    assert out == {"ok": True, "server": "github"}
    cfg = captured["config"]
    assert isinstance(cfg, MCPServerConfig)
    assert cfg.name == "github"
    # The KNOWN_SERVERS entry for github uses npx — the registry MUST
    # carry that into the config (this was the silent shape mismatch).
    assert cfg.command == "npx"
    assert cfg.args[:2] == ["-y", "@modelcontextprotocol/server-github"]


@pytest.mark.asyncio
async def test_registry_connect_server_reports_failed_connect():
    class _StubManager:
        async def connect_server(self, config):  # noqa: ANN001
            return False

    reg = MCPServerRegistry(mcp_client=_StubManager())
    out = await reg.connect_server("github")
    assert "error" in out
    assert "github" in out["error"]


@pytest.mark.asyncio
async def test_registry_connect_server_unknown_id_returns_error():
    reg = MCPServerRegistry(mcp_client=object())  # any non-None client
    out = await reg.connect_server("not-in-catalog")
    assert "error" in out
    assert "not-in-catalog" in out["error"]


@pytest.mark.asyncio
async def test_registry_disconnect_server_routes_through_manager():
    captured: dict[str, Any] = {}

    class _StubManager:
        async def disconnect_server(self, name):  # noqa: ANN001
            captured["name"] = name
            return True

    reg = MCPServerRegistry(mcp_client=_StubManager())
    out = await reg.disconnect_server("github")
    assert out == {"ok": True, "server": "github"}
    assert captured["name"] == "github"


@pytest.mark.asyncio
async def test_registry_disconnect_server_unknown_returns_error():
    class _StubManager:
        async def disconnect_server(self, name):  # noqa: ANN001
            return False

    reg = MCPServerRegistry(mcp_client=_StubManager())
    out = await reg.disconnect_server("github")
    assert "error" in out
    assert "not connected" in out["error"]
