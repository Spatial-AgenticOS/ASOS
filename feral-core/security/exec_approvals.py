"""
FERAL Execution Approval System
Requires explicit user approval before running dangerous tools.

Pattern: per-command exec approvals store with TTL.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from config.loader import feral_data_home


class ApprovalPolicy(str, Enum):
    """How approvals are enforced before dangerous tool execution."""

    DENY = "deny"
    ALLOWLIST = "allowlist"
    FULL_ACCESS = "full_access"


@dataclass
class ApprovalRecord:
    tool_name: str
    approved_by: str
    approved_at: float
    expires_at: Optional[float]
    scope: str  # "session" | "permanent"


def _default_db_path() -> str:
    base = feral_data_home()
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "exec_approvals.db")


class ApprovalManager:
    """
    SQLite-backed grants for tool execution.
    Session-scoped rows may set expires_at; permanent rows use scope='permanent'
    and expires_at NULL (until revoked).
    """

    def __init__(
        self,
        policy: ApprovalPolicy = ApprovalPolicy.ALLOWLIST,
        db_path: Optional[str] = None,
    ):
        self.policy = policy
        self._db_path = db_path or _default_db_path()
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        # One connection for the process lifetime so :memory: and threading stay consistent.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        conn = self._conn
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exec_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    approved_at REAL NOT NULL,
                    expires_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exec_approvals_tool_session
                ON exec_approvals (tool_name, session_id)
                """
            )

    def close(self) -> None:
        """Close the SQLite connection (optional for tests/shutdown)."""
        with self._lock:
            self._conn.close()

    def check_approval(self, tool_name: str, session_id: str) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        if self.policy == ApprovalPolicy.FULL_ACCESS:
            return True, "policy: full access"
        if self.policy == ApprovalPolicy.DENY:
            return False, "policy: deny all approvals"

        with self._lock:
            now = time.time()
            conn = self._conn
            rows = conn.execute(
                """
                SELECT * FROM exec_approvals
                WHERE tool_name = ? AND (
                    session_id = ? OR (scope = 'permanent' AND session_id = '*')
                )
                ORDER BY id DESC
                """,
                (tool_name, session_id),
            ).fetchall()

            for row in rows:
                exp = row["expires_at"]
                if exp is not None and exp <= now:
                    continue
                return True, "allowlisted"

            return False, "no matching approval"

    def grant_approval(
        self,
        tool_name: str,
        session_id: str,
        scope: str = "session",
    ) -> ApprovalRecord:
        """
        Persist an approval for this tool.
        Permanent grants are stored with session_id='*', scope='permanent', expires_at NULL.
        Session grants use the given session_id; optional expiry can be layered by deleting rows
        when the session ends (caller) or by setting expires_at before next check.
        """
        if scope == "permanent":
            sid = "*"
            exp: Optional[float] = None
        else:
            sid = session_id
            exp = None

        now = time.time()
        with self._lock:
            conn = self._conn
            conn.execute(
                """
                DELETE FROM exec_approvals
                WHERE tool_name = ? AND session_id = ? AND scope = ?
                """,
                (tool_name, sid, scope),
            )
            conn.execute(
                """
                INSERT INTO exec_approvals
                (tool_name, session_id, scope, approved_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tool_name, sid, scope, now, exp),
            )
            conn.commit()

        return ApprovalRecord(
            tool_name=tool_name,
            approved_by="user",
            approved_at=now,
            expires_at=exp,
            scope=scope,
        )

    def revoke_approval(self, tool_name: str, session_id: str) -> None:
        """
        Remove the approval row for this exact (tool_name, session_id).
        Pass session_id='*' to drop a permanent (global) grant.
        """
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM exec_approvals
                WHERE tool_name = ? AND session_id = ?
                """,
                (tool_name, session_id),
            )
            self._conn.commit()

    def list_approvals(self, session_id: str) -> list[ApprovalRecord]:
        """Approvals for this session plus global permanent rows."""
        now = time.time()
        out: list[ApprovalRecord] = []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM exec_approvals
                WHERE session_id = ? OR session_id = '*'
                ORDER BY approved_at DESC
                """,
                (session_id,),
            ).fetchall()

        for row in rows:
            exp = row["expires_at"]
            if exp is not None and exp <= now:
                continue
            out.append(
                ApprovalRecord(
                    tool_name=row["tool_name"],
                    approved_by="user",
                    approved_at=row["approved_at"],
                    expires_at=exp,
                    scope=row["scope"],
                )
            )
        return out

    def request_approval(self, tool_name: str, session_id: str) -> dict[str, Any]:
        """
        Create a pending approval request for the client to render.
        Client should call grant_approval after user confirms.
        """
        req_id = str(uuid.uuid4())
        payload = {
            "request_id": req_id,
            "status": "pending",
            "tool_name": tool_name,
            "session_id": session_id,
            "message": f"Approval required to run: {tool_name}",
            "created_at": time.time(),
        }
        with self._lock:
            self._pending[req_id] = payload
        return payload
