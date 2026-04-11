"""Channel management and WhatsApp webhook endpoints."""

import json
import logging
import os

from fastapi import APIRouter, Request, Response

from api.state import state

logger = logging.getLogger("feral.brain")

router = APIRouter()


@router.get("/api/channels")
async def list_channels():
    if not state.channel_manager:
        return {"channels": []}
    return state.channel_manager.stats


@router.post("/api/channels/start")
async def start_channel(body: dict):
    channel_type = body.get("type", "")
    config = body.get("config", {})
    if not state.channel_manager:
        return {"error": "Channel manager not initialized"}
    await state.channel_manager.start_channel(channel_type, config)
    return {"ok": True, "channel": channel_type}


@router.get("/api/channels/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    """WhatsApp webhook verification (GET challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "feral-verify")
    if mode == "subscribe" and token == verify_token:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


@router.post("/api/channels/whatsapp/webhook")
async def whatsapp_webhook_inbound(request: Request):
    """Handle inbound WhatsApp messages."""
    try:
        body = await request.json()
        from channels.base import WhatsAppChannel
        channel_mgr = getattr(state, "channel_manager", None)
        if channel_mgr:
            wa = channel_mgr.get_channel("whatsapp")
            if wa and isinstance(wa, WhatsAppChannel):
                response = await wa.handle_webhook(body)
                return {"status": "ok", "response": response}
        return {"status": "no_handler"}
    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}")
        return {"status": "error", "detail": str(e)}
