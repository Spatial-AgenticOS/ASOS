"""Track A channel-stub contract — signal, voice_call, feishu, zalo, matrix.

Each stub must satisfy four rules:
1. ``channel_type`` returns the canonical string name.
2. ``start()`` with empty config marks the channel as disabled
   (``_connected`` + ``_running`` both False) and does NOT raise.
3. ``send()`` on a disabled stub logs a warning and returns — never
   fakes delivery, never raises.
4. ``resolve_username()`` returns ``None`` by default.

These rules prevent a stub from silently lying about connectivity.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from channels.base import ChannelResponse
from channels.feishu import FeishuChannel
from channels.matrix import MatrixChannel
from channels.signal import SignalChannel
from channels.voice_call import VoiceCallChannel
from channels.zalo import ZaloChannel


pytestmark = pytest.mark.no_auto_feral_home


STUB_CLASSES = [
    ("signal", SignalChannel, "feral.channels.signal"),
    ("voice_call", VoiceCallChannel, "feral.channels.voice_call"),
    ("feishu", FeishuChannel, "feral.channels.feishu"),
    ("zalo", ZaloChannel, "feral.channels.zalo"),
    ("matrix", MatrixChannel, "feral.channels.matrix"),
]


@pytest.mark.parametrize("name,cls,_logger", STUB_CLASSES)
def test_channel_type_identifier(name, cls, _logger):
    ch = cls(config={})
    assert ch.channel_type == name


@pytest.mark.parametrize("name,cls,_logger", STUB_CLASSES)
def test_disabled_without_credentials(name, cls, _logger):
    ch = cls(config={})
    asyncio.run(ch.start())
    assert ch._connected is False, f"{name} falsely claims to be connected"
    assert ch._running is False


@pytest.mark.parametrize("name,cls,logger_name", STUB_CLASSES)
def test_send_logs_stub_noop(name, cls, logger_name, caplog):
    ch = cls(config={})
    with caplog.at_level(logging.WARNING, logger=logger_name):
        asyncio.run(ch.send("test-channel", ChannelResponse(text="hello")))
    # Stub must never raise and must log something that makes it clear
    # the message was dropped.
    matched = [r for r in caplog.records if r.name == logger_name and r.levelno == logging.WARNING]
    assert matched, f"{name} send() produced no warning on a stub noop"


@pytest.mark.parametrize("name,cls,_logger", STUB_CLASSES)
def test_resolve_username_returns_none(name, cls, _logger):
    ch = cls(config={})
    result = asyncio.run(ch.resolve_username("@someone"))
    assert result is None
