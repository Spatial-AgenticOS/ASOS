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
                # Additive migrations. Silent-skip when already present so
                # re-running on an existing DB is safe.
                for col, decl in (
                    ("kind", "TEXT"),             # "browser" / "hup" / "name"
                    ("node_id", "TEXT"),          # free-form daemon id (optional)
                    ("claimed_at", "REAL"),       # set when /v1/node authed with this token
                    ("platform", "TEXT"),         # ua / os for browser clients
                    ("capabilities", "TEXT"),     # JSON-encoded list
                ):
                    try:
                        conn.execute(f"ALTER TABLE paired_devices ADD COLUMN {col} {decl}")
                    except sqlite3.OperationalError:
                        pass
                conn.commit()
            finally:
                conn.close()

    def pair_device(
        self,
        name: str,
        *,
        kind: str = "name",
        node_id: str = "",
        platform: str = "",
        capabilities: Optional[list[str]] = None,
    ) -> dict:
        """Register a new device.

        Args:
            name: human-readable label the user sees in Devices.
            kind: ``"name"`` (default pair-modal label), ``"browser"`` (a
                browser-node attach), ``"hup"`` (daemon registering with
                explicit node_id + capabilities). This is the "typed body"
                the v2 PairDeviceModal needed for its HUP tab.
            node_id: optional authoritative id the daemon will register
                with on /v1/node (only used by kind="hup").
            platform: user-agent / platform hint for browser clients.
            capabilities: declared capabilities (camera / mic / location /
                heart_rate / …), JSON-encoded in storage.

        Returns ``{device_id, token, name, paired_at, kind, node_id?, …}``.
        """
        import json as _json
        device_id = str(uuid4())
        token = secrets.token_hex(32)
        now = time.time()
        caps_text = _json.dumps(list(capabilities or []))
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO paired_devices
                       (device_id, token, name, paired_at, kind, node_id, platform, capabilities)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (device_id, token, name, now, kind, node_id or "", platform or "", caps_text),
                )
                conn.commit()
            finally:
                conn.close()
        logger.info("Paired device %s (%s, kind=%s, node=%s)", device_id, name, kind, node_id or "-")
        return {
            "device_id": device_id,
            "token": token,
            "name": name,
            "paired_at": now,
            "kind": kind,
            "node_id": node_id or "",
            "platform": platform or "",
            "capabilities": list(capabilities or []),
        }

    def mark_claimed(self, token: str) -> Optional[str]:
        """Set ``claimed_at`` once a daemon actually attaches with *token*.

        Used by /api/devices/pair/complete so the UI can distinguish
        tokens that were issued-but-never-used from live paired devices.
        Returns the device_id on success.
        """
        now = time.time()
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT device_id FROM paired_devices WHERE token = ?", (token,),
                ).fetchone()
                if row is None:
                    return None
                conn.execute(
                    "UPDATE paired_devices SET claimed_at = ?, last_seen = ? WHERE token = ?",
                    (now, now, token),
                )
                conn.commit()
                return row["device_id"]
            finally:
                conn.close()

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
        """Return all paired devices with the typed metadata."""
        import json as _json
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT device_id, token, name, paired_at, last_seen,
                          kind, node_id, claimed_at, platform, capabilities
                   FROM paired_devices
                   ORDER BY paired_at DESC"""
            ).fetchall()
            out = []
            for r in rows:
                caps_raw = r["capabilities"] if "capabilities" in r.keys() else None
                try:
                    caps = _json.loads(caps_raw) if caps_raw else []
                except Exception:
                    caps = []
                out.append({
                    "device_id": r["device_id"],
                    "token": r["token"],
                    "name": r["name"],
                    "paired_at": r["paired_at"],
                    "last_seen": r["last_seen"],
                    "kind": r["kind"] if "kind" in r.keys() else "",
                    "node_id": r["node_id"] if "node_id" in r.keys() else "",
                    "claimed_at": r["claimed_at"] if "claimed_at" in r.keys() else None,
                    "platform": r["platform"] if "platform" in r.keys() else "",
                    "capabilities": caps,
                })
            return out
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
