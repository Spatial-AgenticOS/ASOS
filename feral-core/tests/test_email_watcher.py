"""Tests for Email Watcher — MIME parsing, VIP matching, subject filtering, OAuth2 helpers."""
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

import pytest

from integrations.email_watcher import EmailWatcher, IncomingEmail, _format_xoauth2


# ─── Helpers ─────────────────────────────────────────────────────


def _make_plain_email(sender="alice@example.com", subject="Hello", body="Plain text body"):
    msg = MIMEText(body, "plain")
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = "Thu, 16 Apr 2026 12:00:00 +0000"
    msg["Message-ID"] = "<test-plain@example.com>"
    return msg.as_bytes()


def _make_html_email(sender="bob@test.com", subject="HTML News", body_html="<h1>Hello</h1><p>World</p>"):
    msg = MIMEText(body_html, "html")
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = "Thu, 16 Apr 2026 12:00:00 +0000"
    msg["Message-ID"] = "<test-html@example.com>"
    return msg.as_bytes()


def _make_multipart_alternative(plain="Plain version", html="<p>HTML version</p>"):
    msg = MIMEMultipart("alternative")
    msg["From"] = "multi@example.com"
    msg["Subject"] = "Multipart Alt"
    msg["Date"] = "Thu, 16 Apr 2026 12:00:00 +0000"
    msg["Message-ID"] = "<test-multi@example.com>"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg.as_bytes()


def _make_email_with_attachments(
    body="Body with attachment",
    attachments=None,
):
    """Create a multipart/mixed email with file attachments."""
    attachments = attachments or [("report.pdf", b"%PDF-fake"), ("data.csv", b"a,b\n1,2")]
    msg = MIMEMultipart("mixed")
    msg["From"] = "attach@example.com"
    msg["Subject"] = "Report Attached"
    msg["Date"] = "Thu, 16 Apr 2026 12:00:00 +0000"
    msg["Message-ID"] = "<test-attach@example.com>"
    msg.attach(MIMEText(body, "plain"))

    for fname, content in attachments:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=fname)
        msg.attach(part)

    return msg.as_bytes()


# ─── MIME parsing ────────────────────────────────────────────────


class TestMIMEParsing:
    def test_plain_text_body(self):
        raw = _make_plain_email(body="Hello from plain text")
        result = EmailWatcher._parse_message(raw)
        assert result is not None
        assert result.sender == "alice@example.com"
        assert result.subject == "Hello"
        assert "Hello from plain text" in result.body
        assert result.has_attachments is False

    def test_html_body(self):
        raw = _make_html_email(body_html="<h1>Title</h1><p>Paragraph text</p>")
        result = EmailWatcher._parse_message(raw)
        assert result is not None
        assert "Title" in result.body
        assert "Paragraph text" in result.body
        assert "<h1>" not in result.body

    def test_multipart_alternative_prefers_plain(self):
        raw = _make_multipart_alternative(
            plain="The plain version",
            html="<p>The HTML version</p>",
        )
        result = EmailWatcher._parse_message(raw)
        assert result is not None
        assert "The plain version" in result.body

    def test_attachments_detected(self):
        raw = _make_email_with_attachments(
            body="See attached",
            attachments=[("report.pdf", b"fake-pdf"), ("notes.txt", b"hello")],
        )
        result = EmailWatcher._parse_message(raw)
        assert result is not None
        assert result.has_attachments is True
        assert "report.pdf" in result.attachment_names
        assert "notes.txt" in result.attachment_names
        assert result.subject == "Report Attached"
        assert "See attached" in result.body

    def test_no_attachments(self):
        raw = _make_plain_email(body="no files here")
        result = EmailWatcher._parse_message(raw)
        assert result is not None
        assert result.has_attachments is False
        assert result.attachment_names == []


# ─── _extract_body standalone ────────────────────────────────────


class TestExtractBody:
    def test_plain_message(self):
        msg = email.message_from_bytes(_make_plain_email(body="test body"))
        body = EmailWatcher._extract_body(msg)
        assert body == "test body"

    def test_html_strips_tags(self):
        msg = email.message_from_bytes(
            _make_html_email(body_html="<div><b>Bold</b> text</div>")
        )
        body = EmailWatcher._extract_body(msg)
        assert "Bold" in body
        assert "<div>" not in body

    def test_multipart_extracts_plain(self):
        msg = email.message_from_bytes(
            _make_multipart_alternative(plain="plain wins", html="<p>html</p>")
        )
        body = EmailWatcher._extract_body(msg)
        assert body == "plain wins"


# ─── VIP sender matching ────────────────────────────────────────


class TestVIPSenderMatching:
    def test_vip_sender_match(self, monkeypatch):
        monkeypatch.setenv("FERAL_EMAIL_VIP_SENDERS", "boss@corp.com,cto@corp.com")
        monkeypatch.setenv("FERAL_IMAP_HOST", "imap.test")
        monkeypatch.setenv("FERAL_IMAP_USER", "me")
        monkeypatch.setenv("FERAL_IMAP_PASS", "pass")
        monkeypatch.delenv("FERAL_EMAIL_FILTER_SUBJECTS", raising=False)
        monkeypatch.delenv("FERAL_IMAP_OAUTH_TOKEN", raising=False)
        watcher = EmailWatcher()
        assert "boss@corp.com" in watcher._vip_senders
        assert "cto@corp.com" in watcher._vip_senders

    def test_vip_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FERAL_EMAIL_VIP_SENDERS", "Boss@Corp.com")
        monkeypatch.delenv("FERAL_EMAIL_FILTER_SUBJECTS", raising=False)
        monkeypatch.delenv("FERAL_IMAP_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("FERAL_IMAP_HOST", "h")
        monkeypatch.setenv("FERAL_IMAP_USER", "u")
        monkeypatch.setenv("FERAL_IMAP_PASS", "p")
        watcher = EmailWatcher()
        sender = "boss@corp.com"
        assert any(v.lower() in sender.lower() for v in watcher._vip_senders)

    def test_empty_vip_list(self, monkeypatch):
        monkeypatch.setenv("FERAL_EMAIL_VIP_SENDERS", "")
        monkeypatch.delenv("FERAL_EMAIL_FILTER_SUBJECTS", raising=False)
        monkeypatch.delenv("FERAL_IMAP_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("FERAL_IMAP_HOST", "h")
        monkeypatch.setenv("FERAL_IMAP_USER", "u")
        monkeypatch.setenv("FERAL_IMAP_PASS", "p")
        watcher = EmailWatcher()
        assert watcher._vip_senders == []


# ─── Subject filter ──────────────────────────────────────────────


class TestSubjectFilter:
    def test_subject_filter_from_env(self, monkeypatch):
        monkeypatch.setenv("FERAL_EMAIL_FILTER_SUBJECTS", "urgent,invoice,alert")
        monkeypatch.setenv("FERAL_EMAIL_VIP_SENDERS", "")
        monkeypatch.delenv("FERAL_IMAP_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("FERAL_IMAP_HOST", "h")
        monkeypatch.setenv("FERAL_IMAP_USER", "u")
        monkeypatch.setenv("FERAL_IMAP_PASS", "p")
        watcher = EmailWatcher()
        assert watcher._filter_subjects == ["urgent", "invoice", "alert"]

    def test_subject_match_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FERAL_EMAIL_FILTER_SUBJECTS", "URGENT")
        monkeypatch.setenv("FERAL_EMAIL_VIP_SENDERS", "")
        monkeypatch.delenv("FERAL_IMAP_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("FERAL_IMAP_HOST", "h")
        monkeypatch.setenv("FERAL_IMAP_USER", "u")
        monkeypatch.setenv("FERAL_IMAP_PASS", "p")
        watcher = EmailWatcher()
        subject = "urgent: server down"
        assert any(f.lower() in subject.lower() for f in watcher._filter_subjects)


# ─── OAuth2 ──────────────────────────────────────────────────────


class TestOAuth2:
    def test_xoauth2_format_string(self):
        result = _format_xoauth2("user@gmail.com", "ya29.FAKE_TOKEN")
        import base64
        decoded = base64.b64decode(result).decode()
        assert "user=user@gmail.com" in decoded
        assert "auth=Bearer ya29.FAKE_TOKEN" in decoded

    def test_configured_with_oauth_token(self, monkeypatch):
        monkeypatch.setenv("FERAL_IMAP_HOST", "imap.gmail.com")
        monkeypatch.setenv("FERAL_IMAP_USER", "me@gmail.com")
        monkeypatch.delenv("FERAL_IMAP_PASS", raising=False)
        monkeypatch.setenv("FERAL_IMAP_OAUTH_TOKEN", "ya29.token")
        monkeypatch.setenv("FERAL_EMAIL_VIP_SENDERS", "")
        monkeypatch.setenv("FERAL_EMAIL_FILTER_SUBJECTS", "")
        watcher = EmailWatcher()
        assert watcher.configured is True

    def test_not_configured_without_any_auth(self, monkeypatch):
        monkeypatch.setenv("FERAL_IMAP_HOST", "imap.test")
        monkeypatch.setenv("FERAL_IMAP_USER", "user")
        monkeypatch.delenv("FERAL_IMAP_PASS", raising=False)
        monkeypatch.delenv("FERAL_IMAP_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("FERAL_EMAIL_VIP_SENDERS", "")
        monkeypatch.setenv("FERAL_EMAIL_FILTER_SUBJECTS", "")
        watcher = EmailWatcher()
        assert watcher.configured is False
