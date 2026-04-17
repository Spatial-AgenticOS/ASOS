"""Persist channel user ↔ target id mappings (e.g. Telegram username → chat_id)."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from config.loader import feral_home

_lock = threading.Lock()
_store: Optional["ChannelContactStore"] = None


class ChannelContactStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (feral_home() / "channel_contacts.db")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contacts (
                    channel TEXT NOT NULL,
                    username TEXT,
                    target_id TEXT NOT NULL,
                    first_name TEXT,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    PRIMARY KEY (channel, target_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_contacts_channel_username "
                "ON contacts (channel, username)"
            )

    def remember(
        self,
        channel: str,
        target_id: str,
        username: str | None = None,
        first_name: str | None = None,
    ) -> None:
        un = _norm_username(username)
        now = time.time()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO contacts (channel, username, target_id, first_name, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel, target_id) DO UPDATE SET
                    username = COALESCE(excluded.username, contacts.username),
                    first_name = COALESCE(excluded.first_name, contacts.first_name),
                    last_seen = excluded.last_seen
                """,
                (channel, un, str(target_id), first_name or "", now, now),
            )

    def resolve_username(self, channel: str, username: str) -> str | None:
        un = _norm_username(username)
        if not un:
            return None
        with sqlite3.connect(self.path) as conn:
            cur = conn.execute(
                "SELECT target_id FROM contacts WHERE channel = ? AND username = ?",
                (channel, un),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None

    def list_for_channel(self, channel: str, limit: int = 200) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT channel, username, target_id, first_name, first_seen, last_seen
                FROM contacts WHERE channel = ?
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (channel, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def _norm_username(username: str | None) -> str | None:
    if not username:
        return None
    u = username.strip().lstrip("@").lower()
    return u or None


def get_contact_store() -> ChannelContactStore:
    global _store
    with _lock:
        if _store is None:
            _store = ChannelContactStore()
        return _store
