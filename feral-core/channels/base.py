"""
FERAL Channels — Multi-Platform Messaging Bridges
=====================================================
Bidirectional messaging bridges with support for text, voice notes,
images, and SDUI.  Every channel can receive and send rich content.

Supported: Telegram, Discord, Slack, WhatsApp
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, Callable, Awaitable, Any

logger = logging.getLogger("feral.channels")


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
        self._known_chat_ids: set[str] = set()

    def set_handler(self, handler: MessageHandler):
        self._handler = handler

    async def _emit_comms_event(self, direction: str, sender_or_recipient: str, preview: str = "", extra: dict = None):
        """Emit brain_event for Glass Brain comms visualization. direction: 'in' or 'out'."""
        try:
            from observability.metrics import increment
            channel_name = self.__class__.__name__.replace("Channel", "").lower()
            increment("feral.channel.message_total", attributes={"channel": channel_name, "direction": direction})
        except Exception:
            pass
        try:
            from api.state import state
            if not state.orchestrator:
                return
            payload = {
                "channel": self.__class__.__name__.replace("Channel", "").lower(),
                "direction": direction,
            }
            if direction == "in":
                payload["sender"] = sender_or_recipient
            else:
                payload["recipient"] = sender_or_recipient
            payload["preview"] = (preview or "")[:100]
            if extra:
                payload.update(extra)
            event_type = "channel_message_in" if direction == "in" else "channel_message_out"
            for sid in list(state.sessions.keys()):
                try:
                    await state.orchestrator._emit_brain_event(sid, event_type, payload)
                except Exception:
                    pass
        except Exception:
            pass

    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...

    @abstractmethod
    async def send(self, channel_id: str, response: ChannelResponse):
        ...

    @property
    @abstractmethod
    def channel_type(self) -> str:
        ...

    @property
    def active_chat_ids(self) -> list[str]:
        return list(self._known_chat_ids)

    @staticmethod
    async def _http_with_retry(client, method: str, url: str, **kw):
        """Exponential-backoff retry for 429 / 503 responses (up to 3 attempts)."""
        fn = getattr(client, method.lower(), None) or client.request
        r = None
        for attempt in range(3):
            if fn is client.request:
                r = await fn(method, url, **kw)
            else:
                r = await fn(url, **kw)
            if hasattr(r, "status_code") and r.status_code in (429, 503):
                logger.warning("Channel HTTP %s %s returned %d (attempt %d/3)", method, url[:80], r.status_code, attempt + 1)
                await asyncio.sleep(2 ** attempt)
                continue
            return r
        return r


class TelegramChannel(Channel):
    """Telegram bot — full bidirectional with voice/image support."""

    @property
    def channel_type(self) -> str:
        return "telegram"

    async def start(self):
        token = self.config.get("bot_token", "")
        if not token:
            logger.warning("Telegram channel: no bot_token configured")
            return

        import httpx
        self._running = True
        self._http = httpx.AsyncClient(timeout=35.0)
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._offset = 0
        logger.info("Telegram channel started")
        asyncio.ensure_future(self._poll_loop())

    async def stop(self):
        self._running = False
        if hasattr(self, "_http"):
            await self._http.aclose()

    async def _poll_loop(self):
        while self._running:
            try:
                resp = await self._http.get(
                    f"{self._base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 30},
                )
                data = resp.json()

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    message = update.get("message", {})
                    callback = update.get("callback_query")

                    if callback and self._handler:
                        await self._handle_callback(callback)
                    elif message and self._handler:
                        await self._handle_message(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram poll error: {e}")
                await asyncio.sleep(5)

    async def _handle_message(self, message: dict):
        chat_id = str(message.get("chat", {}).get("id", ""))
        user = message.get("from", {})
        user_id = str(user.get("id", ""))
        username = user.get("first_name", "") or user.get("username", "")
        self._known_chat_ids.add(chat_id)

        text = message.get("text", "")
        is_voice = "voice" in message
        image_b64 = ""

        if message.get("photo"):
            photo = message["photo"][-1]
            image_b64 = await self._download_file(photo.get("file_id", ""))

        channel_msg = ChannelMessage(
            channel_type="telegram",
            channel_id=chat_id,
            user_id=user_id,
            text=text,
            username=username,
            is_voice=is_voice,
            image_b64=image_b64,
        )
        await self._emit_comms_event("in", username or user_id, text)
        response = await self._handler(channel_msg)
        await self.send(chat_id, response)

    async def _handle_callback(self, callback: dict):
        chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
        data = callback.get("data", "")
        user_id = str(callback.get("from", {}).get("id", ""))
        self._known_chat_ids.add(chat_id)

        channel_msg = ChannelMessage(
            channel_type="telegram",
            channel_id=chat_id,
            user_id=user_id,
            text=data,
            metadata={"callback": True},
        )
        await self._emit_comms_event("in", user_id, data, {"callback": True})
        response = await self._handler(channel_msg)
        await self.send(chat_id, response)

        await self._http.post(
            f"{self._base_url}/answerCallbackQuery",
            json={"callback_query_id": callback.get("id", "")},
        )

    async def _download_file(self, file_id: str) -> str:
        import base64
        try:
            resp = await self._http.get(f"{self._base_url}/getFile", params={"file_id": file_id})
            file_path = resp.json().get("result", {}).get("file_path", "")
            if file_path:
                token = self.config.get("bot_token", "")
                file_resp = await self._http.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
                return base64.b64encode(file_resp.content).decode()
        except Exception as e:
            logger.error(f"Telegram file download failed: {e}")
        return ""

    async def send(self, channel_id: str, response: ChannelResponse):
        if not response.text and not response.image_b64:
            return
        tg_logger = logging.getLogger("feral.channel.telegram")
        try:
            payload = {
                "chat_id": channel_id,
                "text": response.text or "(see attachment)",
                "parse_mode": "Markdown",
            }
            if response.buttons:
                payload["reply_markup"] = {
                    "inline_keyboard": [
                        [{"text": b.get("label", ""), "callback_data": b.get("action", "")}]
                        for b in response.buttons
                    ]
                }
            await self._http_with_retry(self._http, "POST", f"{self._base_url}/sendMessage", json=payload)
            await self._emit_comms_event("out", channel_id, response.text)
        except Exception as e:
            tg_logger.error("Telegram send error: %s", e)


class DiscordChannel(Channel):
    """Discord bot — Gateway WebSocket for incoming, REST for outgoing."""

    @property
    def channel_type(self) -> str:
        return "discord"

    async def start(self):
        token = self.config.get("bot_token", "")
        if not token:
            logger.warning("Discord channel: no bot_token configured")
            return

        import httpx
        self._running = True
        self._token = token
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            timeout=10.0,
        )

        asyncio.ensure_future(self._gateway_connect())
        logger.info("Discord channel started (Gateway mode)")

    async def _gateway_connect(self):
        """Connect to Discord Gateway for incoming messages."""
        try:
            import websockets
            resp = await self._http.get("https://discord.com/api/v10/gateway")
            gateway_url = resp.json().get("url", "")
            if not gateway_url:
                logger.warning("Discord: could not get gateway URL")
                return

            async with websockets.connect(f"{gateway_url}?v=10&encoding=json") as ws:
                hello = json.loads(await ws.recv())
                heartbeat_interval = hello.get("d", {}).get("heartbeat_interval", 41250) / 1000

                await ws.send(json.dumps({
                    "op": 2,
                    "d": {
                        "token": self._token,
                        "intents": 512 | 32768,
                        "properties": {"os": "linux", "browser": "feral", "device": "feral"},
                    },
                }))

                asyncio.ensure_future(self._heartbeat_loop(ws, heartbeat_interval))

                async for raw in ws:
                    if not self._running:
                        break
                    event = json.loads(raw)
                    if event.get("t") == "MESSAGE_CREATE":
                        await self._handle_discord_message(event.get("d", {}))

        except Exception as e:
            if self._running:
                logger.error(f"Discord gateway error: {e}")
                await asyncio.sleep(10)
                if self._running:
                    asyncio.ensure_future(self._gateway_connect())

    async def _heartbeat_loop(self, ws, interval: float):
        while self._running:
            await asyncio.sleep(interval)
            try:
                await ws.send(json.dumps({"op": 1, "d": None}))
            except Exception:
                break

    async def _handle_discord_message(self, data: dict):
        if data.get("author", {}).get("bot"):
            return

        channel_id = data.get("channel_id", "")
        user_id = data.get("author", {}).get("id", "")
        username = data.get("author", {}).get("username", "")
        text = data.get("content", "")
        self._known_chat_ids.add(channel_id)

        if self._handler:
            channel_msg = ChannelMessage(
                channel_type="discord",
                channel_id=channel_id,
                user_id=user_id,
                text=text,
                username=username,
            )
            await self._emit_comms_event("in", username or user_id, text)
            response = await self._handler(channel_msg)
            await self.send(channel_id, response)

    async def stop(self):
        self._running = False
        if hasattr(self, "_http"):
            await self._http.aclose()

    async def send(self, channel_id: str, response: ChannelResponse):
        if not response.text:
            return
        dc_logger = logging.getLogger("feral.channel.discord")
        try:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            await self._http_with_retry(self._http, "POST", url, json={"content": response.text})
            await self._emit_comms_event("out", channel_id, response.text)
        except Exception as e:
            dc_logger.error("Discord send error: %s", e)


class SlackChannel(Channel):
    """Slack bot — Socket Mode for incoming, Web API for outgoing."""

    @property
    def channel_type(self) -> str:
        return "slack"

    async def start(self):
        bot_token = self.config.get("bot_token", "")
        app_token = self.config.get("app_token", "")
        if not bot_token:
            logger.warning("Slack channel: no bot_token configured")
            return

        import httpx
        self._running = True
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
            timeout=10.0,
        )

        if app_token:
            asyncio.ensure_future(self._socket_mode(app_token))
            logger.info("Slack channel started (Socket Mode)")
        else:
            logger.info("Slack channel started (outbound only — add app_token for incoming)")

    async def _socket_mode(self, app_token: str):
        """Connect via Slack Socket Mode for incoming events."""
        try:
            import httpx as hx
            async with hx.AsyncClient() as client:
                resp = await client.post(
                    "https://slack.com/api/apps.connections.open",
                    headers={"Authorization": f"Bearer {app_token}"},
                )
                ws_url = resp.json().get("url", "")
                if not ws_url:
                    logger.warning("Slack: could not get Socket Mode URL")
                    return

            import websockets
            _ws = None
            for _attempt in range(3):
                try:
                    _ws = await websockets.connect(ws_url)
                    break
                except Exception:
                    if _attempt == 2:
                        raise
                    await asyncio.sleep(2 ** _attempt)

            async with _ws as ws:
                async for raw in ws:
                    if not self._running:
                        break
                    event = json.loads(raw)

                    if event.get("type") == "events_api":
                        await ws.send(json.dumps({
                            "envelope_id": event.get("envelope_id", ""),
                        }))
                        payload = event.get("payload", {}).get("event", {})
                        if payload.get("type") == "message" and not payload.get("bot_id"):
                            await self._handle_slack_message(payload)

        except Exception as e:
            if self._running:
                logger.error(f"Slack Socket Mode error: {e}")
                await asyncio.sleep(10)
                if self._running:
                    asyncio.ensure_future(self._socket_mode(app_token))

    async def _handle_slack_message(self, event: dict):
        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        text = event.get("text", "")
        self._known_chat_ids.add(channel_id)

        if self._handler:
            channel_msg = ChannelMessage(
                channel_type="slack",
                channel_id=channel_id,
                user_id=user_id,
                text=text,
            )
            await self._emit_comms_event("in", user_id, text)
            response = await self._handler(channel_msg)
            await self.send(channel_id, response)

    async def stop(self):
        self._running = False
        if hasattr(self, "_http"):
            await self._http.aclose()

    async def send(self, channel_id: str, response: ChannelResponse):
        if not response.text:
            return
        try:
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
            await self._http_with_retry(self._http, "POST", "https://slack.com/api/chat.postMessage", json=payload)
            await self._emit_comms_event("out", channel_id, response.text)
        except Exception as e:
            logging.getLogger("feral.channel.slack").error("Slack send error: %s", e)


class WhatsAppChannel(Channel):
    """WhatsApp Cloud API — webhook-based incoming, REST outgoing."""

    @property
    def channel_type(self) -> str:
        return "whatsapp"

    async def start(self):
        self._access_token = self.config.get("access_token", "")
        self._phone_id = self.config.get("phone_number_id", "")
        self._app_secret = self.config.get("app_secret", os.environ.get("FERAL_WHATSAPP_APP_SECRET", ""))
        if not self._access_token or not self._phone_id:
            logger.warning("WhatsApp channel: access_token and phone_number_id required")
            return

        import httpx
        self._running = True
        self._http = httpx.AsyncClient(timeout=10.0)
        logger.info("WhatsApp channel started (webhook mode)")

    async def stop(self):
        self._running = False
        if hasattr(self, "_http") and self._http:
            await self._http.aclose()

    def verify_signature(self, raw_body: bytes, signature: str) -> bool:
        """Verify the X-Hub-Signature-256 header from WhatsApp Cloud API."""
        if not self._app_secret:
            return True
        import hashlib
        import hmac
        expected = "sha256=" + hmac.new(
            self._app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def handle_webhook(self, body: dict) -> Optional[ChannelResponse]:
        """Process an incoming WhatsApp Cloud API webhook."""
        entries = body.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    text = msg.get("text", {}).get("body", "")
                    sender = msg.get("from", "")
                    self._known_chat_ids.add(sender)

                    if text and self._handler:
                        channel_msg = ChannelMessage(
                            channel_type="whatsapp",
                            user_id=sender,
                            text=text,
                            channel_id=self._phone_id,
                        )
                        await self._emit_comms_event("in", sender, text)
                        response = await self._handler(channel_msg)
                        if response and response.text:
                            await self.send_text(sender, response.text)
                        return response
        return None

    async def send_text(self, chat_id: str, text: str, **kwargs) -> dict:
        """Send a text message via WhatsApp Cloud API."""
        wa_logger = logging.getLogger("feral.channel.whatsapp")
        if not self._running or not self._http:
            return {"success": False, "error": "WhatsApp not running"}
        try:
            response = await self._http_with_retry(
                self._http, "POST",
                f"https://graph.facebook.com/v18.0/{self._phone_id}/messages",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "text",
                    "text": {"body": text},
                },
            )
            response.raise_for_status()
            await self._emit_comms_event("out", chat_id, text)
            return {"success": True, "data": response.json()}
        except Exception as e:
            wa_logger.error("WhatsApp send failed: %s", e)
            return {"success": False, "error": str(e)}

    async def send(self, channel_id: str, response: ChannelResponse):
        if not response.text:
            return
        await self.send_text(channel_id, response.text)


class ChannelManager:
    """Manages all messaging channels with proper bidirectional flow."""

    CHANNEL_TYPES = {
        "telegram": TelegramChannel,
        "discord": DiscordChannel,
        "slack": SlackChannel,
        "whatsapp": WhatsAppChannel,
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
        """Send to all known chats across all active channels."""
        for ch in self._channels.values():
            for cid in ch.active_chat_ids:
                await ch.send(cid, response)

    async def send_to_channel(self, channel_type: str, channel_id: str, response: ChannelResponse):
        ch = self._channels.get(channel_type)
        if ch:
            await ch.send(channel_id, response)

    def get_channel(self, channel_type: str) -> Optional[Channel]:
        return self._channels.get(channel_type)

    @property
    def channels(self) -> dict[str, Channel]:
        return self._channels

    @property
    def active_channels(self) -> list[str]:
        return list(self._channels.keys())

    @property
    def stats(self) -> dict:
        channel_details = {}
        for ctype, ch in self._channels.items():
            channel_details[ctype] = {
                "running": ch._running,
                "known_chats": len(ch._known_chat_ids),
            }
        return {
            "active_channels": self.active_channels,
            "channel_count": len(self._channels),
            "details": channel_details,
        }
