"""
FERAL Per-Node Device Pairing
===============================
SQLite-backed registry of paired edge-node devices.

Each paired device gets a unique token that replaces the old
single ``NODE_API_KEY`` for authenticating ``/v1/node`` connections.
"""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

logger = logging.getLogger("feral.device_pairing")


class DevicePairingStore:
    """SQLite-backed paired-device registry.

    Default path: ``~/.feral/paired_devices.db`` (overridable for tests).
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            home = os.environ.get("FERAL_HOME", str(Path.home() / ".feral"))
            Path(home).mkdir(parents=True, exist_ok=True)
            db_path = str(Path(home) / "paired_devices.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS paired_devices (
                        device_id  TEXT PRIMARY KEY,
                        token      TEXT NOT NULL UNIQUE,
                        name       TEXT NOT NULL,
                        paired_at  REAL NOT NULL,
                        last_seen  REAL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_pd_token
                    ON paired_devices(token)
                """)
                conn.commit()
            finally:
                conn.close()

    def pair_device(self, name: str) -> dict:
        """Register a new device.  Returns ``{device_id, token, name, paired_at}``."""
        device_id = str(uuid4())
        token = secrets.token_hex(32)
        now = time.time()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO paired_devices (device_id, token, name, paired_at) VALUES (?, ?, ?, ?)",
                    (device_id, token, name, now),
                )
                conn.commit()
            finally:
                conn.close()
        logger.info("Paired device %s (%s)", device_id, name)
        return {"device_id": device_id, "token": token, "name": name, "paired_at": now}

    def verify_device(self, token: str) -> Optional[str]:
        """Return the ``device_id`` for *token*, or ``None`` if invalid.

        Also bumps ``last_seen`` on a valid lookup.
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT device_id FROM paired_devices WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                return None
            device_id = row["device_id"]
        finally:
            conn.close()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "UPDATE paired_devices SET last_seen = ? WHERE device_id = ?",
                    (time.time(), device_id),
                )
                conn.commit()
            finally:
                conn.close()
        return device_id

    def list_devices(self) -> list[dict]:
        """Return all paired devices."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT device_id, token, name, paired_at, last_seen FROM paired_devices ORDER BY paired_at DESC"
            ).fetchall()
            return [
                {
                    "device_id": r["device_id"],
                    "token": r["token"],
                    "name": r["name"],
                    "paired_at": r["paired_at"],
                    "last_seen": r["last_seen"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def revoke_device(self, device_id: str) -> bool:
        """Remove a paired device.  Returns ``True`` if a row was deleted."""
        with self._lock:
            conn = self._conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM paired_devices WHERE device_id = ?", (device_id,)
                )
                conn.commit()
                deleted = cursor.rowcount > 0
            finally:
                conn.close()
        if deleted:
            logger.info("Revoked device %s", device_id)
        return deleted


_store: Optional[DevicePairingStore] = None


def get_pairing_store(db_path: Optional[str] = None) -> DevicePairingStore:
    """Module-level singleton (lazy-init)."""
    global _store
    if _store is None:
        _store = DevicePairingStore(db_path)
    return _store


def reset_store() -> None:
    """Reset the singleton — useful for tests."""
    global _store
    _store = None
