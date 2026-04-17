"""FERAL Email Watcher — monitors inbox via IMAP IDLE for real-time email processing."""
import asyncio
import email
import imaplib
import logging
import os
import re
import time
from dataclasses import dataclass
from email.header import decode_header
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("feral.integrations.email_watcher")


@dataclass
class IncomingEmail:
    sender: str
    subject: str
    body: str
    date: str
    message_id: str
    has_attachments: bool


class EmailWatcher:
    """Watches an IMAP inbox for new emails and routes them to the orchestrator."""

    def __init__(self, on_email: Optional[Callable[[IncomingEmail], Awaitable]] = None):
        self._imap_host = os.getenv("FERAL_IMAP_HOST", "")
        self._imap_port = int(os.getenv("FERAL_IMAP_PORT", "993"))
        self._imap_user = os.getenv("FERAL_IMAP_USER", "")
        self._imap_pass = os.getenv("FERAL_IMAP_PASS", "")
        self._on_email = on_email
        self._running = False
        self._mail: Optional[imaplib.IMAP4_SSL] = None
        self._processed_count = 0
        self._vip_senders = [
            s.strip()
            for s in os.getenv("FERAL_EMAIL_VIP_SENDERS", "").split(",")
            if s.strip()
        ]
        self._filter_subjects = [
            s.strip()
            for s in os.getenv("FERAL_EMAIL_FILTER_SUBJECTS", "").split(",")
            if s.strip()
        ]

    @property
    def configured(self) -> bool:
        return bool(self._imap_host and self._imap_user and self._imap_pass)

    async def start(self) -> bool:
        if not self.configured:
            logger.info(
                "Email watcher: not configured (set FERAL_IMAP_HOST, FERAL_IMAP_USER, FERAL_IMAP_PASS)"
            )
            return False
        self._running = True
        asyncio.create_task(self._watch_loop())
        logger.info("Email watcher started: %s@%s", self._imap_user, self._imap_host)
        return True

    async def stop(self):
        self._running = False
        if self._mail:
            try:
                self._mail.logout()
            except Exception:
                pass

    async def _watch_loop(self):
        while self._running:
            try:
                await asyncio.to_thread(self._connect_and_idle)
            except Exception as e:
                if self._running:
                    logger.warning("Email watcher error: %s — reconnecting in 30s", e)
                    await asyncio.sleep(30)

    def _connect_and_idle(self):
        self._mail = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
        self._mail.login(self._imap_user, self._imap_pass)
        self._mail.select("INBOX")

        while self._running:
            status, data = self._mail.search(None, "UNSEEN")
            if status == "OK" and data[0]:
                msg_ids = data[0].split()
                for msg_id in msg_ids[-5:]:
                    self._process_message(msg_id)

            # IDLE wait (fallback polling if IDLE is unsupported)
            try:
                self._mail.send(b"a IDLE\r\n")
                self._mail.readline()
                self._mail.send(b"DONE\r\n")
                self._mail.readline()
            except Exception:
                time.sleep(30)

    def _process_message(self, msg_id: bytes):
        try:
            status, data = self._mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                return

            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            sender = self._decode_header(msg.get("From", ""))
            subject = self._decode_header(msg.get("Subject", ""))
            date = msg.get("Date", "")
            message_id = msg.get("Message-ID", "")

            if self._vip_senders and not any(
                vip.lower() in sender.lower() for vip in self._vip_senders
            ):
                if self._filter_subjects and not any(
                    f.lower() in subject.lower() for f in self._filter_subjects
                ):
                    return

            body = self._extract_body(msg)
            has_attachments = any(
                part.get_content_disposition() == "attachment" for part in msg.walk()
            )

            incoming = IncomingEmail(
                sender=sender,
                subject=subject,
                body=body[:5000],
                date=date,
                message_id=message_id,
                has_attachments=has_attachments,
            )

            self._processed_count += 1

            is_vip = any(vip.lower() in sender.lower() for vip in self._vip_senders) if self._vip_senders else False

            try:
                from api.state import state
                if state.orchestrator:
                    loop = asyncio.get_event_loop()
                    for sid in list(state.sessions.keys()):
                        loop.call_soon_threadsafe(
                            asyncio.create_task,
                            state.orchestrator._emit_brain_event(sid, "email_received", {
                                "from": sender, "subject": subject, "vip": is_vip,
                            }),
                        )
            except Exception:
                pass

            if self._on_email:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(asyncio.create_task, self._on_email(incoming))
        except Exception as e:
            logger.warning("Failed to process email %s: %s", msg_id, e)

    @staticmethod
    def _decode_header(value: str) -> str:
        parts = decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(str(part))
        return " ".join(decoded)

    @staticmethod
    def _extract_body(msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="replace")
                elif ctype == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        text = payload.decode(errors="replace")
                        text = re.sub(r"<[^>]+>", " ", text)
                        text = re.sub(r"\s+", " ", text).strip()
                        return text
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(errors="replace")
        return ""

    def stats(self) -> dict:
        return {
            "configured": self.configured,
            "running": self._running,
            "host": self._imap_host,
            "user": self._imap_user,
            "processed": self._processed_count,
            "vip_senders": self._vip_senders,
        }
