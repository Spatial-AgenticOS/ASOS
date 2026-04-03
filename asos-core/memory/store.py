"""
THEORA Memory System — 4-Tier Cognitive Architecture
======================================================
Implements the Vision.md memory layer:

  ┌─────────────────────────────────────┐
  │  Working Memory (current session)   │  ← volatile, per-session
  │  Episodic Memory (past events)      │  ← timestamped, decayable
  │  Semantic Memory (permanent facts)  │  ← knowledge graph entries
  │  Execution Log (learns from actions)│  ← every skill invocation
  └─────────────────────────────────────┘

All tiers share one SQLite database.  Working memory also lives in-RAM
for sub-millisecond access during the agentic loop.
"""

from __future__ import annotations
import json
import logging
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Optional
from uuid import uuid4

logger = logging.getLogger("theora.memory")

_SCHEMA_VERSION = 2


class MemoryStore:
    """
    The full THEORA memory layer.

    Tier 1 — Working Memory : in-RAM per-session context window
    Tier 2 — Episodic Memory: timestamped events (conversations, observations)
    Tier 3 — Semantic Memory : permanent knowledge / user facts
    Tier 4 — Execution Log  : every skill call with outcome
    Tier 0 — Notes (legacy) : backward-compatible simple notes
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = Path.home() / ".theora"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "memory.db")

        self.db_path = db_path

        # Tier 1: in-RAM working memory per session
        self._working: dict[str, deque[dict]] = {}
        self._working_max = 50  # messages per session

        self._init_db()
        logger.info(f"Memory store v{_SCHEMA_VERSION} initialized at {self.db_path}")

    # ─────────────────────────────────────────────
    # Schema
    # ─────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)

        # Tier 0: Legacy notes (backward-compat)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                importance TEXT DEFAULT 'normal',
                source TEXT DEFAULT 'user',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
            USING fts5(content, tags, tokenize='porter')
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                DELETE FROM notes_fts WHERE rowid = old.rowid;
            END
        """)

        # Tier 2: Episodic Memory
        conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                detail TEXT DEFAULT '',
                emotions TEXT DEFAULT '[]',
                location TEXT DEFAULT '',
                participants TEXT DEFAULT '[]',
                importance REAL DEFAULT 0.5,
                created_at REAL NOT NULL,
                decay_factor REAL DEFAULT 1.0
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
            USING fts5(summary, detail, tokenize='porter')
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(rowid, summary, detail)
                VALUES (new.rowid, new.summary, new.detail);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
                DELETE FROM episodes_fts WHERE rowid = old.rowid;
            END
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(created_at DESC)")

        # Tier 3: Semantic Memory (permanent knowledge graph entries)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source TEXT DEFAULT 'user',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
            USING fts5(subject, predicate, object, tokenize='porter')
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
                INSERT INTO knowledge_fts(rowid, subject, predicate, object)
                VALUES (new.rowid, new.subject, new.predicate, new.object);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
                DELETE FROM knowledge_fts WHERE rowid = old.rowid;
            END
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_subject ON knowledge(subject)")

        # Tier 4: Execution Log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_log (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                endpoint_id TEXT NOT NULL,
                args TEXT DEFAULT '{}',
                result_status TEXT NOT NULL,
                result_summary TEXT DEFAULT '',
                latency_ms REAL DEFAULT 0,
                user_feedback TEXT DEFAULT '',
                created_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_execlog_skill ON execution_log(skill_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_execlog_time ON execution_log(created_at DESC)")

        conn.commit()
        conn.close()

    # ─────────────────────────────────────────────
    # Tier 1: Working Memory (in-RAM)
    # ─────────────────────────────────────────────

    def working_push(self, session_id: str, entry: dict):
        """Push an entry into the session's working memory."""
        if session_id not in self._working:
            self._working[session_id] = deque(maxlen=self._working_max)
        self._working[session_id].append({**entry, "ts": time.time()})

    def working_get(self, session_id: str, limit: int = 20) -> list[dict]:
        """Retrieve recent working memory for a session."""
        buf = self._working.get(session_id, deque())
        items = list(buf)
        return items[-limit:]

    def working_context_string(self, session_id: str, limit: int = 10) -> str:
        """Build a compact string summary of recent working memory for LLM injection."""
        entries = self.working_get(session_id, limit)
        if not entries:
            return ""
        lines = []
        for e in entries:
            role = e.get("role", "system")
            text = e.get("text", e.get("summary", ""))[:200]
            if text:
                lines.append(f"[{role}] {text}")
        return "\n".join(lines)

    def working_clear(self, session_id: str):
        self._working.pop(session_id, None)

    # ─────────────────────────────────────────────
    # Tier 2: Episodic Memory
    # ─────────────────────────────────────────────

    def episode_save(
        self,
        session_id: str,
        event_type: str,
        summary: str,
        detail: str = "",
        emotions: list[str] | None = None,
        location: str = "",
        participants: list[str] | None = None,
        importance: float = 0.5,
    ) -> dict:
        """Record an episodic memory (conversation, observation, event)."""
        eid = str(uuid4())[:12]
        now = time.time()
        emotions = emotions or []
        participants = participants or []

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO episodes
               (id, session_id, event_type, summary, detail, emotions, location, participants, importance, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, session_id, event_type, summary, detail,
             json.dumps(emotions), location, json.dumps(participants), importance, now),
        )
        conn.commit()
        conn.close()
        logger.info(f"Episode saved: [{event_type}] {summary[:60]}")
        return {"id": eid, "event_type": event_type, "summary": summary, "created_at": now}

    def episode_search(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across episodic memories."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT e.id, e.session_id, e.event_type, e.summary, e.detail,
                          e.emotions, e.location, e.importance, e.created_at, e.decay_factor
                   FROM episodes_fts f
                   JOIN episodes e ON f.rowid = e.rowid
                   WHERE episodes_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                """SELECT id, session_id, event_type, summary, detail,
                          emotions, location, importance, created_at, decay_factor
                   FROM episodes WHERE summary LIKE ? OR detail LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        conn.close()
        return [self._episode_row_to_dict(r) for r in rows]

    def episode_recent(self, limit: int = 10, session_id: str = None) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if session_id:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
        conn.close()
        return [self._episode_row_to_dict(r) for r in rows]

    @staticmethod
    def _episode_row_to_dict(row) -> dict:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "event_type": row["event_type"],
            "summary": row["summary"],
            "detail": row["detail"],
            "emotions": json.loads(row["emotions"]),
            "location": row["location"],
            "importance": row["importance"],
            "created_at": row["created_at"],
            "decay_factor": row["decay_factor"],
        }

    # ─────────────────────────────────────────────
    # Tier 3: Semantic Memory (Knowledge Graph)
    # ─────────────────────────────────────────────

    def knowledge_store(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float = 1.0,
        source: str = "user",
    ) -> dict:
        """Store or update a knowledge triple (subject, predicate, object).
        If the same subject+predicate exists, update the object."""
        conn = sqlite3.connect(self.db_path)
        now = time.time()

        existing = conn.execute(
            "SELECT id FROM knowledge WHERE subject = ? AND predicate = ?",
            (subject, predicate),
        ).fetchone()

        if existing:
            kid = existing[0]
            conn.execute(
                "UPDATE knowledge SET object = ?, confidence = ?, source = ?, updated_at = ? WHERE id = ?",
                (obj, confidence, source, now, kid),
            )
            # Re-sync FTS
            conn.execute("DELETE FROM knowledge_fts WHERE rowid = (SELECT rowid FROM knowledge WHERE id = ?)", (kid,))
            conn.execute(
                "INSERT INTO knowledge_fts(rowid, subject, predicate, object) "
                "SELECT rowid, subject, predicate, object FROM knowledge WHERE id = ?", (kid,),
            )
        else:
            kid = str(uuid4())[:12]
            conn.execute(
                """INSERT INTO knowledge (id, subject, predicate, object, confidence, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (kid, subject, predicate, obj, confidence, source, now, now),
            )

        conn.commit()
        conn.close()
        logger.info(f"Knowledge: ({subject}) --[{predicate}]--> ({obj})")
        return {"id": kid, "subject": subject, "predicate": predicate, "object": obj}

    def knowledge_query(self, subject: str = "", predicate: str = "", limit: int = 20) -> list[dict]:
        """Query the knowledge graph by subject and/or predicate."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        conditions, params = [], []
        if subject:
            conditions.append("subject = ?")
            params.append(subject)
        if predicate:
            conditions.append("predicate = ?")
            params.append(predicate)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM knowledge {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        conn.close()

        return [
            {
                "id": r["id"], "subject": r["subject"], "predicate": r["predicate"],
                "object": r["object"], "confidence": r["confidence"], "source": r["source"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def knowledge_search(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across all knowledge triples."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT k.* FROM knowledge_fts f
                   JOIN knowledge k ON f.rowid = k.rowid
                   WHERE knowledge_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                """SELECT * FROM knowledge
                   WHERE subject LIKE ? OR object LIKE ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        conn.close()

        return [
            {
                "id": r["id"], "subject": r["subject"], "predicate": r["predicate"],
                "object": r["object"], "confidence": r["confidence"],
            }
            for r in rows
        ]

    def knowledge_about(self, entity: str, limit: int = 20) -> list[dict]:
        """Retrieve everything known about an entity (as subject or object)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM knowledge
               WHERE subject = ? OR object = ?
               ORDER BY confidence DESC, updated_at DESC LIMIT ?""",
            (entity, entity, limit),
        ).fetchall()
        conn.close()
        return [
            {"subject": r["subject"], "predicate": r["predicate"], "object": r["object"],
             "confidence": r["confidence"]}
            for r in rows
        ]

    # ─────────────────────────────────────────────
    # Tier 4: Execution Log
    # ─────────────────────────────────────────────

    def log_execution(
        self,
        session_id: str,
        skill_id: str,
        endpoint_id: str,
        args: dict,
        result_status: str,
        result_summary: str = "",
        latency_ms: float = 0,
    ) -> str:
        """Record a skill execution for learning and auditing."""
        eid = str(uuid4())[:12]
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO execution_log
               (id, session_id, skill_id, endpoint_id, args, result_status, result_summary, latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, session_id, skill_id, endpoint_id, json.dumps(args)[:2000],
             result_status, result_summary[:500], latency_ms, now),
        )
        conn.commit()
        conn.close()
        return eid

    def log_feedback(self, execution_id: str, feedback: str):
        """Attach user feedback to a past execution."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE execution_log SET user_feedback = ? WHERE id = ?",
            (feedback[:500], execution_id),
        )
        conn.commit()
        conn.close()

    def log_recent(self, skill_id: str = "", limit: int = 20) -> list[dict]:
        """Retrieve recent execution logs, optionally filtered by skill."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if skill_id:
            rows = conn.execute(
                "SELECT * FROM execution_log WHERE skill_id = ? ORDER BY created_at DESC LIMIT ?",
                (skill_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM execution_log ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def log_success_rate(self, skill_id: str) -> dict:
        """Calculate success rate for a skill from the execution log."""
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(*) FROM execution_log WHERE skill_id = ?", (skill_id,),
        ).fetchone()[0]
        successes = conn.execute(
            "SELECT COUNT(*) FROM execution_log WHERE skill_id = ? AND result_status = 'success'",
            (skill_id,),
        ).fetchone()[0]
        conn.close()
        return {
            "skill_id": skill_id,
            "total_executions": total,
            "successes": successes,
            "rate": successes / total if total > 0 else 0.0,
        }

    # ─────────────────────────────────────────────
    # Unified Context Builder (for LLM injection)
    # ─────────────────────────────────────────────

    def build_context_for_llm(self, session_id: str, query: str = "", max_tokens_budget: int = 2000) -> str:
        """
        Build a unified memory context string for LLM system prompt injection.
        Pulls from all 4 tiers based on relevance and recency.
        """
        sections = []
        budget_per_section = max_tokens_budget // 4

        # Working Memory
        working = self.working_context_string(session_id, limit=8)
        if working:
            sections.append(f"## Recent Context\n{working[:budget_per_section]}")

        # Relevant Knowledge
        if query:
            knowledge = self.knowledge_search(query, limit=5)
            if knowledge:
                k_lines = [f"- {k['subject']} {k['predicate']} {k['object']}" for k in knowledge]
                sections.append(f"## Known Facts\n" + "\n".join(k_lines)[:budget_per_section])

        # Relevant Episodes
        if query:
            episodes = self.episode_search(query, limit=3)
        else:
            episodes = self.episode_recent(limit=3, session_id=session_id)
        if episodes:
            ep_lines = [f"- [{e['event_type']}] {e['summary']}" for e in episodes]
            sections.append(f"## Past Events\n" + "\n".join(ep_lines)[:budget_per_section])

        # Recent Execution Patterns
        recent_execs = self.log_recent(limit=5)
        if recent_execs:
            ex_lines = []
            for ex in recent_execs:
                status = ex.get("result_status", "?")
                skill = ex.get("skill_id", "?")
                ex_lines.append(f"- {skill}: {status}")
            sections.append(f"## Recent Actions\n" + "\n".join(ex_lines)[:budget_per_section])

        return "\n\n".join(sections) if sections else ""

    # ─────────────────────────────────────────────
    # Legacy Notes API (backward compatibility)
    # ─────────────────────────────────────────────

    def save(self, content: str, tags: list[str] = None, importance: str = "normal", source: str = "user") -> dict:
        note_id = str(uuid4())[:8]
        now = time.time()
        tags = tags or []
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO notes (id, content, tags, importance, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (note_id, content, json.dumps(tags), importance, source, now, now),
        )
        conn.commit()
        conn.close()
        # Also store as semantic knowledge for cross-tier retrieval
        self.knowledge_store(subject="user_note", predicate="says", obj=content[:300], source="notes")
        logger.info(f"Saved note {note_id}: {content[:80]}...")
        return {"id": note_id, "content": content, "tags": tags, "importance": importance, "created_at": now, "status": "saved"}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT n.id, n.content, n.tags, n.importance, n.created_at, rank as relevance_score
                   FROM notes_fts f JOIN notes n ON f.rowid = n.rowid
                   WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT id, content, tags, importance, created_at, 0.5 as relevance_score FROM notes WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        conn.close()
        return [
            {"id": r["id"], "content": r["content"], "tags": json.loads(r["tags"]),
             "importance": r["importance"], "created_at": r["created_at"], "relevance_score": abs(r["relevance_score"])}
            for r in rows
        ]

    def list_recent(self, limit: int = 10) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, content, tags, importance, created_at FROM notes ORDER BY created_at DESC LIMIT ?", (limit,),
        ).fetchall()
        conn.close()
        return [
            {"id": r["id"], "content": r["content"], "tags": json.loads(r["tags"]),
             "importance": r["importance"], "created_at": r["created_at"]}
            for r in rows
        ]

    def delete(self, note_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        conn.close()
        return count

    def stats(self) -> dict:
        """Return aggregate stats across all memory tiers."""
        conn = sqlite3.connect(self.db_path)
        notes_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        episodes_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        knowledge_count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        exec_count = conn.execute("SELECT COUNT(*) FROM execution_log").fetchone()[0]
        working_sessions = len(self._working)
        conn.close()
        return {
            "notes": notes_count,
            "episodes": episodes_count,
            "knowledge_triples": knowledge_count,
            "execution_logs": exec_count,
            "active_working_sessions": working_sessions,
        }
