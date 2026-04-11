"""
Tests for channel message types, Telegram/Slack send paths, and ``ChannelManager``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from channels.base import (
    ChannelManager,
    ChannelMessage,
    ChannelResponse,
    SlackChannel,
    TelegramChannel,
)


class TestChannelMessage:
    def test_channel_message_required_fields(self) -> None:
        msg = ChannelMessage(
            channel_type="telegram",
            channel_id="ch1",
            user_id="u1",
        )
        assert msg.channel_type == "telegram"
        assert msg.channel_id == "ch1"
        assert msg.user_id == "u1"
        assert msg.text == ""
        assert msg.metadata == {}


class TestChannelResponse:
    def test_channel_response_with_text(self) -> None:
        resp = ChannelResponse(text="Hello world")
        assert resp.text == "Hello world"
        assert resp.sdui is None


class TestTelegramChannel:
    def test_init_stores_bot_token_in_config(self) -> None:
        ch = TelegramChannel({"bot_token": "secret-token-123", "enabled": True})
        assert ch.config.get("bot_token") == "secret-token-123"

    @pytest.mark.asyncio
    async def test_send_posts_to_telegram_api(self) -> None:
        ch = TelegramChannel({"bot_token": "tok"})
        ch._base_url = "https://api.telegram.org/bottok"
        mock_http = AsyncMock()
        ch._http = mock_http

        await ch.send("999", ChannelResponse(text="hi there"))

        mock_http.post.assert_awaited_once()
        args, kwargs = mock_http.post.call_args
        assert "/sendMessage" in args[0]
        assert kwargs["json"]["chat_id"] == "999"
        assert kwargs["json"]["text"] == "hi there"


class TestSlackChannel:
    @pytest.mark.asyncio
    async def test_send_posts_to_slack_web_api(self) -> None:
        ch = SlackChannel({"bot_token": "xoxb-test"})
        mock_http = AsyncMock()
        ch._http = mock_http

        await ch.send("C0123", ChannelResponse(text="slack msg"))

        mock_http.post.assert_awaited_once()
        args, kwargs = mock_http.post.call_args
        assert "chat.postMessage" in args[0]
        assert kwargs["json"]["channel"] == "C0123"
        assert kwargs["json"]["text"] == "slack msg"


class TestChannelManager:
    @pytest.mark.asyncio
    async def test_register_and_get_channel_by_name(self) -> None:
        mgr = ChannelManager()

        async def noop_start(self) -> None:
            self._running = True
            import httpx

            self._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

        with patch.object(TelegramChannel, "start", noop_start):
            await mgr.start_channel("telegram", {"bot_token": "t"})

        got = mgr.get_channel("telegram")
        assert got is not None
        assert got.channel_type == "telegram"
        assert "telegram" in mgr.active_channels

        await mgr.stop_all()
