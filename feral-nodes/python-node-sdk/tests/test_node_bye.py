"""Verify the SDK sends node_bye on graceful close."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from feral_node_sdk import FeralNode


@pytest.fixture
def node():
    return FeralNode(
        node_id="bye-test-node",
        name="Bye Test",
        node_type="sensor",
        capabilities=["heart_rate"],
        brain_url="ws://localhost:9999/v1/node",
        api_key="test-key",
    )


def test_close_sends_node_bye(node):
    """FeralNode.close() must send a node_bye frame before closing WS."""
    sent_frames: list[str] = []

    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock(side_effect=lambda data: sent_frames.append(data))
    mock_ws.close = AsyncMock()
    node._ws = mock_ws

    asyncio.run(node.close(reason="test-shutdown"))

    bye_frames = [
        json.loads(f) for f in sent_frames
        if "node_bye" in f
    ]
    assert len(bye_frames) == 1
    frame = bye_frames[0]
    assert frame["type"] == "node_bye"
    assert frame["payload"]["reason"] == "test-shutdown"


def test_close_tolerates_ws_error(node):
    """close() must not raise even if the WS send fails."""
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock(side_effect=ConnectionError("already closed"))
    mock_ws.close = AsyncMock()
    node._ws = mock_ws

    asyncio.run(node.close())
