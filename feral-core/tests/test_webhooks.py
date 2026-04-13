"""
Tests for EventBus, WebhookReceiver, and FastAPI webhook routes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.server import app
from integrations.webhook_receiver import EventBus, WebhookEvent, WebhookReceiver, WebhookConfig

pytestmark = pytest.mark.no_auto_feral_home


# ── EventBus (subscribe via `on` / publish via `emit`) ──────────────────────


@pytest.mark.asyncio
async def test_event_bus_on_and_emit_delivers_to_handler():
    bus = EventBus()
    seen: list[WebhookEvent] = []

    async def h(ev: WebhookEvent):
        seen.append(ev)

    bus.on("my_app", h)
    ev = WebhookEvent(app_id="my_app", event_type="ping", payload={"x": 1})
    await bus.emit(ev)
    assert len(seen) == 1
    assert seen[0].app_id == "my_app"
    assert seen[0].payload["x"] == 1


@pytest.mark.asyncio
async def test_event_bus_on_all_receives_every_emit():
    bus = EventBus()
    global_hits: list[str] = []
    specific_hits: list[str] = []

    async def global_h(ev: WebhookEvent):
        global_hits.append(ev.app_id)

    async def specific_h(ev: WebhookEvent):
        specific_hits.append(ev.event_type)

    bus.on_all(global_h)
    bus.on("app_a", specific_h)
    await bus.emit(WebhookEvent(app_id="app_a", event_type="t1", payload={}))
    await bus.emit(WebhookEvent(app_id="other", event_type="t2", payload={}))
    assert global_hits == ["app_a", "other"]
    assert specific_hits == ["t1"]


@pytest.mark.asyncio
async def test_event_bus_emit_logs_and_recent_events_and_stats():
    bus = EventBus()
    bus.on("z", AsyncMock())
    await bus.emit(WebhookEvent(app_id="z", event_type="e", payload={"k": 2}))
    recent = bus.recent_events(5)
    assert recent[-1]["app_id"] == "z"
    assert recent[-1]["event_type"] == "e"
    st = bus.stats()
    assert "z" in st["registered_apps"]
    assert st["total_events"] == 1
    assert st["global_handlers"] == 0


@pytest.mark.asyncio
async def test_event_bus_handler_exception_does_not_block_following_handlers():
    bus = EventBus()

    async def bad(_ev: WebhookEvent):
        raise RuntimeError("boom")

    ok_calls = []

    async def good(ev: WebhookEvent):
        ok_calls.append(ev.event_type)

    bus.on("multi", bad)
    bus.on("multi", good)
    await bus.emit(WebhookEvent(app_id="multi", event_type="x", payload={}))
    assert ok_calls == ["x"]


@pytest.mark.asyncio
async def test_event_bus_global_handler_runs_alongside_app_handlers():
    bus = EventBus()
    seq: list[str] = []

    async def g1(ev: WebhookEvent):
        seq.append("g")

    async def a1(ev: WebhookEvent):
        seq.append("a")

    bus.on_all(g1)
    bus.on("app", a1)
    await bus.emit(WebhookEvent(app_id="app", event_type="t", payload={}))
    assert seq == ["a", "g"]


# ── WebhookReceiver ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_receiver_unknown_app_rejected():
    bus = EventBus()
    recv = WebhookReceiver(bus)
    out = await recv.handle_request(
        "not_registered_xyz",
        b"{}",
        {},
        "application/json",
    )
    assert out["accepted"] is False
    assert "error" in out


@pytest.mark.asyncio
async def test_webhook_receiver_github_hmac_verified_when_secret_matches():
    bus = EventBus()
    recv = WebhookReceiver(bus)
    recv.set_secret("github", "mysecret")
    body = b'{"action":"opened"}'
    sig = hmac.new(b"mysecret", body, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature-256": f"sha256={sig}",
        "X-GitHub-Event": "pull_request",
    }
    captured: list[WebhookEvent] = []

    async def cap(ev: WebhookEvent):
        captured.append(ev)

    bus.on("github", cap)
    out = await recv.handle_request("github", body, headers, "application/json")
    assert out["accepted"] is True
    assert out["verified"] is True
    assert out["event_type"] == "pull_request"
    assert captured and captured[0].verified is True


@pytest.mark.asyncio
async def test_webhook_receiver_github_bad_signature_marks_unverified():
    bus = EventBus()
    recv = WebhookReceiver(bus)
    recv.set_secret("github", "mysecret")
    body = b"{}"
    headers = {"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "push"}
    out = await recv.handle_request("github", body, headers, "application/json")
    assert out["accepted"] is True
    assert out["verified"] is False


@pytest.mark.asyncio
async def test_webhook_receiver_stripe_event_type_from_payload():
    bus = EventBus()
    recv = WebhookReceiver(bus)
    body_dict = {"type": "invoice.paid", "data": {"object": {"id": "in_1"}}}
    body = json.dumps(body_dict).encode()
    out = await recv.handle_request("stripe", body, {}, "application/json")
    assert out["accepted"] is True
    assert out["event_type"] == "invoice.paid"


@pytest.mark.asyncio
async def test_webhook_receiver_home_assistant_event_type_resolution():
    bus = EventBus()
    recv = WebhookReceiver(bus)
    body = json.dumps({"event_type": "automation_triggered"}).encode()
    out = await recv.handle_request("home_assistant", body, {}, "application/json")
    assert out["accepted"] is True
    assert out["event_type"] == "automation_triggered"


# ── HTTP routes (verification against patched state) ──────────────────────


def test_receive_webhook_route_delegates_to_receiver():
    bus = EventBus()
    recv = WebhookReceiver(bus)

    async def track(ev: WebhookEvent):
        pass

    bus.on("notion", track)

    with patch("api.routes.integrations_webhooks.state") as st:
        st.webhook_receiver = recv
        st.event_bus = bus
        client = TestClient(app)
        r = client.post("/api/webhooks/notion", json={"type": "page_updated", "id": "p1"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("accepted") is True
    assert data.get("event_type") == "page_updated"


def test_list_webhooks_route_returns_configs_and_recent_events():
    bus = EventBus()
    recv = WebhookReceiver(bus)

    async def dummy(_ev: WebhookEvent):
        return None

    bus.on("github", dummy)

    with patch("api.routes.integrations_webhooks.state") as st:
        st.webhook_receiver = recv
        st.event_bus = bus
        client = TestClient(app)
        r = client.get("/api/webhooks")
    assert r.status_code == 200
    payload = r.json()
    assert "webhooks" in payload
    assert isinstance(payload["webhooks"], list)
    assert "events" in payload


def test_receive_webhook_route_when_receiver_missing():
    with patch("api.routes.integrations_webhooks.state") as st:
        st.webhook_receiver = None
        st.event_bus = None
        client = TestClient(app)
        r = client.post("/api/webhooks/github", json={})
    assert r.status_code == 200
    assert "error" in r.json()


def test_webhook_receiver_register_webhook_custom_app():
    bus = EventBus()
    recv = WebhookReceiver(bus)
    recv.register_webhook(WebhookConfig(app_id="custom", enabled=True))
    out = recv.list_webhooks()
    ids = {x["app_id"] for x in out}
    assert "custom" in ids
