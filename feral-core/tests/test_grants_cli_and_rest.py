"""PR2: Workspace folder grant lever — CLI + REST + persistence.

A successful Desktop write from ``computer_use__write_file`` follows
this end-to-end chain:

1. ``permission_request`` WS message reaches the client (already wired).
2. Operator clicks Allow → ``ui_handlers.handle_permission_response``
   calls ``SandboxPolicy.grant_folder``.
3. The grant is persisted to ``workspace_grants.json`` so the next
   ``can_write_path`` call succeeds.

The CLI (`feral grant`) and REST (`/api/security/grants`) are
operator-facing alternatives to step 2 — same persistence target.
These tests cover the persistence contract for both surfaces with the
grants file rooted in a tmp dir so the user's real ~/.feral isn't
touched.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from cli.grant_commands import cmd_grant
from security.sandbox_policy import SandboxPolicy


@pytest.fixture
def tmp_feral_home(tmp_path, monkeypatch):
    """Re-root ``feral_home`` for SandboxPolicy persistence so we never
    write into the user's real ~/.feral during tests."""
    home = tmp_path / "feral-home"
    home.mkdir()
    monkeypatch.setattr(
        "security.sandbox_policy.feral_home",
        lambda: home,
    )
    return home


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_cli_add_grant_persists_and_lists(tmp_feral_home, tmp_path, capsys) -> None:
    target = tmp_path / "Desktop"
    target.mkdir()

    rc = cmd_grant(_ns(action="add", path=str(target), mode="readwrite"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Granted readwrite access" in out

    # Persistence check: a fresh SandboxPolicy must see the grant.
    fresh = SandboxPolicy.load_default()
    assert fresh.can_write_path(str(target / "game.html")) is True


def test_cli_refuses_grant_for_missing_path(tmp_feral_home, tmp_path, capsys) -> None:
    rc = cmd_grant(_ns(action="add", path=str(tmp_path / "does-not-exist"), mode="readwrite"))
    assert rc == 1
    out = capsys.readouterr().out
    assert "does not exist" in out


def test_cli_revoke_removes_grant(tmp_feral_home, tmp_path) -> None:
    target = tmp_path / "Documents"
    target.mkdir()
    SandboxPolicy.load_default().grant_folder(str(target), mode="readwrite")
    assert SandboxPolicy.load_default().can_write_path(str(target / "x.txt")) is True

    rc = cmd_grant(_ns(action="revoke", path=str(target)))
    assert rc == 0
    assert SandboxPolicy.load_default().can_write_path(str(target / "x.txt")) is False


def test_cli_list_with_no_grants_prints_hint(tmp_feral_home, capsys) -> None:
    rc = cmd_grant(_ns(action="list"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "No workspace grants" in out
    assert "feral grant add" in out


@pytest.mark.asyncio
async def test_rest_grant_endpoint_persists(tmp_feral_home, tmp_path, monkeypatch) -> None:
    """The REST surface should write to the same grants file as the CLI."""
    # Avoid pulling brain state in the test.
    import api.routes.security_and_hardware as routes_mod

    class _FakeState:
        policy = None

    monkeypatch.setattr(routes_mod, "state", _FakeState())

    target = tmp_path / "Projects"
    target.mkdir()

    out = await routes_mod.grant_workspace_folder({"path": str(target), "mode": "readwrite"})
    assert out["ok"] is True
    assert out["mode"] == "readwrite"

    listing = await routes_mod.list_workspace_grants()
    paths = {g["path"] for g in listing["grants"]}
    assert str(target.resolve()) in paths

    # Fresh policy honours the persisted grant.
    fresh = SandboxPolicy.load_default()
    assert fresh.can_write_path(str(target / "site.html")) is True

    # Revoke via REST removes it.
    revoked = await routes_mod.revoke_workspace_folder(str(target))
    assert revoked["ok"] is True
    fresh_after = SandboxPolicy.load_default()
    assert fresh_after.can_write_path(str(target / "site.html")) is False


@pytest.mark.asyncio
async def test_rest_grant_rejects_invalid_mode(tmp_feral_home, monkeypatch, tmp_path) -> None:
    import api.routes.security_and_hardware as routes_mod

    class _FakeState:
        policy = None

    monkeypatch.setattr(routes_mod, "state", _FakeState())

    out = await routes_mod.grant_workspace_folder(
        {"path": str(tmp_path), "mode": "execute"},
    )
    assert out["ok"] is False
    assert "invalid mode" in out["error"]
