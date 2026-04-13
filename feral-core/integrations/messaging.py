"""
FERAL Messaging Integration — Telegram + Slack + Discord
==========================================================
Thin skill-facing wrappers that delegate send operations to the
canonical channel implementations in ``channels.base``.  Read-only
helpers (``get_updates``, ``list_channels``) that have no channel
equivalent are kept here.

The ``MessagingHub.execute(endpoint_id, args, vault)`` contract
consumed by the skill executor is unchanged.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from channels.base import (
    ChannelResponse,
    DiscordChannel,
    SlackChannel,
    TelegramChannel,
)

logger = logging.getLogger("feral.integrations.messaging")


# ── helpers ────────────────────────────────────────────────────────

def _init_telegram(token: str) -> TelegramChannel:
    """Create a TelegramChannel wired for outbound use (no poll loop)."""
    ch = TelegramChannel({"bot_token": token})
    ch._http = httpx.AsyncClient(timeout=10.0)
    ch._base_url = f"https://api.telegram.org/bot{token}"
    return ch


def _init_slack(token: str) -> SlackChannel:
    ch = SlackChannel({"bot_token": token})
    ch._http = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10.0,
    )
    return ch


def _init_discord(token: str) -> DiscordChannel:
    ch = DiscordChannel({"bot_token": token})
    ch._http = httpx.AsyncClient(
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        timeout=10.0,
    )
    return ch


# ── Telegram ───────────────────────────────────────────────────────

class TelegramBridge:
    """Skill-facing Telegram wrapper — delegates sends to TelegramChannel."""

    def __init__(self):
        self._token: Optional[str] = os.environ.get("FERAL_TELEGRAM_BOT_TOKEN")
        self._channel: Optional[TelegramChannel] = None
        if self._token:
            self._channel = _init_telegram(self._token)

    @property
    def connected(self) -> bool:
        return self._token is not None

    async def send(self, chat_id: str = "", text: str = "", **kwargs) -> dict:
        if not self._channel:
            return {"success": False, "error": "Telegram bot token not configured"}
        try:
            await self._channel.send(chat_id, ChannelResponse(text=text))
            return {"success": True, "data": {"chat_id": chat_id}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_updates(self, offset: int = 0, **kwargs) -> dict:
        """No channel equivalent — uses the channel's HTTP client directly."""
        if not self._channel:
            return {"success": False, "error": "Telegram bot token not configured"}
        try:
            resp = await self._channel._http.get(
                f"{self._channel._base_url}/getUpdates",
                params={"offset": offset, "timeout": 0, "limit": 25},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return {"success": False, "error": data.get("description", "Unknown Telegram error")}
            updates = []
            for u in data.get("result", []):
                msg = u.get("message", {})
                updates.append({
                    "update_id": u.get("update_id"),
                    "chat_id": msg.get("chat", {}).get("id"),
                    "from": msg.get("from", {}).get("first_name", ""),
                    "text": msg.get("text", ""),
                    "date": msg.get("date"),
                })
            return {"success": True, "data": {"updates": updates}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        if self._channel and hasattr(self._channel, "_http"):
            await self._channel._http.aclose()


# ── Slack ──────────────────────────────────────────────────────────

class SlackBridge:
    """Skill-facing Slack wrapper — delegates sends to SlackChannel."""

    def __init__(self):
        self._token: Optional[str] = os.environ.get("FERAL_SLACK_BOT_TOKEN")
        self._channel: Optional[SlackChannel] = None
        if self._token:
            self._channel = _init_slack(self._token)

    @property
    def connected(self) -> bool:
        return self._token is not None

    async def send(self, channel: str = "", text: str = "", **kwargs) -> dict:
        if not self._channel:
            return {"success": False, "error": "Slack bot token not configured"}
        try:
            await self._channel.send(channel, ChannelResponse(text=text))
            return {"success": True, "data": {"channel": channel}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def list_channels(self, **kwargs) -> dict:
        """No channel equivalent — uses the channel's HTTP client directly."""
        if not self._channel:
            return {"success": False, "error": "Slack bot token not configured"}
        try:
            resp = await self._channel._http.get(
                "https://slack.com/api/conversations.list",
                params={"types": "public_channel,private_channel", "limit": 100},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return {"success": False, "error": data.get("error", "Unknown Slack error")}
            channels = [
                {"id": c["id"], "name": c.get("name", ""), "is_member": c.get("is_member", False)}
                for c in data.get("channels", [])
            ]
            return {"success": True, "data": {"channels": channels}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        if self._channel and hasattr(self._channel, "_http"):
            await self._channel._http.aclose()


# ── Discord ────────────────────────────────────────────────────────

class DiscordBridge:
    """Skill-facing Discord wrapper — delegates sends to DiscordChannel."""

    DISCORD_API = "https://discord.com/api/v10"

    def __init__(self):
        self._token: Optional[str] = os.environ.get("FERAL_DISCORD_BOT_TOKEN")
        self._channel: Optional[DiscordChannel] = None
        if self._token:
            self._channel = _init_discord(self._token)

    @property
    def connected(self) -> bool:
        return self._token is not None

    async def send(self, channel_id: str = "", text: str = "", **kwargs) -> dict:
        if not self._channel:
            return {"success": False, "error": "Discord bot token not configured"}
        try:
            await self._channel.send(channel_id, ChannelResponse(text=text))
            return {"success": True, "data": {"channel_id": channel_id}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def list_channels(self, guild_id: str = "", **kwargs) -> dict:
        """No channel equivalent — uses the channel's HTTP client directly."""
        if not self._channel:
            return {"success": False, "error": "Discord bot token not configured"}
        try:
            resp = await self._channel._http.get(
                f"{self.DISCORD_API}/guilds/{guild_id}/channels",
            )
            resp.raise_for_status()
            raw = resp.json()
            channels = [
                {"id": c["id"], "name": c.get("name", ""), "type": c.get("type", 0)}
                for c in raw if c.get("type") in (0, 2, 5)
            ]
            return {"success": True, "data": {"channels": channels, "guild_id": guild_id}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        if self._channel and hasattr(self._channel, "_http"):
            await self._channel._http.aclose()


# ── Unified Hub ────────────────────────────────────────────────────

class MessagingHub:
    """
    Unified messaging dispatcher.
    Routes endpoint_id to the correct platform bridge.
    """

    def __init__(self, oauth_manager=None):
        self._oauth = oauth_manager
        self.telegram = TelegramBridge()
        self.slack = SlackBridge()
        self.discord = DiscordBridge()

    @property
    def connected(self) -> bool:
        return self.telegram.connected or self.slack.connected or self.discord.connected

    async def execute(self, endpoint_id: str, args: dict, vault: dict = None) -> dict:
        """Skill executor interface — called by SkillExecutor."""
        dispatch = {
            "telegram_send": self.telegram.send,
            "telegram_get_updates": self.telegram.get_updates,
            "slack_send": self.slack.send,
            "slack_list_channels": self.slack.list_channels,
            "discord_send": self.discord.send,
            "discord_list_channels": self.discord.list_channels,
        }
        fn = dispatch.get(endpoint_id)
        if not fn:
            return {"success": False, "error": f"Unknown endpoint: {endpoint_id}"}
        return await fn(**args)

    async def close(self):
        await self.telegram.close()
        await self.slack.close()
        await self.discord.close()
