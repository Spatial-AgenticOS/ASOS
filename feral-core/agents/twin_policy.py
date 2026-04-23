"""TwinPolicy + ApprovalQueue — the guardrails that let the digital twin
actually act on the user's behalf without turning into a loose cannon.

Every twin action is gated by:
  1. A per-domain policy (draft_only / auto_send / disabled).
  2. Time windows (HH:MM-HH:MM) when the mode applies.
  3. A daily cap (max_per_day) so the twin can't spam on your behalf.
  4. An optional requires_user_online flag.
  5. The global kill switch (Supervisor.set_paused).

When the mode is ``draft_only``, the action lands in an approval queue
backed by SQLite. The user reviews via /api/twin/approvals + v2 Settings
→ Twin & Delegation and approves / rejects. When the mode is
``auto_send`` AND all checks pass, the action executes immediately and
lands in the Supervisor audit log as actor="twin".

Domains are free-form strings so new twin skills register their own
without schema churn. Canonical starter set:

  respond_imessage, draft_email, reply_slack, reply_telegram,
  schedule_meeting, buy_groceries, summarise_reading, post_journal
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4


logger = logging.getLogger("feral.twin_policy")


CANONICAL_DOMAINS: tuple[str, ...] = (
    "respond_imessage",
    "draft_email",
    "reply_slack",
    "reply_telegram",
    "reply_whatsapp",
    "schedule_meeting",
    "buy_groceries",
    "summarise_reading",
    "post_journal",
)

MODES = {"draft_only", "auto_send", "disabled"}


@dataclass
class TwinPolicy:
    """Policy for a single twin domain."""
    domain: str
    mode: str = "draft_only"  # draft_only / auto_send / disabled
    time_windows: list[str] = field(default_factory=list)  # ["09:00-21:00", ...]
    max_per_day: int = 10
    requires_user_online: bool = False

    def validate(self) -> "TwinPolicy":
        if self.mode not in MODES:
            raise ValueError(f"unknown mode: {self.mode} (want one of {sorted(MODES)})")
        for w in self.time_windows:
            _parse_window(w)  # raises on bad shape
        if self.max_per_day < 0:
            raise ValueError("max_per_day must be >= 0")
        return self


def _parse_window(window: str) -> tuple[int, int, int, int]:
    """Parse "HH:MM-HH:MM" into (start_h, start_m, end_h, end_m)."""
    try:
        start, end = window.split("-")
        sh, sm = [int(x) for x in start.split(":")]
        eh, em = [int(x) for x in end.split(":")]
        if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60):
            raise ValueError
        return sh, sm, eh, em
    except Exception as exc:
        raise ValueError(f"bad time window {window!r} — want HH:MM-HH:MM") from exc


def _in_window(window: str, now: Optional[time.struct_time] = None) -> bool:
    sh, sm, eh, em = _parse_window(window)
    now = now or time.localtime()
    minutes = now.tm_hour * 60 + now.tm_min
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= minutes <= end
    # Cross-midnight window (e.g. "22:00-06:00")
    return minutes >= start or minutes <= end


@dataclass
class ApprovalRow:
    """A queued twin action awaiting user review."""
    approval_id: str
    created_at: float
    domain: str
    action: str               # free-form action id within the domain
    context: dict             # structured payload the twin wants to send
    status: str = "pending"   # pending / approved / rejected / expired / executed
    resolved_at: Optional[float] = None
    resolved_by: str = ""
    execution_result: dict = field(default_factory=dict)


class TwinPolicyStore:
    """SQLite store for per-domain policies + approval queue + daily counts."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            home = os.environ.get("FERAL_HOME", str(Path.home() / ".feral"))
            Path(home).mkdir(parents=True, exist_ok=True)
            db_path = str(Path(home) / "twin_policy.db")
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
                    CREATE TABLE IF NOT EXISTS twin_policies (
                        domain             TEXT PRIMARY KEY,
                        mode               TEXT NOT NULL,
                        time_windows       TEXT NOT NULL,
                        max_per_day        INTEGER NOT NULL,
                        requires_user_online INTEGER NOT NULL,
                        updated_at         REAL NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS twin_approvals (
                        approval_id TEXT PRIMARY KEY,
                        created_at  REAL NOT NULL,
                        domain      TEXT NOT NULL,
                        action      TEXT NOT NULL,
                        context     TEXT NOT NULL,
                        status      TEXT NOT NULL,
                        resolved_at REAL,
                        resolved_by TEXT,
                        execution_result TEXT NOT NULL DEFAULT '{}'
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_twin_pending
                    ON twin_approvals(status, created_at DESC)
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS twin_daily_counts (
                        domain     TEXT NOT NULL,
                        day        TEXT NOT NULL,
                        count      INTEGER NOT NULL,
                        PRIMARY KEY (domain, day)
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    # ── policies ─────────────────────────────────────────────────

    def upsert_policy(self, policy: TwinPolicy) -> TwinPolicy:
        policy.validate()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO twin_policies
                       (domain, mode, time_windows, max_per_day, requires_user_online, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(domain) DO UPDATE SET
                           mode = excluded.mode,
                           time_windows = excluded.time_windows,
                           max_per_day = excluded.max_per_day,
                           requires_user_online = excluded.requires_user_online,
                           updated_at = excluded.updated_at""",
                    (
                        policy.domain,
                        policy.mode,
                        json.dumps(policy.time_windows),
                        policy.max_per_day,
                        1 if policy.requires_user_online else 0,
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return policy

    def get_policy(self, domain: str) -> Optional[TwinPolicy]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM twin_policies WHERE domain = ?", (domain,),
            ).fetchone()
            if row is None:
                return None
            return TwinPolicy(
                domain=row["domain"],
                mode=row["mode"],
                time_windows=json.loads(row["time_windows"]),
                max_per_day=int(row["max_per_day"]),
                requires_user_online=bool(row["requires_user_online"]),
            )
        finally:
            conn.close()

    def list_policies(self) -> list[TwinPolicy]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM twin_policies ORDER BY domain"
            ).fetchall()
            return [
                TwinPolicy(
                    domain=r["domain"],
                    mode=r["mode"],
                    time_windows=json.loads(r["time_windows"]),
                    max_per_day=int(r["max_per_day"]),
                    requires_user_online=bool(r["requires_user_online"]),
                )
                for r in rows
            ]
        finally:
            conn.close()

    def delete_policy(self, domain: str) -> bool:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute("DELETE FROM twin_policies WHERE domain = ?", (domain,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    # ── approvals ────────────────────────────────────────────────

    def insert_approval(self, row: ApprovalRow) -> ApprovalRow:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO twin_approvals
                       (approval_id, created_at, domain, action, context,
                        status, resolved_at, resolved_by, execution_result)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row.approval_id,
                        row.created_at,
                        row.domain,
                        row.action,
                        json.dumps(row.context),
                        row.status,
                        row.resolved_at,
                        row.resolved_by,
                        json.dumps(row.execution_result),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return row

    def list_approvals(self, status: str = "", limit: int = 50) -> list[ApprovalRow]:
        q = "SELECT * FROM twin_approvals"
        args: list = []
        if status:
            q += " WHERE status = ?"
            args.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        conn = self._conn()
        try:
            rows = conn.execute(q, args).fetchall()
            return [
                ApprovalRow(
                    approval_id=r["approval_id"],
                    created_at=r["created_at"],
                    domain=r["domain"],
                    action=r["action"],
                    context=json.loads(r["context"]),
                    status=r["status"],
                    resolved_at=r["resolved_at"],
                    resolved_by=r["resolved_by"],
                    execution_result=json.loads(r["execution_result"] or "{}"),
                )
                for r in rows
            ]
        finally:
            conn.close()

    def set_approval_status(
        self,
        approval_id: str,
        *,
        status: str,
        resolved_by: str = "",
        execution_result: Optional[dict] = None,
    ) -> Optional[ApprovalRow]:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    """UPDATE twin_approvals
                       SET status = ?, resolved_at = ?, resolved_by = ?, execution_result = ?
                       WHERE approval_id = ?""",
                    (
                        status,
                        time.time(),
                        resolved_by,
                        json.dumps(execution_result or {}),
                        approval_id,
                    ),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
                row = conn.execute(
                    "SELECT * FROM twin_approvals WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return ApprovalRow(
            approval_id=row["approval_id"],
            created_at=row["created_at"],
            domain=row["domain"],
            action=row["action"],
            context=json.loads(row["context"]),
            status=row["status"],
            resolved_at=row["resolved_at"],
            resolved_by=row["resolved_by"],
            execution_result=json.loads(row["execution_result"] or "{}"),
        )

    # ── daily counts ─────────────────────────────────────────────

    def bump_daily_count(self, domain: str) -> int:
        day = time.strftime("%Y-%m-%d")
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO twin_daily_counts (domain, day, count)
                       VALUES (?, ?, 1)
                       ON CONFLICT(domain, day) DO UPDATE SET count = count + 1""",
                    (domain, day),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT count FROM twin_daily_counts WHERE domain = ? AND day = ?",
                    (domain, day),
                ).fetchone()
            finally:
                conn.close()
        return int(row["count"]) if row else 1

    def daily_count(self, domain: str) -> int:
        day = time.strftime("%Y-%m-%d")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT count FROM twin_daily_counts WHERE domain = ? AND day = ?",
                (domain, day),
            ).fetchone()
            return int(row["count"]) if row else 0
        finally:
            conn.close()


class TwinPolicyEngine:
    """Evaluates policies + manages the approval queue.

    Integrates with the Supervisor as the policy_gate for events whose
    actor is ``twin`` and records its own execution events via
    ``supervisor.record(actor='twin', ...)``.
    """

    def __init__(
        self,
        store: Optional[TwinPolicyStore] = None,
        *,
        supervisor=None,
        user_online: Callable[[], bool] = lambda: True,
    ):
        self.store = store or TwinPolicyStore()
        self.supervisor = supervisor
        self._user_online = user_online

    def set_user_online_probe(self, fn: Callable[[], bool]) -> None:
        self._user_online = fn

    def decide(self, domain: str, *, now: Optional[time.struct_time] = None) -> dict:
        """Return a decision dict for the twin before it acts.

        Shape: ``{"verdict": "allowed"|"denied"|"queued", "reason": str,
                   "policy": {...} | None}``.

        - No policy registered → queued (draft_only default).
        - mode=disabled        → denied.
        - mode=draft_only      → queued.
        - mode=auto_send       → check windows, cap, supervisor pause,
                                  and user-online. Pass → allowed.
        """
        if self.supervisor is not None and getattr(self.supervisor, "paused", False):
            return {"verdict": "denied", "reason": "supervisor_paused", "policy": None}

        policy = self.store.get_policy(domain)
        if policy is None:
            return {
                "verdict": "queued",
                "reason": "no_policy_default_draft",
                "policy": None,
            }
        if policy.mode == "disabled":
            return {"verdict": "denied", "reason": "policy_disabled", "policy": asdict(policy)}
        if policy.mode == "draft_only":
            return {"verdict": "queued", "reason": "mode_draft_only", "policy": asdict(policy)}

        # auto_send — every check must pass.
        if policy.time_windows:
            if not any(_in_window(w, now) for w in policy.time_windows):
                return {
                    "verdict": "queued",
                    "reason": "outside_window",
                    "policy": asdict(policy),
                }
        if policy.max_per_day and self.store.daily_count(domain) >= policy.max_per_day:
            return {
                "verdict": "queued",
                "reason": "daily_cap_reached",
                "policy": asdict(policy),
            }
        if policy.requires_user_online and not self._user_online():
            return {
                "verdict": "queued",
                "reason": "user_offline",
                "policy": asdict(policy),
            }

        return {"verdict": "allowed", "reason": "auto_send_ok", "policy": asdict(policy)}

    def queue_for_approval(
        self,
        domain: str,
        action: str,
        context: dict,
    ) -> ApprovalRow:
        row = ApprovalRow(
            approval_id=str(uuid4()),
            created_at=time.time(),
            domain=domain,
            action=action,
            context=dict(context or {}),
        )
        self.store.insert_approval(row)

        if self.supervisor is not None:
            try:
                self.supervisor.record(
                    source="twin",
                    kind="approval_queued",
                    actor="twin",
                    payload=context,
                    decision="queued",
                    detail={
                        "approval_id": row.approval_id,
                        "domain": domain,
                        "action": action,
                    },
                )
            except Exception as exc:
                logger.debug("supervisor.record(twin:queued) failed: %s", exc)
        return row

    def resolve(
        self,
        approval_id: str,
        *,
        verdict: str,
        resolved_by: str = "user",
        execution_result: Optional[dict] = None,
    ) -> Optional[ApprovalRow]:
        if verdict not in {"approved", "rejected", "expired", "executed"}:
            raise ValueError(f"bad verdict: {verdict}")
        row = self.store.set_approval_status(
            approval_id,
            status=verdict,
            resolved_by=resolved_by,
            execution_result=execution_result or {},
        )
        if row and self.supervisor is not None:
            try:
                self.supervisor.record(
                    source="twin",
                    kind=f"approval_{verdict}",
                    actor="user" if resolved_by == "user" else resolved_by or "system",
                    payload=row.context,
                    decision="allowed" if verdict in {"approved", "executed"} else "denied",
                    detail={
                        "approval_id": approval_id,
                        "domain": row.domain,
                        "action": row.action,
                    },
                )
            except Exception as exc:
                logger.debug("supervisor.record(twin:%s) failed: %s", verdict, exc)
        return row

    def record_execution(self, domain: str) -> int:
        return self.store.bump_daily_count(domain)
