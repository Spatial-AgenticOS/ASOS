"""Twin Settings honesty: only render rows the user has actually wired.

Pre-2026.4.29 the v2 ``Settings → Twin`` page rendered nine canned
domains regardless of whether any executor existed for them — the
toggles flipped state in SQLite but no real channel/integration
listened, so the UI was theatre.

These tests pin the new contract:

* ``GET /api/twin/policies`` returns an empty ``policies`` list when no
  executor is wired (no theatre).
* Wiring an executor + persisting a policy makes the row appear.
* Unwiring the executor moves the row to the ``disconnected`` bucket
  (the v2 picker dims it and disables the toggles) instead of letting
  the row keep pretending to do something.
* The ``available`` field exposes every wired executor so the
  frontend can render an "Available executors" discovery list.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.digital_twin import DigitalTwin
from agents.twin_policy import TwinPolicy, TwinPolicyEngine, TwinPolicyStore


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def twin_client(tmp_path):
    store = TwinPolicyStore(db_path=str(tmp_path / "twin.db"))
    engine = TwinPolicyEngine(store=store)
    twin = DigitalTwin(
        memory=MagicMock(),
        identity_loader=MagicMock(),
        llm=MagicMock(),
        policy_engine=engine,
    )

    mock = MagicMock()
    mock.twin_policy = engine
    mock.digital_twin = twin
    mock.supervisor = None

    with patch("api.state.state", mock), patch("api.routes.twin.state", mock):
        from api.server import app
        client = TestClient(app, raise_server_exceptions=False)
        yield client, twin, engine


async def _noop_executor(_context: dict) -> dict:
    return {"sent": True}


# ----------------------------------------------------------------------
# No executors wired → empty payload (no theatre)
# ----------------------------------------------------------------------


class TestEmptyStateWithoutExecutors:
    def test_policies_empty_when_no_executors_wired(self, twin_client):
        client, twin, engine = twin_client
        # Even with a stored policy, with zero executors wired the
        # active list must be empty — the row is "disconnected".
        engine.store.upsert_policy(TwinPolicy(domain="reply_slack", mode="auto_send"))

        r = client.get("/api/twin/policies")
        assert r.status_code == 200
        body = r.json()
        assert body["policies"] == []
        assert body["available"] == []
        # Existing-but-unwired policies should at least be discoverable
        # so the v2 UI can offer a "Reconnect" affordance.
        assert any(d["domain"] == "reply_slack" for d in body["disconnected"])

    def test_completely_clean_state(self, twin_client):
        client, _, _ = twin_client
        r = client.get("/api/twin/policies")
        body = r.json()
        assert body["policies"] == []
        assert body["disconnected"] == []
        assert body["available"] == []


# ----------------------------------------------------------------------
# Wiring an executor surfaces the row
# ----------------------------------------------------------------------


class TestWiringMakesRowAppear:
    def test_register_executor_then_upsert_policy(self, twin_client):
        client, twin, engine = twin_client
        twin.register_executor("reply_slack", _noop_executor, label="Slack")
        engine.store.upsert_policy(
            TwinPolicy(domain="reply_slack", mode="draft_only")
        )

        r = client.get("/api/twin/policies")
        body = r.json()
        domains = {p["domain"] for p in body["policies"]}
        assert "reply_slack" in domains
        row = next(p for p in body["policies"] if p["domain"] == "reply_slack")
        assert row["wired"] is True
        assert row["label"] == "Slack"
        # Even before any policy is set, the available list lets the
        # frontend offer "Set policy for Slack" as honest discovery.
        assert any(a["domain"] == "reply_slack" for a in body["available"])

    def test_executor_without_policy_only_in_available(self, twin_client):
        client, twin, _ = twin_client
        twin.register_executor("draft_email", _noop_executor, label="Email")

        r = client.get("/api/twin/policies")
        body = r.json()
        # No policy yet → the active list stays empty but the
        # executor shows up under "available" for discovery.
        assert body["policies"] == []
        avail = {a["domain"] for a in body["available"]}
        assert "draft_email" in avail


# ----------------------------------------------------------------------
# Unwiring an executor demotes the row to "disconnected"
# ----------------------------------------------------------------------


class TestDisconnectingMovesToDisconnected:
    def test_unregister_executor_demotes_row(self, twin_client):
        client, twin, engine = twin_client
        twin.register_executor("reply_slack", _noop_executor, label="Slack")
        engine.store.upsert_policy(
            TwinPolicy(domain="reply_slack", mode="auto_send")
        )

        r1 = client.get("/api/twin/policies").json()
        assert {p["domain"] for p in r1["policies"]} == {"reply_slack"}

        # Disconnect — picker should mark the row as disconnected
        # rather than keep it active and silently broken.
        twin.unregister_executor("reply_slack")

        r2 = client.get("/api/twin/policies").json()
        assert r2["policies"] == []
        disc_domains = {d["domain"] for d in r2["disconnected"]}
        assert "reply_slack" in disc_domains
        # And the available list no longer mentions it.
        avail = {a["domain"] for a in r2["available"]}
        assert "reply_slack" not in avail


# ----------------------------------------------------------------------
# DigitalTwin.execute() falls back to the registered executor
# ----------------------------------------------------------------------


class TestExecuteUsesRegisteredExecutor:
    @pytest.mark.asyncio
    async def test_execute_picks_registered_executor(self, twin_client):
        _client, twin, engine = twin_client
        called: dict = {}

        async def _record(ctx: dict) -> dict:
            called.update(ctx)
            return {"ok": True}

        twin.register_executor("reply_slack", _record, label="Slack")
        engine.store.upsert_policy(
            TwinPolicy(domain="reply_slack", mode="auto_send")
        )
        out = await twin.execute(
            "reply_slack", "send", {"text": "hi"}
        )
        assert out["status"] == "executed"
        assert called == {"text": "hi"}

    @pytest.mark.asyncio
    async def test_execute_queues_when_no_executor_registered(self, twin_client):
        _client, twin, engine = twin_client
        engine.store.upsert_policy(
            TwinPolicy(domain="reply_slack", mode="auto_send")
        )
        # No register_executor → must NOT silently no-op.
        out = await twin.execute("reply_slack", "send", {})
        assert out["status"] == "queued"
        assert out["reason"] == "auto_send_no_executor"
