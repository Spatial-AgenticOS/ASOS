"""
FERAL Daemon Command Contract
==============================
Formal lifecycle for hardware/software commands sent to edge daemons.

Command States:
  SUBMITTED -> ACKED -> RUNNING -> SUCCEEDED | FAILED | CANCELLED | TIMED_OUT

Every command carries:
  - command_id: globally unique UUID (full, not truncated)
  - idempotency_key: optional dedup key for retries
  - deadline: UTC timestamp after which the command should not execute
  - correlation_id: trace ID linking to the originating user request
  - priority: SAFETY > INTERACTIVE > BACKGROUND
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger("feral.command_contract")


# ─────────────────────────────────────────────
# Envelope & State
# ─────────────────────────────────────────────


class CommandEnvelope(BaseModel):
    """Wire-format envelope for every command sent to a daemon."""

    command_id: str = Field(default_factory=lambda: str(uuid4()))
    idempotency_key: Optional[str] = None
    deadline: Optional[float] = None
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    priority: Literal["safety", "interactive", "background"] = "interactive"
    node_id: str
    action: str
    params: dict = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class CommandState(str, Enum):
    SUBMITTED = "submitted"
    ACKED = "acked"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


_TERMINAL_STATES = {
    CommandState.SUCCEEDED,
    CommandState.FAILED,
    CommandState.CANCELLED,
    CommandState.TIMED_OUT,
}


class CommandRecord(BaseModel):
    """Full lifecycle record for a single command."""

    envelope: CommandEnvelope
    state: CommandState = CommandState.SUBMITTED
    state_history: list[dict] = Field(default_factory=list)
    ack_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[dict] = None
    retries: int = 0


# ─────────────────────────────────────────────
# CommandLedger — SQLite-backed durable store
# ─────────────────────────────────────────────


class CommandLedger:
    """
    Persistent command ledger backed by SQLite.

    Default path: ``~/.feral/command_ledger.db`` (overridable for tests).
    Thread-safe via a reentrant lock around all writes.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            import os
            home = os.environ.get("FERAL_HOME", str(Path.home() / ".feral"))
            Path(home).mkdir(parents=True, exist_ok=True)
            db_path = str(Path(home) / "command_ledger.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # -- schema ----------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS commands (
                        command_id     TEXT PRIMARY KEY,
                        idempotency_key TEXT,
                        envelope_json  TEXT NOT NULL,
                        state          TEXT NOT NULL,
                        history_json   TEXT NOT NULL DEFAULT '[]',
                        ack_at         REAL,
                        completed_at   REAL,
                        result_json    TEXT,
                        retries        INTEGER NOT NULL DEFAULT 0,
                        node_id        TEXT NOT NULL,
                        created_at     REAL NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cmd_node
                    ON commands(node_id, state)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cmd_idemp
                    ON commands(idempotency_key)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cmd_created
                    ON commands(created_at DESC)
                """)
                conn.commit()
            finally:
                conn.close()

    # -- helpers ---------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> CommandRecord:
        envelope = CommandEnvelope.model_validate_json(row["envelope_json"])
        result = json.loads(row["result_json"]) if row["result_json"] else None
        history = json.loads(row["history_json"])
        return CommandRecord(
            envelope=envelope,
            state=CommandState(row["state"]),
            state_history=history,
            ack_at=row["ack_at"],
            completed_at=row["completed_at"],
            result=result,
            retries=row["retries"],
        )

    def _append_history(self, existing_json: str, state: CommandState, message: str = "") -> str:
        history = json.loads(existing_json)
        history.append({
            "timestamp": time.time(),
            "state": state.value,
            "message": message,
        })
        return json.dumps(history)

    # -- public API ------------------------------------------------------

    def submit(self, envelope: CommandEnvelope) -> CommandRecord:
        """Insert a new command in SUBMITTED state.  Returns the record."""
        if envelope.idempotency_key:
            existing = self.check_idempotency(envelope.idempotency_key)
            if existing is not None:
                return existing

        now = time.time()
        history = json.dumps([{"timestamp": now, "state": CommandState.SUBMITTED.value, "message": "created"}])

        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO commands
                       (command_id, idempotency_key, envelope_json, state,
                        history_json, retries, node_id, created_at)
                       VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
                    (
                        envelope.command_id,
                        envelope.idempotency_key,
                        envelope.model_dump_json(),
                        CommandState.SUBMITTED.value,
                        history,
                        envelope.node_id,
                        envelope.created_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        return CommandRecord(
            envelope=envelope,
            state=CommandState.SUBMITTED,
            state_history=json.loads(history),
        )

    def ack(self, command_id: str) -> Optional[CommandRecord]:
        """Transition a command to ACKED.  Returns updated record or None."""
        return self.update_state(command_id, CommandState.ACKED, message="daemon acknowledged")

    def update_state(
        self,
        command_id: str,
        state: CommandState,
        message: str = "",
        result: Optional[dict] = None,
    ) -> Optional[CommandRecord]:
        now = time.time()
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT * FROM commands WHERE command_id = ?", (command_id,)
                ).fetchone()
                if row is None:
                    return None

                current = CommandState(row["state"])
                if current in _TERMINAL_STATES:
                    return self._row_to_record(row)

                new_history = self._append_history(row["history_json"], state, message)

                ack_at = row["ack_at"]
                if state == CommandState.ACKED and ack_at is None:
                    ack_at = now

                completed_at = row["completed_at"]
                if state in _TERMINAL_STATES and completed_at is None:
                    completed_at = now

                result_json = json.dumps(result) if result is not None else row["result_json"]

                conn.execute(
                    """UPDATE commands
                       SET state = ?, history_json = ?, ack_at = ?,
                           completed_at = ?, result_json = ?
                       WHERE command_id = ?""",
                    (state.value, new_history, ack_at, completed_at, result_json, command_id),
                )
                conn.commit()

                updated = conn.execute(
                    "SELECT * FROM commands WHERE command_id = ?", (command_id,)
                ).fetchone()
                return self._row_to_record(updated)
            finally:
                conn.close()

    def get(self, command_id: str) -> Optional[CommandRecord]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ?", (command_id,)
            ).fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def get_pending(self, node_id: str) -> list[CommandRecord]:
        """Return non-terminal commands for a given node, oldest first."""
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT * FROM commands
                   WHERE node_id = ? AND state NOT IN (?, ?, ?, ?)
                   ORDER BY created_at ASC""",
                (
                    node_id,
                    CommandState.SUCCEEDED.value,
                    CommandState.FAILED.value,
                    CommandState.CANCELLED.value,
                    CommandState.TIMED_OUT.value,
                ),
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    def get_recent(self, limit: int = 50) -> list[CommandRecord]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM commands ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    def check_idempotency(self, key: str) -> Optional[CommandRecord]:
        """Return existing record with the same idempotency key, or None."""
        if not key:
            return None
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM commands WHERE idempotency_key = ? LIMIT 1", (key,)
            ).fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def expire_stale(self, timeout_seconds: float = 300.0) -> int:
        """Move SUBMITTED/RUNNING commands past their deadline to TIMED_OUT.

        Returns the number of commands expired.
        """
        now = time.time()
        cutoff = now - timeout_seconds
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    """SELECT * FROM commands
                       WHERE state IN (?, ?)
                         AND (
                             (deadline IS NOT NULL AND deadline < ?)
                             OR (deadline IS NULL AND created_at < ?)
                         )""",
                    (
                        CommandState.SUBMITTED.value,
                        CommandState.RUNNING.value,
                        now,
                        cutoff,
                    ),
                ).fetchall()

                count = 0
                for row in rows:
                    new_history = self._append_history(
                        row["history_json"], CommandState.TIMED_OUT, "expired by ledger sweep"
                    )
                    conn.execute(
                        """UPDATE commands
                           SET state = ?, history_json = ?, completed_at = ?
                           WHERE command_id = ?""",
                        (CommandState.TIMED_OUT.value, new_history, now, row["command_id"]),
                    )
                    count += 1

                conn.commit()
                return count
            finally:
                conn.close()

    def stats(self) -> dict:
        """Return counts by state."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT state, COUNT(*) as cnt FROM commands GROUP BY state"
            ).fetchall()
            counts = {r["state"]: r["cnt"] for r in rows}
            counts["total"] = sum(counts.values())
            return counts
        finally:
            conn.close()


# ─────────────────────────────────────────────
# NodeHealth — per-node liveness tracking
# ─────────────────────────────────────────────


class NodeHealth:
    """In-memory per-node health tracker.

    Records heartbeats and error/command counts so the brain can
    decide whether a node is healthy before dispatching commands.
    """

    def __init__(self):
        self._nodes: dict[str, dict] = {}
        self._lock = threading.Lock()

    def record_heartbeat(self, node_id: str):
        now = time.time()
        with self._lock:
            entry = self._nodes.setdefault(node_id, {
                "connected_at": now,
                "command_count": 0,
                "error_count": 0,
            })
            entry["last_heartbeat"] = now

    def record_connect(self, node_id: str):
        now = time.time()
        with self._lock:
            self._nodes[node_id] = {
                "connected_at": now,
                "last_heartbeat": now,
                "command_count": 0,
                "error_count": 0,
            }

    def record_disconnect(self, node_id: str):
        with self._lock:
            self._nodes.pop(node_id, None)

    def increment_commands(self, node_id: str):
        with self._lock:
            entry = self._nodes.get(node_id)
            if entry:
                entry["command_count"] = entry.get("command_count", 0) + 1

    def increment_errors(self, node_id: str):
        with self._lock:
            entry = self._nodes.get(node_id)
            if entry:
                entry["error_count"] = entry.get("error_count", 0) + 1

    def is_healthy(self, node_id: str, max_stale_seconds: float = 60.0) -> bool:
        with self._lock:
            entry = self._nodes.get(node_id)
            if entry is None:
                return False
            last = entry.get("last_heartbeat", 0)
            return (time.time() - last) < max_stale_seconds

    def get_all(self) -> dict[str, dict]:
        with self._lock:
            now = time.time()
            out: dict[str, dict] = {}
            for nid, entry in self._nodes.items():
                last = entry.get("last_heartbeat", 0)
                out[nid] = {
                    **entry,
                    "healthy": (now - last) < 60,
                    "stale_seconds": round(now - last, 1) if last else None,
                }
            return out
