"""
FERAL Messaging Integration — Telegram + Slack + Discord
==========================================================
Unified messaging hub routing to platform-specific bridges.
Each bridge is self-contained; the MessagingHub dispatches via
the standard execute(endpoint_id, args, vault) interface.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("feral.integrations.messaging")


# ── Telegram ───────────────────────────────────────────────────────

class TelegramBridge:
    """Telegram Bot API bridge."""

    BASE = "https://api.telegram.org"

    def __init__(self):
        self._token: Optional[str] = os.environ.get("FERAL_TELEGRAM_BOT_TOKEN")
        self._http = httpx.AsyncClient(timeout=10.0)

    @property
    def connected(self) -> bool:
        return self._token is not None

    @property
    def _base(self) -> str:
        return f"{self.BASE}/bot{self._token}"

    async def send(self, chat_id: str = "", text: str = "", **kwargs) -> dict:
        if not self._token:
            return {"success": False, "error": "Telegram bot token not configured"}
        try:
            resp = await self._http.post(
                f"{self._base}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return {"success": False, "error": data.get("description", "Unknown Telegram error")}
            return {"success": True, "data": {"message_id": data["result"]["message_id"], "chat_id": chat_id}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_updates(self, offset: int = 0, **kwargs) -> dict:
        if not self._token:
            return {"success": False, "error": "Telegram bot token not configured"}
        try:
            resp = await self._http.get(
                f"{self._base}/getUpdates",
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
        await self._http.aclose()


# ── Slack ──────────────────────────────────────────────────────────

class SlackBridge:
    """Slack Web API bridge using a Bot Token."""

    BASE = "https://slack.com/api"

    def __init__(self):
        self._token: Optional[str] = os.environ.get("FERAL_SLACK_BOT_TOKEN")
        self._http = httpx.AsyncClient(base_url=self.BASE, timeout=10.0)

    @property
    def connected(self) -> bool:
        return self._token is not None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    async def send(self, channel: str = "", text: str = "", **kwargs) -> dict:
        if not self._token:
            return {"success": False, "error": "Slack bot token not configured"}
        try:
            resp = await self._http.post(
                "/chat.postMessage",
                json={"channel": channel, "text": text},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return {"success": False, "error": data.get("error", "Unknown Slack error")}
            return {"success": True, "data": {"channel": channel, "ts": data.get("ts", "")}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def list_channels(self, **kwargs) -> dict:
        if not self._token:
            return {"success": False, "error": "Slack bot token not configured"}
        try:
            resp = await self._http.get(
                "/conversations.list",
                params={"types": "public_channel,private_channel", "limit": 100},
                headers=self._headers(),
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
        await self._http.aclose()


# ── Discord ────────────────────────────────────────────────────────

class DiscordBridge:
    """Discord Bot API bridge."""

    BASE = "https://discord.com/api/v10"

    def __init__(self):
        self._token: Optional[str] = os.environ.get("FERAL_DISCORD_BOT_TOKEN")
        self._http = httpx.AsyncClient(base_url=self.BASE, timeout=10.0)

    @property
    def connected(self) -> bool:
        return self._token is not None

    def _headers(self) -> dict:
        return {"Authorization": f"Bot {self._token}"}

    async def send(self, channel_id: str = "", text: str = "", **kwargs) -> dict:
        if not self._token:
            return {"success": False, "error": "Discord bot token not configured"}
        try:
            resp = await self._http.post(
                f"/channels/{channel_id}/messages",
                json={"content": text},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "data": {"message_id": data.get("id", ""), "channel_id": channel_id}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def list_channels(self, guild_id: str = "", **kwargs) -> dict:
        if not self._token:
            return {"success": False, "error": "Discord bot token not configured"}
        try:
            resp = await self._http.get(
                f"/guilds/{guild_id}/channels",
                headers=self._headers(),
            )
            resp.raise_for_status()
            raw = resp.json()
            channels = [
                {"id": c["id"], "name": c.get("name", ""), "type": c.get("type", 0)}
                for c in raw if c.get("type") in (0, 2, 5)  # text, voice, announcement
            ]
            return {"success": True, "data": {"channels": channels, "guild_id": guild_id}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        await self._http.aclose()


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
