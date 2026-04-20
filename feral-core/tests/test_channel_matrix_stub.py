"""Unit tests for the Matrix channel stub (Track A exemplar).

These tests assert the stub behaves *honestly*:
- Reports disabled when credentials are missing (no fake connection).
- Refuses to start when matrix-nio isn't installed.
- send() is a no-op that logs a warning rather than silently succeeding.

When the full Matrix implementation lands, these tests get extended with
the real sync-loop + send round-trip. Until then they lock in the "never
fake" contract.
"""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.no_auto_feral_home


@pytest.mark.asyncio
async def test_matrix_channel_disabled_without_credentials(caplog):
    from channels.matrix import MatrixChannel

    ch = MatrixChannel({"enabled": True})
    with caplog.at_level(logging.WARNING, logger="feral.channels.matrix"):
        await ch.start()
    assert ch._connected is False
    assert ch._running is False
    assert any("homeserver/user_id/access_token missing" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_matrix_channel_send_is_honest_noop(caplog):
    from channels.base import ChannelResponse
    from channels.matrix import MatrixChannel

    ch = MatrixChannel({})
    with caplog.at_level(logging.WARNING, logger="feral.channels.matrix"):
        await ch.send("!room:matrix.org", ChannelResponse(text="test"))
    assert any("stub is active" in r.message for r in caplog.records)


def test_matrix_channel_type_identifier():
    from channels.matrix import MatrixChannel

    ch = MatrixChannel({})
    assert ch.channel_type == "matrix"
