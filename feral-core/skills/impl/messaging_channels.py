"""
Unified messaging channels skill.

Routes the LLM's `messaging_channels__send` tool call through the live
ChannelManager on BrainState. Follows the unified message-tool pattern:
one tool, dynamic routing, never say "I can't" when a channel exists.

The channel instances (TelegramChannel, SlackChannel, DiscordChannel,
WhatsAppChannel) expose a unified `send_direct(to, text)` method we
added in channels/base.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skill.messaging_channels")


@register_skill
class MessagingChannelsSkill(BaseSkill):
    """Unified outbound messaging across all configured channels."""

    def __init__(self):
        super().__init__("messaging_channels")

    @staticmethod
    def _get_channel_manager():
        try:
            from api.state import state
            return getattr(state, "channel_manager", None)
        except Exception:
            return None

    async def execute(
        self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]
    ) -> Dict[str, Any]:
        cm = self._get_channel_manager()
        if cm is None:
            return {
                "success": False,
                "status_code": 503,
                "data": None,
                "error": "Channel manager not initialized. FERAL brain is still starting up.",
            }

        if endpoint_id == "list_channels":
            return await self._list_channels(cm)
        if endpoint_id == "list_recent_chats":
            return await self._list_recent_chats(cm, args)
        if endpoint_id == "resolve_chat_id":
            return await self._resolve_chat_id(cm, args)
        if endpoint_id == "send":
            return await self._send(cm, args)

        return {
            "success": False,
            "status_code": 400,
            "data": None,
            "error": f"Unknown endpoint: {endpoint_id}",
        }

    async def _list_channels(self, cm) -> Dict[str, Any]:
        rows = []
        for ctype, ch in cm.channels.items():
            row = {
                "name": ctype,
                "running": bool(getattr(ch, "_running", False)),
                "known_chats": len(getattr(ch, "_known_chat_ids", []) or []),
            }
            bot_username = getattr(ch, "_bot_username", None)
            if bot_username:
                row["bot_username"] = bot_username
            rows.append(row)
        return {
            "success": True,
            "status_code": 200,
            "data": {"channels": rows},
            "error": None,
        }

    async def _list_recent_chats(self, cm, args: Dict[str, Any]) -> Dict[str, Any]:
        channel = (args.get("channel") or "").lower().strip()
        ch = cm.get_channel(channel)
        if not ch:
            return self._not_configured(channel, cm)
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "channel": channel,
                "chats": list(getattr(ch, "_known_chat_ids", []) or []),
            },
            "error": None,
        }

    async def _resolve_chat_id(self, cm, args: Dict[str, Any]) -> Dict[str, Any]:
        channel = (args.get("channel") or "").lower().strip()
        handle = (args.get("handle") or "").strip()
        if not handle:
            return {"success": False, "status_code": 400, "data": None, "error": "handle is required"}
        ch = cm.get_channel(channel)
        if not ch:
            return self._not_configured(channel, cm)
        resolver = getattr(ch, "resolve_username", None)
        if not resolver:
            return {
                "success": False,
                "status_code": 400,
                "data": None,
                "error": f"Channel {channel!r} does not support username resolution.",
            }
        try:
            resolved = await resolver(handle)
        except Exception as e:
            return {"success": False, "status_code": 502, "data": None, "error": str(e)}
        if not resolved:
            return {
                "success": False,
                "status_code": 404,
                "data": None,
                "error": (
                    f"Could not resolve {handle!r} on {channel}. "
                    "The user likely needs to message the bot first so it learns their chat_id."
                ),
            }
        return {
            "success": True,
            "status_code": 200,
            "data": resolved,
            "error": None,
        }

    async def _send(self, cm, args: Dict[str, Any]) -> Dict[str, Any]:
        channel = (args.get("channel") or "").lower().strip()
        to = (args.get("to") or "").strip()
        text = args.get("text") or ""
        reply_to = args.get("reply_to") or None

        if not channel:
            return {"success": False, "status_code": 400, "data": None, "error": "channel is required"}
        if not to:
            return {"success": False, "status_code": 400, "data": None, "error": "to is required"}
        if not text:
            return {"success": False, "status_code": 400, "data": None, "error": "text is required"}

        ch = cm.get_channel(channel)
        if not ch:
            return self._not_configured(channel, cm)

        sender = getattr(ch, "send_direct", None)
        if not sender:
            return {
                "success": False,
                "status_code": 501,
                "data": None,
                "error": f"Channel {channel!r} has no outbound send_direct implementation.",
            }

        try:
            result = await sender(to, text, reply_to=reply_to)
        except Exception as e:
            logger.error("messaging_channels.send failed: %s", e, exc_info=True)
            return {"success": False, "status_code": 502, "data": None, "error": str(e)}

        if not isinstance(result, dict):
            result = {"success": True, "raw": result}

        if not result.get("success", False):
            return {
                "success": False,
                "status_code": int(result.get("status_code", 502)),
                "data": None,
                "error": result.get("error") or f"Send via {channel} failed.",
            }

        return {
            "success": True,
            "status_code": 200,
            "data": {
                "channel": channel,
                "to": to,
                "preview": text[:120],
                "message_id": result.get("message_id"),
                "raw": result.get("raw"),
            },
            "error": None,
        }

    @staticmethod
    def _not_configured(channel: str, cm) -> Dict[str, Any]:
        active = ", ".join(cm.active_channels) or "none"
        return {
            "success": False,
            "status_code": 409,
            "data": None,
            "error": (
                f"Channel {channel!r} is not configured on this FERAL brain. "
                f"Active channels: {active}. Ask the user to run `feral setup` "
                f"and add the credentials for {channel}."
            ),
        }
