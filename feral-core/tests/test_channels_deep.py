"""
Deeper channel tests — Telegram polling/callbacks, Discord/Slack WebSocket paths,
WhatsApp webhooks, and ChannelManager orchestration (fully mocked I/O).
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from channels.base import (
    ChannelManager,
    ChannelMessage,
    ChannelResponse,
    DiscordChannel,
    SlackChannel,
    TelegramChannel,
    WhatsAppChannel,
)

pytestmark = pytest.mark.no_auto_feral_home


# ── Telegram — httpx mocks ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_callback_query_invokes_handler_and_answers_callback():
    mock_http = MagicMock()
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()
    mock_http.get = AsyncMock(return_value=MagicMock(json=lambda: {"result": []}))

    handler = AsyncMock(return_value=ChannelResponse(text="picked"))
    with patch("httpx.AsyncClient", return_value=mock_http):
        ch = TelegramChannel({"bot_token": "tok", "enabled": True})
        ch.set_handler(handler)
        await ch.start()

        cb = {
            "id": "cbq-1",
            "data": "action:ok",
            "from": {"id": 99},
            "message": {"chat": {"id": 555}},
        }
        await ch._handle_callback(cb)
        await ch.stop()

    handler.assert_awaited_once()
    cm = handler.await_args.args[0]
    assert isinstance(cm, ChannelMessage)
    assert cm.metadata.get("callback") is True
    assert cm.text == "action:ok"
    answer_calls = [c for c in mock_http.post.call_args_list if "answerCallbackQuery" in str(c)]
    assert answer_calls


@pytest.mark.asyncio
async def test_telegram_photo_message_downloads_via_httpx_and_passes_image_b64():
    mock_http = MagicMock()
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()
    file_get = MagicMock()
    file_get.json = lambda: {"result": {"file_path": "photos/x.jpg"}}
    bin_get = MagicMock()
    bin_get.content = b"\xff\xd8\xff"
    mock_http.get = AsyncMock(side_effect=[file_get, bin_get])

    handler = AsyncMock(return_value=ChannelResponse(text="got pic"))
    ch = TelegramChannel({"bot_token": "tok", "enabled": True})
    ch._http = mock_http
    ch._base_url = "https://api.telegram.org/bot/tok"
    ch.set_handler(handler)

    msg = {
        "chat": {"id": 1},
        "from": {"id": 2, "username": "cam"},
        "photo": [{"file_id": "ignored"}, {"file_id": "fid-final"}],
    }
    await ch._handle_message(msg)

    handler.assert_awaited_once()
    out = handler.await_args.args[0]
    assert out.image_b64
    assert mock_http.get.await_count >= 2


@pytest.mark.asyncio
async def test_telegram_poll_loop_one_update_then_stops():
    update = {
        "update_id": 10,
        "message": {
            "chat": {"id": 77},
            "from": {"id": 3, "first_name": "Ann"},
            "text": "poll hi",
        },
    }
    mock_http = MagicMock()
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()
    ch_box: list[TelegramChannel | None] = [None]
    poll_n = [0]

    async def get_side_effect(*args, **kwargs):
        poll_n[0] += 1
        if poll_n[0] == 1:
            return MagicMock(json=lambda: {"result": [update]})
        if ch_box[0] is not None:
            ch_box[0]._running = False
        return MagicMock(json=lambda: {"result": []})

    mock_http.get = AsyncMock(side_effect=get_side_effect)
    handler = AsyncMock(return_value=ChannelResponse(text="r"))

    with patch("httpx.AsyncClient", return_value=mock_http):
        ch = TelegramChannel({"bot_token": "tok", "enabled": True})
        ch_box[0] = ch
        ch.set_handler(handler)
        await ch.start()
        await asyncio.sleep(0.08)
        await ch.stop()

    handler.assert_called()


# ── Discord — websockets + httpx ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_gateway_connect_delivers_message_create_to_handler():
    hello_raw = json.dumps({"op": 10, "d": {"heartbeat_interval": 999999000}})
    msg_raw = json.dumps(
        {
            "t": "MESSAGE_CREATE",
            "d": {
                "channel_id": "CH-1",
                "content": "gateway hi",
                "author": {"id": "a1", "username": "bob", "bot": False},
            },
        }
    )

    class FakeWS:
        def __init__(self):
            self.send = AsyncMock()

        async def recv(self):
            return hello_raw

        def __aiter__(self):
            self._done = False
            return self

        async def __anext__(self):
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return msg_raw

    fake_ws = FakeWS()

    @asynccontextmanager
    async def fake_connect(*_a, **_kw):
        yield fake_ws

    gateway_resp = MagicMock()
    gateway_resp.json = lambda: {"url": "wss://discord.test/gateway"}

    mock_http = MagicMock()
    mock_http.get = AsyncMock(
        side_effect=[
            gateway_resp,
        ]
    )
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()

    handler = AsyncMock(return_value=ChannelResponse(text="discord reply"))

    with patch("httpx.AsyncClient", return_value=mock_http), patch(
        "websockets.connect", fake_connect,
    ):
        ch = DiscordChannel({"bot_token": "DISC.TOKEN", "enabled": True})
        ch.set_handler(handler)
        await ch.start()
        await asyncio.sleep(0.15)
        await ch.stop()

    handler.assert_called()
    args0 = handler.call_args[0][0]
    assert isinstance(args0, ChannelMessage)
    assert args0.channel_id == "CH-1"
    assert args0.text == "gateway hi"


@pytest.mark.asyncio
async def test_discord_handle_message_skips_bot_authors():
    ch = DiscordChannel({"bot_token": "t"})
    handler = AsyncMock(return_value=ChannelResponse(text="x"))
    ch.set_handler(handler)
    await ch._handle_discord_message(
        {
            "channel_id": "c",
            "author": {"id": "1", "username": "botty", "bot": True},
            "content": "ignored",
        },
    )
    handler.assert_not_called()


# ── Slack — Socket Mode websockets ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_slack_socket_mode_events_api_acknowledges_and_handles_message():
    ev = {
        "type": "events_api",
        "envelope_id": "env-42",
        "payload": {
            "event": {
                "type": "message",
                "channel": "C900",
                "user": "U12",
                "text": "socket hi",
            },
        },
    }
    raw = json.dumps(ev)

    class FakeSlackWS:
        def __init__(self):
            self.send = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __aiter__(self):
            self._gone = False
            return self

        async def __anext__(self):
            if self._gone:
                raise StopAsyncIteration
            self._gone = True
            return raw

    fake_ws = FakeSlackWS()
    fake_connect = AsyncMock(return_value=fake_ws)

    socket_client = MagicMock()
    socket_client.post = AsyncMock(
        return_value=MagicMock(json=lambda: {"url": "wss://slack.test/socket"}),
    )
    socket_cm = MagicMock()
    socket_cm.__aenter__ = AsyncMock(return_value=socket_client)
    socket_cm.__aexit__ = AsyncMock(return_value=None)

    main_http = MagicMock()
    main_http.post = AsyncMock()
    main_http.aclose = AsyncMock()

    handler = AsyncMock(return_value=ChannelResponse(text="slack out"))

    with patch("httpx.AsyncClient", side_effect=[main_http, socket_cm]), patch(
        "websockets.connect", fake_connect,
    ):
        ch = SlackChannel(
            {"bot_token": "xoxb-test", "app_token": "xapp-test", "enabled": True},
        )
        ch.set_handler(handler)
        await ch.start()
        await asyncio.sleep(0.12)
        ch._running = False
        await ch.stop()

    handler.assert_called()
    cm = handler.call_args[0][0]
    assert cm.channel_id == "C900"
    assert cm.text == "socket hi"
    fake_ws.send.assert_called()
    ack = json.loads(fake_ws.send.call_args[0][0])
    assert ack.get("envelope_id") == "env-42"


# ── WhatsApp ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_skips_when_no_text_even_if_handler_set():
    ch = WhatsAppChannel({"access_token": "t", "phone_number_id": "p", "enabled": True})
    ch._running = True
    ch._phone_id = "p"
    ch._http = MagicMock()
    ch._http.post = AsyncMock()
    h = AsyncMock(return_value=ChannelResponse(text="nope"))
    ch.set_handler(h)
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "+1", "text": {}},
                            ]
                        }
                    }
                ]
            }
        ]
    }
    assert await ch.handle_webhook(body) is None
    h.assert_not_called()


@pytest.mark.asyncio
async def test_whatsapp_handle_webhook_returns_first_response_when_multiple_messages():
    ch = WhatsAppChannel({"access_token": "t", "phone_number_id": "p", "enabled": True})
    ch._running = True
    ch._phone_id = "p"
    ch._http = MagicMock()
    ch._http.post = AsyncMock()
    calls = []

    async def counting_handler(msg: ChannelMessage):
        calls.append(msg.text)
        return ChannelResponse(text=f"ack-{len(calls)}")

    ch.set_handler(counting_handler)
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "111", "text": {"body": "first"}},
                                {"from": "222", "text": {"body": "second"}},
                            ]
                        }
                    }
                ]
            }
        ]
    }
    out = await ch.handle_webhook(body)
    assert out is not None
    assert out.text == "ack-1"
    assert calls == ["first"]


# ── ChannelManager ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_manager_set_handler_before_start_propagates():
    mgr = ChannelManager()
    h = AsyncMock(return_value=ChannelResponse(text="early"))
    mgr.set_handler(h)
    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=MagicMock(json=lambda: {"result": []}))
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()
    with patch("httpx.AsyncClient", return_value=mock_http):
        await mgr.start_channel("telegram", {"bot_token": "t"})
    tg = mgr.get_channel("telegram")
    assert tg is not None
    assert tg._handler is h
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_stats_reflects_multiple_channels():
    mgr = ChannelManager()
    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=MagicMock(json=lambda: {"result": []}))
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()
    with patch("httpx.AsyncClient", return_value=mock_http):
        await mgr.start_channel("telegram", {"bot_token": "a"})
    wa = WhatsAppChannel({"access_token": "x", "phone_number_id": "y", "enabled": True})
    wa._running = True
    wa._known_chat_ids.add("p1")
    mgr._channels["whatsapp"] = wa

    s = mgr.stats
    assert s["channel_count"] == 2
    assert set(s["active_channels"]) == {"telegram", "whatsapp"}
    assert s["details"]["telegram"]["running"] is True
    assert s["details"]["whatsapp"]["known_chats"] == 1
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_broadcast_and_send_across_mixed_channels():
    mgr = ChannelManager()
    mock_t = MagicMock()
    mock_t.post = AsyncMock()
    mock_t.aclose = AsyncMock(return_value=None)
    mock_t.get = AsyncMock(return_value=MagicMock(json=lambda: {"result": []}))

    tg = TelegramChannel({"bot_token": "z"})
    tg._http = mock_t
    tg._base_url = "https://api.telegram.org/bot/z"
    tg._running = True
    tg._known_chat_ids.add("10")

    mock_s = MagicMock()
    mock_s.post = AsyncMock()
    mock_s.aclose = AsyncMock(return_value=None)
    slack = SlackChannel({"bot_token": "xoxb"})
    slack._http = mock_s
    slack._running = True
    slack._known_chat_ids.add("C55")

    mgr._channels["telegram"] = tg
    mgr._channels["slack"] = slack

    await mgr.broadcast(ChannelResponse(text="all hands"))
    assert mock_t.post.called
    assert mock_s.post.called

    mock_t.post.reset_mock()
    await mgr.send_to_channel("telegram", "10", ChannelResponse(text="dm"))
    mock_t.post.assert_called_once()
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_set_handler_updates_all_existing_channels():
    mgr = ChannelManager()
    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=MagicMock(json=lambda: {"result": []}))
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()
    h1 = AsyncMock(return_value=ChannelResponse(text="1"))
    h2 = AsyncMock(return_value=ChannelResponse(text="2"))
    with patch("httpx.AsyncClient", return_value=mock_http):
        await mgr.start_channel("telegram", {"bot_token": "t"})
        mgr.set_handler(h1)
        assert mgr.get_channel("telegram")._handler is h1
        mgr.set_handler(h2)
    assert mgr.get_channel("telegram")._handler is h2
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_stop_all_clears_channels():
    mgr = ChannelManager()
    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=MagicMock(json=lambda: {"result": []}))
    mock_http.post = AsyncMock()
    mock_http.aclose = AsyncMock()
    with patch("httpx.AsyncClient", return_value=mock_http):
        await mgr.start_channel("telegram", {"bot_token": "t"})
    await mgr.stop_all()
    assert mgr.active_channels == []
    assert mgr.stats["channel_count"] == 0
