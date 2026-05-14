"""Tests for cli/setup/network — the shared LAN / Tailscale core.

We mock the heavy ``integrations.tailscale`` surface so the tests don't
require a real Tailscale install. The persistence path is exercised
against a tmp ``~/.feral/settings.json`` (the autouse FERAL_HOME
isolation fixture redirects ``feral_home()`` for us).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from cli.setup import network


@dataclass
class _FakeStatus:
    installed: bool = False
    running: bool = False
    logged_in: bool = False
    dns_name: str = ""
    ipv4: str = ""
    ipv6: str = ""
    tailnet_name: str = ""
    error: str = ""


def _patch_tailscale(monkeypatch, *, status=None, funnel=None, enable=None,
                    enable_exc=None, disable_exc=None):
    """Build a fake ``integrations.tailscale`` module surface."""
    import integrations.tailscale as ts

    monkeypatch.setattr(ts, "status", lambda: status or _FakeStatus())
    if funnel is not None:
        monkeypatch.setattr(ts, "funnel_status", lambda: funnel)
    if enable is not None or enable_exc is not None:
        def _fake_enable(port, **kw):
            if enable_exc is not None:
                raise enable_exc
            return enable or {}
        monkeypatch.setattr(ts, "funnel_enable", _fake_enable)
    if disable_exc is not None:
        def _fake_disable(port):
            raise disable_exc
        monkeypatch.setattr(ts, "funnel_disable", _fake_disable)
    else:
        monkeypatch.setattr(ts, "funnel_disable", lambda port: {"enabled": False, "port": port})
    return ts


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_default_localhost_when_no_settings(self, monkeypatch):
        _patch_tailscale(monkeypatch)
        snap = await network.get_snapshot()
        assert snap.mode == "localhost"
        assert snap.bind_host == "127.0.0.1"
        assert snap.tailscale.installed is False

    @pytest.mark.asyncio
    async def test_lan_mode_inferred_from_persisted_bind(self, monkeypatch):
        _patch_tailscale(monkeypatch)
        # Pre-seed settings.
        from config.loader import feral_home

        settings_path = feral_home() / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"network": {"bind_host": "0.0.0.0"}}))
        snap = await network.get_snapshot()
        assert snap.mode == "lan"
        assert snap.bind_host == "0.0.0.0"

    @pytest.mark.asyncio
    async def test_remote_mode_inferred_from_pairing_setting(self, monkeypatch):
        _patch_tailscale(
            monkeypatch,
            status=_FakeStatus(installed=True, running=True, logged_in=True,
                               dns_name="brain.foo.ts.net"),
            funnel={"active": True, "ports": [9090]},
        )
        from config.loader import feral_home

        settings_path = feral_home() / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({
            "access": {
                "pairing_mode": "remote",
                "tailscale": {"tailnet_url": "https://brain.foo.ts.net"},
            }
        }))
        snap = await network.get_snapshot()
        assert snap.mode == "remote"
        assert snap.remote_url == "https://brain.foo.ts.net"
        assert snap.funnel_active is True


# ---------------------------------------------------------------------------
# apply_localhost / apply_lan
# ---------------------------------------------------------------------------


class TestApplyLocalhost:
    @pytest.mark.asyncio
    async def test_writes_loopback_bind(self, monkeypatch):
        _patch_tailscale(monkeypatch)
        snap = await network.apply_localhost()
        assert snap.bind_host == "127.0.0.1"
        assert snap.mode == "localhost"
        # Persisted on disk
        from config.loader import feral_home
        data = json.loads((feral_home() / "settings.json").read_text())
        assert data["network"]["bind_host"] == "127.0.0.1"
        assert data["access"]["pairing_mode"] == "localhost"


class TestApplyLan:
    @pytest.mark.asyncio
    async def test_writes_zero_bind_and_env(self, monkeypatch):
        _patch_tailscale(monkeypatch)
        snap = await network.apply_lan()
        assert snap.bind_host == "0.0.0.0"
        assert snap.mode == "lan"
        # Env exported so the in-process server picks it up immediately.
        import os
        assert os.environ.get("FERAL_BIND_HOST") == "0.0.0.0"

    @pytest.mark.asyncio
    async def test_rejects_empty_bind(self, monkeypatch):
        _patch_tailscale(monkeypatch)
        with pytest.raises(network.NetworkApplyError) as excinfo:
            await network.apply_lan(bind_host="")
        assert excinfo.value.code == "invalid_bind_host"


# ---------------------------------------------------------------------------
# apply_tailscale_funnel
# ---------------------------------------------------------------------------


class TestApplyTailscale:
    @pytest.mark.asyncio
    async def test_not_installed_raises_with_remediation(self, monkeypatch):
        _patch_tailscale(monkeypatch, status=_FakeStatus(installed=False))
        with pytest.raises(network.NetworkApplyError) as excinfo:
            await network.apply_tailscale_funnel()
        assert excinfo.value.code == "tailscale_not_installed"
        assert "brew install" in excinfo.value.remediation

    @pytest.mark.asyncio
    async def test_not_logged_in_raises(self, monkeypatch):
        _patch_tailscale(
            monkeypatch,
            status=_FakeStatus(installed=True, running=True, logged_in=False),
        )
        with pytest.raises(network.NetworkApplyError) as excinfo:
            await network.apply_tailscale_funnel()
        assert excinfo.value.code == "tailscale_not_logged_in"

    @pytest.mark.asyncio
    async def test_funnel_disabled_extracts_one_click_url(self, monkeypatch):
        import integrations.tailscale as ts
        msg = (
            "Funnel is not enabled in this tailnet. Enable here: "
            "https://login.tailscale.com/f/funnel?node=abc123 "
            "and retry."
        )
        _patch_tailscale(
            monkeypatch,
            status=_FakeStatus(installed=True, running=True, logged_in=True),
            enable_exc=ts.TailscaleFunnelDisabledInTailnet(msg),
        )
        with pytest.raises(network.NetworkApplyError) as excinfo:
            await network.apply_tailscale_funnel()
        assert excinfo.value.code == "funnel_disabled_in_tailnet"
        assert excinfo.value.remediation.startswith(
            "https://login.tailscale.com/f/funnel"
        )

    @pytest.mark.asyncio
    async def test_success_persists_url_and_returns_snapshot(self, monkeypatch):
        url = "https://brain.tail-cafe.ts.net"
        _patch_tailscale(
            monkeypatch,
            status=_FakeStatus(installed=True, running=True, logged_in=True,
                               dns_name="brain.tail-cafe.ts.net"),
            enable={"url": url, "port": 9090},
            funnel={"active": True, "ports": [9090]},
        )
        snap = await network.apply_tailscale_funnel()
        assert snap.mode == "remote"
        assert snap.remote_url == url

        from config.loader import feral_home
        data = json.loads((feral_home() / "settings.json").read_text())
        assert data["access"]["pairing_mode"] == "remote"
        assert data["access"]["tailscale"]["tailnet_url"] == url


# ---------------------------------------------------------------------------
# render_snapshot_lines — used by both `feral access status` and the wizard
# ---------------------------------------------------------------------------


class TestRenderSnapshot:
    def test_renders_localhost_default(self):
        snap = network.NetworkSnapshot()
        lines = network.render_snapshot_lines(snap)
        joined = "\n".join(lines)
        assert "Pairing mode: localhost" in joined
        assert "Bind host:    127.0.0.1" in joined
        assert "Tailscale:    NOT installed" in joined

    def test_renders_lan_url_when_detected(self):
        snap = network.NetworkSnapshot(
            mode="lan",
            bind_host="0.0.0.0",
            lan_ipv4="192.168.1.42",
        )
        joined = "\n".join(network.render_snapshot_lines(snap))
        assert "192.168.1.42" in joined
        assert "Bind host:    0.0.0.0" in joined
