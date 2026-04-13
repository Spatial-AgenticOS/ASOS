"""
Tests for channels/push.py — PushChannel device registration,
FCM/APNs send paths, and token management with mocked HTTP.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from channels.push import PushChannel, _db_path


@pytest.fixture
def push(tmp_path, monkeypatch):
    monkeypatch.setattr("channels.push._db_path", lambda: tmp_path / "tokens.db")
    monkeypatch.delenv("FERAL_FIREBASE_CREDENTIALS", raising=False)
    monkeypatch.delenv("FERAL_APNS_KEY_PATH", raising=False)
    ch = PushChannel()
    yield ch
    ch.close()


class TestPushChannelInit:
    def test_init_without_config(self, push):
        assert push._firebase_project_id is None
        assert push._apns_token is None

    def test_init_with_firebase(self, tmp_path, monkeypatch):
        creds = tmp_path / "sa.json"
        creds.write_text('{"project_id": "my-proj"}')
        monkeypatch.setenv("FERAL_FIREBASE_CREDENTIALS", str(creds))
        monkeypatch.delenv("FERAL_APNS_KEY_PATH", raising=False)
        monkeypatch.setattr("channels.push._db_path", lambda: tmp_path / "t.db")
        ch = PushChannel()
        assert ch._firebase_project_id == "my-proj"
        ch.close()


class TestDeviceRegistration:
    def test_register_and_get(self, push):
        push.register_device("u1", "tok-abc", "fcm")
        tokens = push.get_tokens("u1")
        assert len(tokens) == 1
        assert tokens[0]["token"] == "tok-abc"
        assert tokens[0]["platform"] == "fcm"

    def test_register_multiple_platforms(self, push):
        push.register_device("u1", "fcm-tok", "fcm")
        push.register_device("u1", "apns-tok", "apns")
        tokens = push.get_tokens("u1")
        assert len(tokens) == 2

    def test_upsert_on_duplicate(self, push):
        push.register_device("u1", "tok", "fcm")
        push.register_device("u1", "tok", "fcm")
        tokens = push.get_tokens("u1")
        assert len(tokens) == 1

    def test_get_tokens_empty(self, push):
        assert push.get_tokens("nonexistent") == []


class TestFCMSend:
    def test_fcm_no_project_returns_error(self, push):
        result = push._send_fcm("tok", "Title", "Body", None)
        assert result["success"] is False
        assert "not configured" in result["error"]

    def test_fcm_no_bearer_returns_error(self, push):
        push._firebase_project_id = "test-proj"
        with patch.object(push, "_get_fcm_bearer_token", return_value=None):
            result = push._send_fcm("tok", "T", "B", None)
        assert result["success"] is False
        assert "bearer" in result["error"].lower()

    def test_fcm_success_mocked(self, push):
        push._firebase_project_id = "test-proj"
        mock_resp = MagicMock(status_code=200, text="ok")
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client
        with patch.object(push, "_get_fcm_bearer_token", return_value="bearer-tok"):
            with patch.dict("sys.modules", {"httpx": mock_httpx}):
                result = push._send_fcm("device-tok", "Hey", "Body", {"key": "val"})
        assert result["success"] is True
        assert result["platform"] == "fcm"


class TestAPNsSend:
    def test_apns_no_key_returns_error(self, push):
        result = push._send_apns("tok", "T", "B", None)
        assert result["success"] is False
        assert "not configured" in result["error"]

    def test_apns_no_bearer_returns_error(self, push, tmp_path, monkeypatch):
        key_file = tmp_path / "key.p8"
        key_file.write_text("fake-key")
        push._apns_key_path = str(key_file)
        with patch.object(push, "_get_apns_token", return_value=None):
            result = push._send_apns("tok", "T", "B", None)
        assert result["success"] is False

    def test_apns_sandbox_host(self, push, tmp_path):
        key_file = tmp_path / "key.p8"
        key_file.write_text("fake")
        push._apns_key_path = str(key_file)
        push._apns_environment = "sandbox"
        mock_resp = MagicMock(status_code=200, text="ok")
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client
        with patch.object(push, "_get_apns_token", return_value="jwt-tok"):
            with patch.dict("sys.modules", {"httpx": mock_httpx}):
                result = push._send_apns("device-tok", "Hey", "Body", None)
        assert result["success"] is True
        assert result["platform"] == "apns"


class TestSendPushRouting:
    def test_routes_to_fcm_by_default(self, push):
        with patch.object(push, "_send_fcm", return_value={"success": True}) as mock_fcm:
            push.send_push("tok", "T", "B", platform="fcm")
        mock_fcm.assert_called_once()

    def test_routes_to_apns(self, push):
        with patch.object(push, "_send_apns", return_value={"success": True}) as mock_apns:
            push.send_push("tok", "T", "B", platform="apns")
        mock_apns.assert_called_once()

    def test_broadcast_no_tokens(self, push):
        results = push.broadcast("no_user", "T", "B")
        assert results[0]["success"] is False
