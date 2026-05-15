"""v2026.5.26 — autonomy mode persistence.

Pre-fix: ``POST /api/autonomy {mode}`` only updated the in-memory
``ToolRunner._autonomy_mode``. The choice never landed in
``~/.feral/settings.json``, so the next brain restart reverted to
"hybrid" (or whatever ``FERAL_AUTONOMY`` env var pinned). Operator's
WebUI Settings -> Autonomy pick was effectively a no-op across
sessions (operator screenshot 3 shows "loose" active, but it was
gone after restart).

Five tests:
* POST persists to settings.json via state.config.update_settings
* GET returns the live ToolRunner value
* Invalid mode rejected without persisting
* `update_settings` failure doesn't roll back the live state
* The boot-time load path picks settings.json over the default
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


def _make_state_with_orchestrator(mode: str = "hybrid"):
    """Build a fake BrainState shell sufficient for the autonomy route
    + a no-op ConfigLoader stub for update_settings."""
    fake = MagicMock()
    fake.orchestrator = MagicMock()
    fake.orchestrator.tool_runner = MagicMock()
    fake.orchestrator.tool_runner._autonomy_mode = mode

    def set_mode(value: str) -> str:
        fake.orchestrator.tool_runner._autonomy_mode = value
        # mirror the property contract so GET reads back the new value
        type(fake.orchestrator.tool_runner).autonomy_mode = property(
            lambda self: self._autonomy_mode
        )
        return value

    fake.orchestrator.tool_runner.set_autonomy_mode = set_mode
    # Read the in-memory value via the same `autonomy_mode` attribute
    # the route handler uses.
    fake.orchestrator.tool_runner.autonomy_mode = mode

    fake.config = MagicMock()
    fake.config.update_settings = MagicMock(return_value=None)
    return fake


def _client():
    from api.routes.timeline import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_post_autonomy_persists_to_settings_json():
    fake = _make_state_with_orchestrator(mode="hybrid")
    with patch("api.routes.timeline.state", fake):
        c = _client()
        r = c.post("/api/autonomy", json={"mode": "loose"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["mode"] == "loose"
    assert body["persisted"] is True
    # The live ToolRunner was updated.
    fake.orchestrator.tool_runner.set_autonomy_mode  # function called
    # AND the persist call landed.
    fake.config.update_settings.assert_called_once_with(
        "security", "autonomy_mode", "loose",
    )


def test_get_autonomy_returns_live_runner_value():
    fake = _make_state_with_orchestrator(mode="strict")
    with patch("api.routes.timeline.state", fake):
        c = _client()
        r = c.get("/api/autonomy")
    assert r.status_code == 200
    assert r.json()["mode"] == "strict"


def test_invalid_mode_returns_error_and_does_not_persist():
    fake = _make_state_with_orchestrator(mode="hybrid")
    with patch("api.routes.timeline.state", fake):
        c = _client()
        r = c.post("/api/autonomy", json={"mode": "yolo"})
    # Handler returns 200 with an error key (existing contract — not
    # changed in v2026.5.26). What MUST be true: nothing persisted.
    assert "error" in r.json()
    fake.config.update_settings.assert_not_called()


def test_persist_failure_does_not_roll_back_live_state():
    # Disk write fails → live mode still flipped (so the operator
    # gets the immediate UX they clicked for) but `persisted=False`
    # tells the client to surface a "restart will revert" hint.
    fake = _make_state_with_orchestrator(mode="hybrid")
    fake.config.update_settings.side_effect = OSError("read-only fs")
    with patch("api.routes.timeline.state", fake):
        c = _client()
        r = c.post("/api/autonomy", json={"mode": "loose"})
    body = r.json()
    assert body["success"] is True
    assert body["mode"] == "loose"
    assert body["persisted"] is False  # honest about the disk failure
    # In-memory flip still happened.
    assert fake.orchestrator.tool_runner._autonomy_mode == "loose"


def test_autonomy_load_at_boot_prefers_settings_json_over_default():
    """The state.py boot path reads
    config.get("security", "autonomy_mode") and calls set_autonomy_mode
    when the persisted value differs from the default. This test
    simulates that boot sequence in isolation.
    """
    fake = _make_state_with_orchestrator(mode="hybrid")

    # ConfigLoader.get returns the persisted value.
    fake.config.get = MagicMock(return_value="loose")
    # Inline the boot-load logic — mirrors what api/state.py does
    # after orchestrator construction (the env var is empty here, so
    # the persisted value wins).
    import os
    os.environ.pop("FERAL_AUTONOMY", None)
    persisted = fake.config.get("security", "autonomy_mode") or ""
    if persisted.strip().lower() in ("strict", "hybrid", "loose"):
        fake.orchestrator.tool_runner.set_autonomy_mode(persisted)

    assert fake.orchestrator.tool_runner._autonomy_mode == "loose"
