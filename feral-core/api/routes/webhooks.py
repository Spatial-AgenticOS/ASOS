"""Webhook management API — create, list, delete webhooks, receive events."""
import hashlib
import hmac
import json
import logging
import time
from uuid import uuid4
from fastapi import APIRouter, Request, Response
from api.state import state

logger = logging.getLogger("feral.api.webhooks")
router = APIRouter(tags=["webhooks"])

_webhooks: dict[str, dict] = {}


@router.post("/api/webhooks/create")
async def create_webhook(body: dict):
    webhook_id = str(uuid4())[:12]
    name = body.get("name", "Untitled Webhook")
    secret = body.get("secret", "")
    action = body.get("action", "chat")
    action_params = body.get("action_params", {})

    _webhooks[webhook_id] = {
        "id": webhook_id,
        "name": name,
        "secret": secret,
        "action": action,
        "action_params": action_params,
        "created_at": time.time(),
        "last_triggered": None,
        "trigger_count": 0,
        "url": f"/api/webhooks/{webhook_id}/receive",
    }
    return {"success": True, "webhook": _webhooks[webhook_id]}


@router.get("/api/webhooks/list")
async def list_webhooks():
    return {"webhooks": list(_webhooks.values())}


@router.delete("/api/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str):
    if webhook_id in _webhooks:
        del _webhooks[webhook_id]
        return {"success": True}
    return {"success": False, "error": "Webhook not found"}


@router.post("/api/webhooks/{webhook_id}/receive")
async def receive_webhook(webhook_id: str, request: Request):
    if webhook_id not in _webhooks:
        return Response(status_code=404, content="Webhook not found")

    hook = _webhooks[webhook_id]
    body = await request.body()

    if hook["secret"]:
        sig_header = (
            request.headers.get("x-hub-signature-256", "")
            or request.headers.get("stripe-signature", "")
            or request.headers.get("x-signature", "")
        )
        # Fail-closed: when a secret is configured the request MUST carry
        # a valid signature header. A missing header is rejected outright
        # rather than silently bypassing verification.
        if not sig_header:
            return Response(status_code=401, content="Missing signature")
        expected = "sha256=" + hmac.new(
            hook["secret"].encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            return Response(status_code=403, content="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"raw": body.decode(errors="replace")}

    hook["last_triggered"] = time.time()
    hook["trigger_count"] += 1

    action = hook["action"]
    if action == "chat" and state.orchestrator:
        text = hook["action_params"].get("prefix", "Webhook received: ") + json.dumps(payload)[:2000]
        for sid in list(state.sessions.keys())[:1]:
            await state.orchestrator.handle_command(
                sid, text, context={"source": "webhook", "webhook_id": webhook_id}
            )

    if hasattr(state, "event_bus") and state.event_bus:
        from integrations.webhook_receiver import WebhookEvent

        event = WebhookEvent(
            app_id=f"custom_{webhook_id}",
            event_type="webhook.received",
            payload=payload,
        )
        await state.event_bus.emit(event)

    return {"ok": True}
