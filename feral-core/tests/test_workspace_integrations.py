"""
Tests for FERAL workspace integrations:
Google Drive, Google Contacts, Microsoft 365, and expanded Slack messaging.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Google Drive ──────────────────────────────────────────────────


class TestGoogleDrive:
    def test_init_no_oauth(self):
        from integrations.google_drive import GoogleDriveIntegration

        gd = GoogleDriveIntegration()
        assert gd.connected is False

    @pytest.mark.asyncio
    async def test_unknown_endpoint(self):
        from integrations.google_drive import GoogleDriveIntegration

        gd = GoogleDriveIntegration()
        result = await gd.execute("nonexistent", {})
        assert result["success"] is False
        assert "Unknown" in result["error"]

    @pytest.mark.asyncio
    async def test_list_files_not_connected(self):
        from integrations.google_drive import GoogleDriveIntegration

        gd = GoogleDriveIntegration()
        result = await gd.list_files()
        assert result["success"] is False
        assert "Not connected" in result["error"]

    @pytest.mark.asyncio
    async def test_list_files_mocked(self):
        from integrations.google_drive import GoogleDriveIntegration

        oauth = MagicMock()
        oauth.is_connected.return_value = True
        oauth.get_token = AsyncMock(return_value="tok")
        gd = GoogleDriveIntegration(oauth_manager=oauth)

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"files": [{"id": "f1", "name": "doc.pdf"}]}
        gd._http = AsyncMock()
        gd._http.get.return_value = resp

        result = await gd.list_files()
        assert result["success"] is True
        assert len(result["data"]["files"]) == 1

    @pytest.mark.asyncio
    async def test_search_files_mocked(self):
        from integrations.google_drive import GoogleDriveIntegration

        oauth = MagicMock()
        oauth.is_connected.return_value = True
        oauth.get_token = AsyncMock(return_value="tok")
        gd = GoogleDriveIntegration(oauth_manager=oauth)

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"files": []}
        gd._http = AsyncMock()
        gd._http.get.return_value = resp

        result = await gd.search_files(query="report")
        assert result["success"] is True
        assert result["data"]["query"] == "report"

    @pytest.mark.asyncio
    async def test_create_folder_not_connected(self):
        from integrations.google_drive import GoogleDriveIntegration

        gd = GoogleDriveIntegration()
        result = await gd.create_folder(name="NewFolder")
        assert result["success"] is False


# ── Google Contacts ───────────────────────────────────────────────


class TestGoogleContacts:
    def test_init_no_oauth(self):
        from integrations.google_contacts import GoogleContactsIntegration

        gc = GoogleContactsIntegration()
        assert gc.connected is False

    @pytest.mark.asyncio
    async def test_unknown_endpoint(self):
        from integrations.google_contacts import GoogleContactsIntegration

        gc = GoogleContactsIntegration()
        result = await gc.execute("nonexistent", {})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_search_contacts_not_connected(self):
        from integrations.google_contacts import GoogleContactsIntegration

        gc = GoogleContactsIntegration()
        result = await gc.search_contacts(query="Sarah")
        assert result["success"] is False
        assert "Not connected" in result["error"]

    @pytest.mark.asyncio
    async def test_search_contacts_mocked(self):
        from integrations.google_contacts import GoogleContactsIntegration

        oauth = MagicMock()
        oauth.is_connected.return_value = True
        oauth.get_token = AsyncMock(return_value="tok")
        gc = GoogleContactsIntegration(oauth_manager=oauth)

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "results": [
                {
                    "person": {
                        "resourceName": "people/c123",
                        "names": [{"displayName": "Sarah Connor"}],
                        "emailAddresses": [{"value": "sarah@example.com"}],
                        "phoneNumbers": [{"value": "+15551234567"}],
                    }
                }
            ]
        }
        gc._http = AsyncMock()
        gc._http.get.return_value = resp

        result = await gc.search_contacts(query="Sarah")
        assert result["success"] is True
        contacts = result["data"]["contacts"]
        assert len(contacts) == 1
        assert contacts[0]["name"] == "Sarah Connor"
        assert "sarah@example.com" in contacts[0]["emails"]

    @pytest.mark.asyncio
    async def test_list_contacts_mocked(self):
        from integrations.google_contacts import GoogleContactsIntegration

        oauth = MagicMock()
        oauth.is_connected.return_value = True
        oauth.get_token = AsyncMock(return_value="tok")
        gc = GoogleContactsIntegration(oauth_manager=oauth)

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"connections": [], "totalPeople": 0}
        gc._http = AsyncMock()
        gc._http.get.return_value = resp

        result = await gc.list_contacts()
        assert result["success"] is True
        assert result["data"]["total"] == 0


# ── Microsoft 365 ─────────────────────────────────────────────────


class TestMicrosoft365:
    def test_init_no_oauth(self):
        from integrations.microsoft365 import Microsoft365Integration

        ms = Microsoft365Integration()
        assert ms.connected is False

    @pytest.mark.asyncio
    async def test_unknown_endpoint(self):
        from integrations.microsoft365 import Microsoft365Integration

        ms = Microsoft365Integration()
        result = await ms.execute("nonexistent", {})
        assert result["success"] is False
        assert "Unknown" in result["error"]

    @pytest.mark.asyncio
    async def test_list_mail_not_connected(self):
        from integrations.microsoft365 import Microsoft365Integration

        ms = Microsoft365Integration()
        result = await ms.list_mail()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_list_mail_mocked(self):
        from integrations.microsoft365 import Microsoft365Integration

        oauth = MagicMock()
        oauth.is_connected.return_value = True
        oauth.get_token = AsyncMock(return_value="tok")
        ms = Microsoft365Integration(oauth_manager=oauth)

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "value": [
                {
                    "id": "m1",
                    "subject": "Hello",
                    "from": {"emailAddress": {"address": "bob@ms.com", "name": "Bob"}},
                    "receivedDateTime": "2026-04-10T10:00:00Z",
                    "bodyPreview": "Hi there",
                    "isRead": False,
                }
            ]
        }
        ms._http = AsyncMock()
        ms._http.get.return_value = resp

        result = await ms.list_mail()
        assert result["success"] is True
        assert len(result["data"]["messages"]) == 1
        assert result["data"]["messages"][0]["from"] == "bob@ms.com"

    @pytest.mark.asyncio
    async def test_send_mail_not_connected(self):
        from integrations.microsoft365 import Microsoft365Integration

        ms = Microsoft365Integration()
        result = await ms.send_mail(to="a@b.com", subject="Hi", body="Hello")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_list_events_mocked(self):
        from integrations.microsoft365 import Microsoft365Integration

        oauth = MagicMock()
        oauth.is_connected.return_value = True
        oauth.get_token = AsyncMock(return_value="tok")
        ms = Microsoft365Integration(oauth_manager=oauth)

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"value": []}
        ms._http = AsyncMock()
        ms._http.get.return_value = resp

        result = await ms.list_events()
        assert result["success"] is True
        assert result["data"]["events"] == []

    @pytest.mark.asyncio
    async def test_list_files_onedrive_not_connected(self):
        from integrations.microsoft365 import Microsoft365Integration

        ms = Microsoft365Integration()
        result = await ms.list_files()
        assert result["success"] is False


# ── Slack Expanded Methods ────────────────────────────────────────


class TestSlackExpanded:
    @pytest.mark.asyncio
    async def test_read_channel_history_no_token(self, monkeypatch):
        monkeypatch.delenv("FERAL_SLACK_BOT_TOKEN", raising=False)
        from integrations.messaging import SlackBridge

        slack = SlackBridge()
        result = await slack.read_channel_history(channel="C123")
        assert result["success"] is False
        assert "not configured" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_reply_to_thread_no_token(self, monkeypatch):
        monkeypatch.delenv("FERAL_SLACK_BOT_TOKEN", raising=False)
        from integrations.messaging import SlackBridge

        slack = SlackBridge()
        result = await slack.reply_to_thread(channel="C123", thread_ts="ts", text="hi")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_set_status_no_token(self, monkeypatch):
        monkeypatch.delenv("FERAL_SLACK_BOT_TOKEN", raising=False)
        from integrations.messaging import SlackBridge

        slack = SlackBridge()
        result = await slack.set_status(status_text="Away")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_hub_dispatches_new_slack_endpoints(self, monkeypatch):
        monkeypatch.delenv("FERAL_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("FERAL_SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("FERAL_DISCORD_BOT_TOKEN", raising=False)
        from integrations.messaging import MessagingHub

        hub = MessagingHub()
        for endpoint in ("slack_read_channel_history", "slack_reply_to_thread", "slack_set_status"):
            result = await hub.execute(endpoint, {"channel": "C1", "text": "hi", "thread_ts": "t", "status_text": "x"})
            assert result["success"] is False
