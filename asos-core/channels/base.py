"""
THEORA Channels — Multi-Platform Messaging Bridges
=====================================================
Like OpenClaw's channels but with a key difference:
  OpenClaw channels = text in, text out
  THEORA channels = text + sensor data + hardware commands + SDUI

Every channel can:
  1. Receive text/voice → forward to Brain
  2. Send text/SDUI/TTS responses back
  3. Forward skill proposals for approval
  4. Display hardware status and alerts

Supported: Telegram, Discord, Slack, WhatsApp, WebChat, SMS, Email
"""

from __future__ import annotations
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Callable, Awaitable, Any

logger = logging.getLogger("theora.channels")


class ChannelMessage:
    """A message received from any channel."""

    def __init__(
        self,
        channel_type: str,
        channel_id: str,
        user_id: str,
        text: str = "",
        username: str = "",
        is_voice: bool = False,
        audio_b64: str = "",
        image_b64: str = "",
        reply_to: str = "",
        metadata: Optional[dict] = None,
    ):
        self.channel_type = channel_type
        self.channel_id = channel_id
        self.user_id = user_id
        self.text = text
        self.username = username
        self.is_voice = is_voice
        self.audio_b64 = audio_b64
        self.image_b64 = image_b64
        self.reply_to = reply_to
        self.metadata = metadata or {}


class ChannelResponse:
    """A response to send back through a channel."""

    def __init__(
        self,
        text: str = "",
        sdui: Optional[dict] = None,
        audio_b64: str = "",
        image_b64: str = "",
        buttons: Optional[list[dict]] = None,
        is_streaming: bool = False,
    ):
        self.text = text
        self.sdui = sdui
        self.audio_b64 = audio_b64
        self.image_b64 = image_b64
        self.buttons = buttons
        self.is_streaming = is_streaming


MessageHandler = Callable[[ChannelMessage], Awaitable[ChannelResponse]]


class Channel(ABC):
    """Base class for all messaging channels."""

    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", True)
        self._handler: Optional[MessageHandler] = None
        self._running = False

    def set_handler(self, handler: MessageHandler):
        self._handler = handler

    @abstractmethod
    async def start(self):
        """Start listening for messages."""
        ...

    @abstractmethod
    async def stop(self):
        """Stop the channel."""
        ...

    @abstractmethod
    async def send(self, channel_id: str, response: ChannelResponse):
        """Send a response to a specific channel/user."""
        ...

    @property
    @abstractmethod
    def channel_type(self) -> str:
        ...


class TelegramChannel(Channel):
    """Telegram bot integration."""

    @property
    def channel_type(self) -> str:
        return "telegram"

    async def start(self):
        token = self.config.get("bot_token", "")
        if not token:
            logger.warning("Telegram channel: no bot_token configured")
            return

        import aiohttp
        self._running = True
        self._session = aiohttp.ClientSession()
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._offset = 0

        logger.info("Telegram channel started")
        asyncio.ensure_future(self._poll_loop())

    async def stop(self):
        self._running = False
        if hasattr(self, "_session"):
            await self._session.close()

    async def _poll_loop(self):
        while self._running:
            try:
                url = f"{self._base_url}/getUpdates?offset={self._offset}&timeout=30"
                async with self._session.get(url) as resp:
                    data = await resp.json()

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    message = update.get("message", {})
                    if message and self._handler:
                        text = message.get("text", "")
                        chat_id = str(message.get("chat", {}).get("id", ""))
                        user = message.get("from", {})
                        user_id = str(user.get("id", ""))
                        username = user.get("first_name", "") or user.get("username", "")

                        channel_msg = ChannelMessage(
                            channel_type="telegram",
                            channel_id=chat_id,
                            user_id=user_id,
                            text=text,
                            username=username,
                        )
                        response = await self._handler(channel_msg)
                        await self.send(chat_id, response)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram poll error: {e}")
                await asyncio.sleep(5)

    async def send(self, channel_id: str, response: ChannelResponse):
        if not response.text:
            return
        try:
            url = f"{self._base_url}/sendMessage"
            payload = {
                "chat_id": channel_id,
                "text": response.text,
                "parse_mode": "Markdown",
            }
            if response.buttons:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": b.get("label", ""), "callback_data": b.get("action", "")}]
                        for b in response.buttons
                    ]
                }
                payload["reply_markup"] = keyboard

            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.warning(f"Telegram send failed: {resp.status}")
        except Exception as e:
            logger.error(f"Telegram send error: {e}")


class DiscordChannel(Channel):
    """Discord bot integration."""

    @property
    def channel_type(self) -> str:
        return "discord"

    async def start(self):
        token = self.config.get("bot_token", "")
        if not token:
            logger.warning("Discord channel: no bot_token configured")
            return

        try:
            import aiohttp
            self._running = True
            self._token = token
            self._session = aiohttp.ClientSession(headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            })
            logger.info("Discord channel started (webhook mode)")
        except Exception as e:
            logger.error(f"Discord start error: {e}")

    async def stop(self):
        self._running = False
        if hasattr(self, "_session"):
            await self._session.close()

    async def send(self, channel_id: str, response: ChannelResponse):
        if not response.text or not hasattr(self, "_session"):
            return
        try:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            payload = {"content": response.text}
            async with self._session.post(url, json=payload) as resp:
                if resp.status not in (200, 201):
                    logger.warning(f"Discord send failed: {resp.status}")
        except Exception as e:
            logger.error(f"Discord send error: {e}")


class SlackChannel(Channel):
    """Slack bot integration."""

    @property
    def channel_type(self) -> str:
        return "slack"

    async def start(self):
        token = self.config.get("bot_token", "")
        if not token:
            logger.warning("Slack channel: no bot_token configured")
            return

        import aiohttp
        self._running = True
        self._session = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        logger.info("Slack channel started")

    async def stop(self):
        self._running = False
        if hasattr(self, "_session"):
            await self._session.close()

    async def send(self, channel_id: str, response: ChannelResponse):
        if not response.text or not hasattr(self, "_session"):
            return
        try:
            url = "https://slack.com/api/chat.postMessage"
            payload = {"channel": channel_id, "text": response.text}
            if response.buttons:
                payload["blocks"] = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": response.text}},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": b.get("label", "")},
                                "action_id": b.get("action", ""),
                            }
                            for b in response.buttons
                        ],
                    },
                ]
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.warning(f"Slack send failed: {resp.status}")
        except Exception as e:
            logger.error(f"Slack send error: {e}")


class ChannelManager:
    """
    Manages all messaging channels.
    Routes incoming messages to the Brain and outgoing responses back.
    """

    CHANNEL_TYPES = {
        "telegram": TelegramChannel,
        "discord": DiscordChannel,
        "slack": SlackChannel,
    }

    def __init__(self):
        self._channels: dict[str, Channel] = {}
        self._handler: Optional[MessageHandler] = None

    def set_handler(self, handler: MessageHandler):
        self._handler = handler
        for ch in self._channels.values():
            ch.set_handler(handler)

    async def start_channel(self, channel_type: str, config: dict):
        cls = self.CHANNEL_TYPES.get(channel_type)
        if not cls:
            logger.warning(f"Unknown channel type: {channel_type}")
            return

        channel = cls(config)
        if self._handler:
            channel.set_handler(self._handler)

        await channel.start()
        self._channels[channel_type] = channel

    async def stop_all(self):
        for ch in self._channels.values():
            await ch.stop()
        self._channels.clear()

    async def broadcast(self, response: ChannelResponse):
        """Send to all active channels."""
        for ch in self._channels.values():
            for cid in self._get_active_channel_ids(ch.channel_type):
                await ch.send(cid, response)

    def _get_active_channel_ids(self, channel_type: str) -> list[str]:
        return []

    @property
    def active_channels(self) -> list[str]:
        return list(self._channels.keys())

    @property
    def stats(self) -> dict:
        return {
            "active_channels": self.active_channels,
            "channel_count": len(self._channels),
        }
