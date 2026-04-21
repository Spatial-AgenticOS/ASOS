"""ConsciousnessStore — the 5th memory tier.

Tiers 1-4 record what *happened*:
  * Working memory — the current session's last N turns.
  * Episodic — user-facing events the Brain observed.
  * Semantic / Knowledge Graph — extracted facts.
  * Execution log — tools that fired + their results.

Consciousness records what is *in-flight* — the agent's own active
operational state. Distinct from "jobs" (which is a live view of
what's running right now): Consciousness is the **persisted** record
that survives reboots, upgrades, and device handoffs so the agent
knows where it left off.

Answers the user-pain "I updated `pip install -U feral-ai` — does it
know what I was working on?". With this tier, yes by design.

Schema
------
Each entry is stored in SQLite at ``~/.feral/consciousness.sqlite`` with
the following shape:

* ``id`` (UUID)
* ``kind`` (``intent | flow | thought | device_stream | turn``)
* ``owner_session_id`` (nullable — survives session death)
* ``status`` (``active | paused | waiting_user | waiting_tool |
                completed | abandoned``)
* ``context_json`` (arbitrary per-kind payload; the TaskFlow step
  index, the intent's plan tree, the thought's half-formed sentence)
* ``summary`` (human-readable single-line "what was I doing?")
* ``created_at`` / ``updated_at`` / ``last_heartbeat_at`` (float secs)
* ``ttl_seconds`` (auto-abandon if no heartbeat)

Design non-negotiables
----------------------
* Snapshot + restore are idempotent and versioned (``schema: 1``).
* TTL-based auto-abandon runs on every ``list_active`` call — we don't
  need a background thread because the Brain boot calls us first and
  then the UI polls /api/consciousness/state.
* No LLM calls in this module. The natural-language "welcome back"
  summary is assembled by [/api/consciousness/summary] at request time.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger("feral.memory.consciousness")


SNAPSHOT_SCHEMA_VERSION = 1


VALID_KINDS = {"intent", "flow", "thought", "device_stream", "turn"}
VALID_STATUSES = {
    "active", "paused", "waiting_user", "waiting_tool",
    "completed", "abandoned",
}


@dataclass
class ConsciousnessEntity:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "thought"
    owner_session_id: Optional[str] = None
    status: str = "active"
    context_json: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_heartbeat_at: float = field(default_factory=time.time)
    ttl_seconds: float = 3600.0  # 1 hour default; flows override

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"invalid kind: {self.kind!r}; expected one of {VALID_KINDS}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {self.status!r}; expected one of {VALID_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ConsciousnessEntity":
        return cls(
            id=row["id"],
            kind=row["kind"],
            owner_session_id=row["owner_session_id"],
            status=row["status"],
            context_json=json.loads(row["context_json"] or "{}"),
            summary=row["summary"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            ttl_seconds=row["ttl_seconds"],
        )


class ConsciousnessStore:
    """SQLite-backed store for in-flight agent operational state."""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self._db_path))
        con.row_factory = sqlite3.Row
        return con

    def _init_schema(self) -> None:
        con = self._conn()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS consciousness (
                    id                  TEXT PRIMARY KEY,
                    kind                TEXT NOT NULL,
                    owner_session_id    TEXT,
                    status              TEXT NOT NULL,
                    context_json        TEXT NOT NULL DEFAULT '{}',
                    summary             TEXT NOT NULL DEFAULT '',
                    created_at          REAL NOT NULL,
                    updated_at          REAL NOT NULL,
                    last_heartbeat_at   REAL NOT NULL,
                    ttl_seconds         REAL NOT NULL
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_consciousness_status ON consciousness(status)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_consciousness_session ON consciousness(owner_session_id)"
            )
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def record(self, entity: ConsciousnessEntity) -> ConsciousnessEntity:
        """Upsert an entity by id. Called by orchestrator / taskflow /
        intent_compiler when they start or advance an operation.
        """
        now = time.time()
        entity.updated_at = now
        entity.last_heartbeat_at = now
        con = self._conn()
        try:
            con.execute(
                """
                INSERT INTO consciousness
                    (id, kind, owner_session_id, status, context_json,
                     summary, created_at, updated_at, last_heartbeat_at,
                     ttl_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    owner_session_id=excluded.owner_session_id,
                    status=excluded.status,
                    context_json=excluded.context_json,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at,
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    ttl_seconds=excluded.ttl_seconds
                """,
                (
                    entity.id,
                    entity.kind,
                    entity.owner_session_id,
                    entity.status,
                    json.dumps(entity.context_json or {}),
                    entity.summary or "",
                    entity.created_at,
                    entity.updated_at,
                    entity.last_heartbeat_at,
                    entity.ttl_seconds,
                ),
            )
            con.commit()
            return entity
        finally:
            con.close()

    def get(self, entity_id: str) -> Optional[ConsciousnessEntity]:
        con = self._conn()
        try:
            row = con.execute(
                "SELECT * FROM consciousness WHERE id = ?", (entity_id,)
            ).fetchone()
            return ConsciousnessEntity.from_row(row) if row else None
        finally:
            con.close()

    def heartbeat(self, entity_id: str) -> bool:
        """Bump ``last_heartbeat_at`` for an entity. Returns True if
        the row existed. Callers use this to keep long-running flows
        from being auto-abandoned by the TTL sweep."""
        now = time.time()
        con = self._conn()
        try:
            cur = con.execute(
                "UPDATE consciousness SET last_heartbeat_at = ? WHERE id = ?",
                (now, entity_id),
            )
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()

    def set_status(self, entity_id: str, status: str) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        now = time.time()
        con = self._conn()
        try:
            cur = con.execute(
                "UPDATE consciousness SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, entity_id),
            )
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()

    def abandon(self, entity_id: str) -> bool:
        return self.set_status(entity_id, "abandoned")

    def resume(self, entity_id: str) -> bool:
        return self.set_status(entity_id, "active")

    def pause(self, entity_id: str) -> bool:
        return self.set_status(entity_id, "paused")

    # ------------------------------------------------------------------
    # Listing + sweeping
    # ------------------------------------------------------------------

    def _sweep_ttl(self) -> int:
        """Auto-abandon entities whose last heartbeat is older than
        their ttl. Runs inline on every list_active call — cheap and
        keeps state honest without a background thread.
        """
        now = time.time()
        con = self._conn()
        try:
            cur = con.execute(
                """
                UPDATE consciousness
                SET status = 'abandoned', updated_at = ?
                WHERE status IN ('active', 'paused', 'waiting_user', 'waiting_tool')
                  AND (? - last_heartbeat_at) > ttl_seconds
                """,
                (now, now),
            )
            con.commit()
            n = cur.rowcount
            if n:
                logger.info("Consciousness TTL sweep: auto-abandoned %d entities", n)
            return n
        finally:
            con.close()

    def list_active(
        self,
        *,
        kind: Optional[str] = None,
        owner_session_id: Optional[str] = None,
        include_abandoned: bool = False,
    ) -> list[ConsciousnessEntity]:
        """Return rows in a non-terminal status. Sweeps TTL first."""
        self._sweep_ttl()
        con = self._conn()
        try:
            clauses = []
            params: list[Any] = []
            if not include_abandoned:
                clauses.append(
                    "status IN ('active', 'paused', 'waiting_user', 'waiting_tool')"
                )
            if kind:
                clauses.append("kind = ?")
                params.append(kind)
            if owner_session_id:
                clauses.append("owner_session_id = ?")
                params.append(owner_session_id)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = con.execute(
                f"SELECT * FROM consciousness {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
            return [ConsciousnessEntity.from_row(r) for r in rows]
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Serialise all active + paused entities into a versioned blob.

        Called on shutdown + on demand. Terminal states (completed,
        abandoned) are included but marked so restore() can skip them.
        """
        con = self._conn()
        try:
            rows = con.execute("SELECT * FROM consciousness").fetchall()
            entities = [ConsciousnessEntity.from_row(r).to_dict() for r in rows]
        finally:
            con.close()
        return {
            "schema": SNAPSHOT_SCHEMA_VERSION,
            "generated_at": time.time(),
            "count": len(entities),
            "entities": entities,
        }

    def restore(self, blob: dict[str, Any]) -> int:
        """Load a snapshot blob back into the store. Idempotent by id.

        Terminal-status entries are preserved so audit history stays
        intact, but consumers of list_active() will skip them.
        """
        if not isinstance(blob, dict):
            raise TypeError("snapshot blob must be a dict")
        schema = blob.get("schema", 0)
        if schema != SNAPSHOT_SCHEMA_VERSION:
            logger.warning(
                "Consciousness snapshot schema mismatch: got %s, expected %s — skipping restore",
                schema, SNAPSHOT_SCHEMA_VERSION,
            )
            return 0
        entities = blob.get("entities") or []
        restored = 0
        for raw in entities:
            try:
                entity = ConsciousnessEntity(**{
                    k: v for k, v in raw.items()
                    if k in {
                        "id", "kind", "owner_session_id", "status",
                        "context_json", "summary", "created_at",
                        "updated_at", "last_heartbeat_at", "ttl_seconds",
                    }
                })
                # Don't overwrite the heartbeat — restored entities may
                # have been stale for a long time. list_active's TTL
                # sweep will correctly auto-abandon if so.
                con = self._conn()
                try:
                    con.execute(
                        """
                        INSERT INTO consciousness
                            (id, kind, owner_session_id, status, context_json,
                             summary, created_at, updated_at, last_heartbeat_at,
                             ttl_seconds)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO NOTHING
                        """,
                        (
                            entity.id, entity.kind, entity.owner_session_id,
                            entity.status, json.dumps(entity.context_json),
                            entity.summary,
                            entity.created_at, entity.updated_at,
                            entity.last_heartbeat_at, entity.ttl_seconds,
                        ),
                    )
                    con.commit()
                finally:
                    con.close()
                restored += 1
            except Exception as exc:
                logger.warning("Skipping malformed consciousness entity: %s", exc)
        return restored

    # ------------------------------------------------------------------
    # Human summary — "Welcome back. You were working on..."
    # ------------------------------------------------------------------

    def natural_summary(self, *, limit: int = 5) -> str:
        """Assemble a single-paragraph English summary of current state.

        Called by GET /api/consciousness/summary for the v2 Home banner.
        Never calls the LLM — deterministic string assembly so the
        greeting renders instantly even before providers boot.
        """
        active = self.list_active()[:limit]
        if not active:
            return "Clean slate — no work in flight."
        parts = []
        by_kind: dict[str, list[ConsciousnessEntity]] = {}
        for e in active:
            by_kind.setdefault(e.kind, []).append(e)
        for kind, items in by_kind.items():
            if len(items) == 1:
                it = items[0]
                parts.append(f"{kind}: {it.summary or it.id[:8]} ({it.status})")
            else:
                names = ", ".join(i.summary or i.id[:8] for i in items[:3])
                parts.append(f"{len(items)} {kind}s ({names})")
        return "You were working on: " + "; ".join(parts) + "."

    # ------------------------------------------------------------------
    # Convenience helpers for orchestrator/flow/intent integration
    # ------------------------------------------------------------------

    def record_intent(self, *, intent_id: str, summary: str, session_id: Optional[str], plan: Optional[dict] = None) -> ConsciousnessEntity:
        return self.record(ConsciousnessEntity(
            id=intent_id,
            kind="intent",
            owner_session_id=session_id,
            status="active",
            summary=summary,
            context_json={"plan": plan or {}},
            ttl_seconds=24 * 3600,
        ))

    def record_flow(self, *, flow_id: str, title: str, step: int, steps: int, session_id: Optional[str]) -> ConsciousnessEntity:
        return self.record(ConsciousnessEntity(
            id=flow_id,
            kind="flow",
            owner_session_id=session_id,
            status="active",
            summary=title,
            context_json={"step": step, "steps": steps},
            ttl_seconds=6 * 3600,
        ))

    def record_thought(self, *, thought_id: str, session_id: str, text: str) -> ConsciousnessEntity:
        return self.record(ConsciousnessEntity(
            id=thought_id,
            kind="thought",
            owner_session_id=session_id,
            status="paused",
            summary=text[:120],
            context_json={"text": text},
            ttl_seconds=30 * 60,
        ))


def default_consciousness_db_path() -> Path:
    """Canonical location: ``$FERAL_HOME/consciousness.sqlite``."""
    import os
    home = Path(os.environ.get("FERAL_HOME") or (Path.home() / ".feral"))
    return home / "consciousness.sqlite"


def default_snapshot_path() -> Path:
    """Snapshot JSON location used by Brain boot/shutdown."""
    import os
    home = Path(os.environ.get("FERAL_HOME") or (Path.home() / ".feral"))
    return home / "consciousness.json"
