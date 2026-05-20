"""Conversation route coverage for v2 chat rehydration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def conversations_client():
    mock = MagicMock()
    mock.orchestrator = MagicMock()
    mock.memory = MagicMock()
    mock.memory.conversation_get = AsyncMock()
    mock.memory.conversation_list = AsyncMock()
    mock.memory.conversation_save = AsyncMock()
    mock.memory.conversation_delete = AsyncMock()
    mock.memory.snapshot_session = AsyncMock()
    mock.memory.list_snapshots = AsyncMock()
    mock.memory.get_snapshot = AsyncMock()
    with patch("api.state.state", mock), patch("api.routes.conversations.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), mock


def test_active_thread_returns_requested_conversation(conversations_client):
    client, mock = conversations_client
    mock.memory.conversation_get.return_value = {
        "id": "thread-1",
        "title": "Saved",
        "messages": [{"role": "user", "content": "hello"}],
    }

    r = client.get("/api/conversations/active/thread?conversation_id=thread-1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "thread-1"
    assert body["messages"][0]["content"] == "hello"


def test_active_thread_falls_back_to_most_recent(conversations_client):
    client, mock = conversations_client
    mock.memory.conversation_get.side_effect = [None, {"id": "recent-1", "title": "Recent", "messages": []}]
    mock.memory.conversation_list.return_value = [{"id": "recent-1"}]

    r = client.get("/api/conversations/active/thread?conversation_id=missing")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "recent-1"
    mock.memory.conversation_list.assert_called_once()


def test_active_thread_creates_new_when_none_exist(conversations_client):
    client, mock = conversations_client
    mock.memory.conversation_get.return_value = None
    mock.memory.conversation_list.return_value = []
    mock.memory.conversation_save.return_value = {
        "id": "thread-new",
        "title": "New conversation",
        "message_count": 0,
        "updated_at": 123.0,
    }

    r = client.get("/api/conversations/active/thread")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "thread-new"
    assert body["messages"] == []
