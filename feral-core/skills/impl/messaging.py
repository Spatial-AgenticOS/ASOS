"""Unified messaging skill — dispatches to ChannelManager and Twilio SMS."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict

import httpx

from channels.base import ChannelResponse
from channels.contact_store import get_contact_store
from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skills.messaging")

_TELEGRAM_BOT_USER_RE = re.compile(r"^@?([a-zA-Z0-9_]{3,})$")


def _telegram_invite_hint() -> str:
    name = (
        os.environ.get("FERAL_TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
        or "YourBot"
    )
    return f"https://t.me/{name}"


async def _send_twilio_sms(to: str, body: str) -> dict:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_num = os.environ.get("TWILIO_PHONE_NUMBER", "")
    if not (sid and token and from_num):
        return {
            "success": False,
            "error": (
                "SMS requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and "
                "TWILIO_PHONE_NUMBER (set in ~/.feral/credentials.json or environment)."
            ),
        }
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            url,
            auth=(sid, token),
            data={"To": to, "From": from_num, "Body": body},
        )
        if r.status_code >= 400:
            return {"success": False, "error": r.text[:500]}
        return {"success": True, "data": r.json()}


def _resolve_telegram_target(raw: str) -> tuple[str, str | None]:
    """Returns (chat_id_or_empty, error_message)."""
    t = (raw or "").strip()
    if not t:
        return "", "Missing target"
    if t.lstrip("-").isdigit():
        return t, None
    if t.startswith("@") or _TELEGRAM_BOT_USER_RE.match(t):
        un = t.lstrip("@")
        resolved = get_contact_store().resolve_username("telegram", un)
        if resolved:
            return resolved, None
        return "", (
            f"No chat_id for @{un}. Ask them to open {_telegram_invite_hint()} "
            "and tap Start first, then message the bot again."
        )
    un = t
    resolved = get_contact_store().resolve_username("telegram", un)
    if resolved:
        return resolved, None
    return "", (
        f"No chat_id for {t!r}. For Telegram, the user must /start the bot first. "
        f"Share: {_telegram_invite_hint()}"
    )


@register_skill
class MessagingSkill(BaseSkill):
    def __init__(self) -> None:
        super().__init__(skill_id="messaging")

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        from api.state import state

        if endpoint_id == "send":
            return await self._send(state, args)
        if endpoint_id == "broadcast":
            return await self._broadcast(state, args)
        if endpoint_id == "list_chats":
            return await self._list_chats(state, args)
        return {"success": False, "error": f"Unknown endpoint: {endpoint_id}"}

    async def _send(self, state, args: dict) -> dict:
        channel = (args.get("channel") or "").strip().lower()
        target = args.get("target") or ""
        text = args.get("text") or ""
        if not channel or not text:
            return {"success": False, "error": "channel and text are required"}

        cm = state.channel_manager
        if not cm:
            return {"success": False, "error": "Channel manager not initialized"}

        if channel == "telegram":
            chat_id, err = _resolve_telegram_target(str(target))
            if err:
                return {"success": False, "error": err}
            await cm.send_to_channel("telegram", chat_id, ChannelResponse(text=text))
            return {"success": True, "data": {"channel": "telegram", "chat_id": chat_id}}

        if channel == "slack":
            await cm.send_to_channel("slack", str(target), ChannelResponse(text=text))
            return {"success": True, "data": {"channel": "slack", "target": str(target)}}

        if channel == "discord":
            await cm.send_to_channel("discord", str(target), ChannelResponse(text=text))
            return {"success": True, "data": {"channel": "discord", "target": str(target)}}

        if channel == "whatsapp":
            ch = cm.get_channel("whatsapp")
            if not ch:
                return {"success": False, "error": "WhatsApp channel not started"}
            result = await ch.send_text(str(target), text)
            return result if isinstance(result, dict) else {"success": True, "data": result}

        if channel == "sms":
            return await _send_twilio_sms(str(target), text)

        return {"success": False, "error": f"Unsupported channel: {channel}"}

    async def _broadcast(self, state, args: dict) -> dict:
        channel = (args.get("channel") or "").strip().lower()
        text = args.get("text") or ""
        if not channel or not text:
            return {"success": False, "error": "channel and text are required"}
        cm = state.channel_manager
        if not cm:
            return {"success": False, "error": "Channel manager not initialized"}
        if channel == "sms":
            return {"success": False, "error": "SMS broadcast not supported (use Twilio loops externally)"}
        await cm.broadcast(ChannelResponse(text=text))
        return {"success": True, "data": {"channel": channel, "mode": "broadcast"}}

    async def _list_chats(self, state, args: dict) -> dict:
        channel = (args.get("channel") or "").strip().lower()
        if not channel:
            return {"success": False, "error": "channel is required"}

        if channel == "telegram":
            rows = get_contact_store().list_for_channel("telegram")
            seen = {r["target_id"] for r in rows}
            cm = state.channel_manager
            extra: list[dict] = []
            if cm:
                tch = cm.get_channel("telegram")
                if tch:
                    for cid in tch.active_chat_ids:
                        if cid not in seen:
                            extra.append(
                                {
                                    "channel": "telegram",
                                    "username": None,
                                    "target_id": cid,
                                    "first_name": "",
                                    "source": "session",
                                }
                            )
            merged = [
                {
                    "channel": r["channel"],
                    "username": r.get("username"),
                    "target_id": r["target_id"],
                    "first_name": r.get("first_name"),
                    "source": "store",
                }
                for r in rows
            ] + extra
            return {"success": True, "data": {"chats": merged}}

        if channel == "slack":
            hub = state.messaging
            if hub and hub.slack.connected:
                return await hub.slack.list_channels()
            return {"success": False, "error": "Slack bot token not configured or hub unavailable"}
        if channel == "discord":
            hub = state.messaging
            gid = (args.get("guild_id") or "").strip()
            if not gid:
                return {
                    "success": False,
                    "error": "Discord list_chats requires guild_id parameter",
                }
            if hub and hub.discord.connected:
                return await hub.discord.list_channels(guild_id=gid)
            return {"success": False, "error": "Discord bot token not configured or hub unavailable"}

        if channel == "whatsapp":
            cm = state.channel_manager
            if not cm:
                return {"success": False, "error": "Channel manager not initialized"}
            wch = cm.get_channel("whatsapp")
            if not wch:
                return {"success": False, "error": "WhatsApp channel not started"}
            chats = [{"target_id": x, "channel": "whatsapp"} for x in wch.active_chat_ids]
            return {"success": True, "data": {"chats": chats}}

        if channel == "sms":
            return {
                "success": True,
                "data": {
                    "chats": [],
                    "hint": "SMS does not maintain a chat directory; use Twilio logs in the dashboard.",
                },
            }

        return {"success": False, "error": f"Channel not available or not connected: {channel}"}
