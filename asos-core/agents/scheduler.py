"""
THEORA Proactive Scheduler
SQLite-backed job scheduler for reminders, health checks, data sync, and proactive insights.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Optional

from config.loader import theora_data_home


class JobType(str, Enum):
    REMINDER = "reminder"
    HEALTH_CHECK = "health_check"
    DATA_SYNC = "data_sync"
    PROACTIVE_INSIGHT = "proactive_insight"
    CUSTOM = "custom"
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"
    CHAIN = "chain"
    WATCHER = "watcher"


@dataclass
class ScheduledJob:
    id: int
    job_type: JobType
    cron_expr: str
    description: str
    payload: dict[str, Any]
    session_id: str
    created_at: float
    last_run: Optional[float]
    next_run: float
    enabled: bool
    run_count: int


def _default_db_path() -> str:
    base = theora_data_home()
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "scheduled_jobs.db")


def _compute_next_run(cron_expr: str, from_time: float) -> float:
    """
    Compute the next run timestamp (UTC epoch seconds) strictly after from_time.

    Supported forms:
    - "every Nm" / "every N m" — every N minutes
    - "every Nh" / "every N h" — every N hours
    - "daily HH:MM" — once per day at HH:MM (24h, UTC)
    - 5-field cron (subset): */N * * * *, M H * * *, etc.
    """
    raw = cron_expr.strip()
    if not raw:
        return from_time + 60.0

    # every N minutes
    m = re.match(r"^every\s+(\d+)\s*m(?:inutes?)?$", raw, re.I)
    if m:
        n = max(1, int(m.group(1)))
        return from_time + n * 60.0

    # every N hours
    m = re.match(r"^every\s+(\d+)\s*h(?:ours?)?$", raw, re.I)
    if m:
        n = max(1, int(m.group(1)))
        return from_time + n * 3600.0

    # daily HH:MM
    m = re.match(r"^daily\s+(\d{1,2}):(\d{2})$", raw, re.I)
    if m:
        hh = int(m.group(1)) % 24
        mm = int(m.group(2)) % 60
        dt = datetime.fromtimestamp(from_time, tz=timezone.utc)
        target = dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target.timestamp() <= from_time:
            target = target + timedelta(days=1)
        return target.timestamp()

    # 5-field cron (limited)
    parts = raw.split()
    if len(parts) == 5:
        minute, hour, dom, month, dow = parts

        def _parse_field(spec: str, vmin: int, vmax: int) -> Optional[int]:
            if spec == "*":
                return None
            if spec.startswith("*/"):
                return int(spec[2:])
            if spec.isdigit():
                v = int(spec)
                if vmin <= v <= vmax:
                    return v
            return None

        # */N * * * *  -> every N minutes (interval from last boundary)
        if minute.startswith("*/") and hour == dom == month == dow == "*":
            step = max(1, int(minute[2:]))
            return float(from_time + step * 60.0)

        # */N * * * * for hours: 0 */N * * *
        if (
            minute == "0"
            and hour.startswith("*/")
            and dom == month == dow == "*"
        ):
            step = max(1, int(hour[2:]))
            interval = step * 3600
            nxt = int(from_time // interval) * interval + interval
            if nxt <= from_time:
                nxt += interval
            return float(nxt)

        # M H * * * -> daily at H:M
        if dom == month == dow == "*":
            mm = _parse_field(minute, 0, 59)
            hh = _parse_field(hour, 0, 23)
            if mm is not None and hh is not None:
                dt = datetime.fromtimestamp(from_time, tz=timezone.utc)
                target = dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if target.timestamp() <= from_time:
                    target = target + timedelta(days=1)
                return target.timestamp()

    # Fallback: 1 minute after from_time
    return from_time + 60.0


class CronService:
    """Background-friendly scheduler with a SQLite job store."""

    @staticmethod
    def _compute_next_run(cron_expr: str, from_time: float) -> float:
        """Delegate to module parser; kept on the class for discovery/testing."""
        return _compute_next_run(cron_expr, from_time)

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _default_db_path()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[ScheduledJob], None]] = None
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        conn = self._conn
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    cron_expr TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}',
                    session_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    last_run REAL,
                    next_run REAL NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    run_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sched_next ON scheduled_jobs (next_run)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS routine_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    status TEXT NOT NULL DEFAULT 'running',
                    result TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    FOREIGN KEY (job_id) REFERENCES scheduled_jobs(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_job ON routine_runs (job_id, started_at DESC)"
            )

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> ScheduledJob:
        payload = json.loads(row["payload"] or "{}")
        return ScheduledJob(
            id=row["id"],
            job_type=JobType(row["job_type"]),
            cron_expr=row["cron_expr"],
            description=row["description"] or "",
            payload=payload,
            session_id=row["session_id"] or "",
            created_at=row["created_at"],
            last_run=row["last_run"],
            next_run=row["next_run"],
            enabled=bool(row["enabled"]),
            run_count=row["run_count"],
        )

    def create_job(
        self,
        job_type: JobType | str,
        cron_expr: str,
        description: str,
        payload: dict[str, Any],
        session_id: str,
    ) -> ScheduledJob:
        if isinstance(job_type, str):
            job_type = JobType(job_type)
        now = time.time()
        nxt = CronService._compute_next_run(cron_expr, now)
        payload_json = json.dumps(payload)
        with self._lock:
            conn = self._conn
            cur = conn.execute(
                """
                INSERT INTO scheduled_jobs
                (job_type, cron_expr, description, payload, session_id,
                 created_at, last_run, next_run, enabled, run_count)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 1, 0)
                """,
                (
                    job_type.value,
                    cron_expr,
                    description,
                    payload_json,
                    session_id,
                    now,
                    nxt,
                ),
            )
            jid = cur.lastrowid
            conn.commit()
            row = conn.execute(
                "SELECT * FROM scheduled_jobs WHERE id = ?", (jid,)
            ).fetchone()
        assert row is not None
        return self._row_to_job(row)

    def delete_job(self, job_id: int) -> bool:
        with self._lock:
            conn = self._conn
            cur = conn.execute(
                "DELETE FROM scheduled_jobs WHERE id = ?", (job_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    def list_jobs(self, session_id: Optional[str] = None) -> list[ScheduledJob]:
        with self._lock:
            conn = self._conn
            if session_id is None:
                rows = conn.execute(
                    "SELECT * FROM scheduled_jobs ORDER BY id ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scheduled_jobs WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_due_jobs(self) -> list[ScheduledJob]:
        now = time.time()
        with self._lock:
            conn = self._conn
            rows = conn.execute(
                """
                SELECT * FROM scheduled_jobs
                WHERE enabled = 1 AND next_run <= ?
                ORDER BY next_run ASC
                """,
                (now,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def mark_completed(self, job_id: int) -> None:
        now = time.time()
        with self._lock:
            conn = self._conn
            row = conn.execute(
                "SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return
            cron = row["cron_expr"]
            nxt = CronService._compute_next_run(cron, now)
            conn.execute(
                """
                UPDATE scheduled_jobs
                SET last_run = ?, next_run = ?, run_count = run_count + 1
                WHERE id = ?
                """,
                (now, nxt, job_id),
            )
            conn.commit()

    def pause_job(self, job_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE scheduled_jobs SET enabled = 0 WHERE id = ?", (job_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def resume_job(self, job_id: int) -> bool:
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT cron_expr FROM scheduled_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return False
            nxt = CronService._compute_next_run(row["cron_expr"], now)
            self._conn.execute(
                "UPDATE scheduled_jobs SET enabled = 1, next_run = ? WHERE id = ?",
                (nxt, job_id),
            )
            self._conn.commit()
            return True

    def get_job(self, job_id: int) -> Optional[ScheduledJob]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def record_run_start(self, job_id: int) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO routine_runs (job_id, started_at, status) VALUES (?, ?, 'running')",
                (job_id, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def record_run_finish(self, run_id: int, status: str, result: dict, error: str | None = None) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE routine_runs SET finished_at = ?, status = ?, result = ?, error = ? WHERE id = ?",
                (now, status, json.dumps(result), error, run_id),
            )
            self._conn.commit()

    def get_runs(self, job_id: int, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM routine_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "job_id": r["job_id"],
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
                "status": r["status"],
                "result": json.loads(r["result"] or "{}"),
                "error": r["error"],
            }
            for r in rows
        ]

    def _loop(self) -> None:
        while not self._stop.wait(30.0):
            if self._callback is None:
                continue
            due = self.get_due_jobs()
            for job in due:
                try:
                    self._callback(job)
                finally:
                    self.mark_completed(job.id)

    def start(self, callback: Callable[[ScheduledJob], None]) -> None:
        """Poll every 30s for due jobs and invoke callback, then reschedule."""
        self._callback = callback
        self._stop.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=35.0)
            self._thread = None


def get_scheduler_skill_manifest() -> dict[str, Any]:
    """Manifest for agent tool use: create/list/delete scheduled jobs."""
    return {
        "name": "theora_scheduler",
        "version": "1.0.0",
        "description": "Create and manage proactive scheduled jobs (SQLite-backed).",
        "endpoints": [
            {
                "name": "create_job",
                "method": "POST",
                "path": "/scheduler/jobs",
                "body": {
                    "job_type": "reminder | health_check | data_sync | proactive_insight | custom",
                    "cron_expr": "string (e.g. every 15m, daily 09:30, */5 * * * *)",
                    "description": "string",
                    "payload": "object",
                    "session_id": "string",
                },
            },
            {
                "name": "list_jobs",
                "method": "GET",
                "path": "/scheduler/jobs",
                "query": {"session_id": "optional string"},
            },
            {
                "name": "delete_job",
                "method": "DELETE",
                "path": "/scheduler/jobs/{job_id}",
            },
        ],
    }
