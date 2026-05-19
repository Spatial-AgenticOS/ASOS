"""
FERAL Memory System — Production Cognitive Architecture
=========================================================
4-tier memory with real vector search, hybrid ranking, temporal decay,
multi-stage compaction, and knowledge graph integration.

  ┌─────────────────────────────────────┐
  │  Working Memory (current session)   │  ← volatile, per-session
  │  Episodic Memory (past events)      │  ← timestamped, decayable, embedded
  │  Semantic Memory (knowledge graph)  │  ← entity-linked graph
  │  Execution Log (learns from actions)│  ← every skill invocation
  └─────────────────────────────────────┘

Hybrid search: FTS5 text (weight 0.3) + vector similarity (weight 0.7)
with MMR diversity reranking and temporal decay.
"""

from __future__ import annotations
import json
import logging
import math
import sqlite3
import time
from collections import deque
from typing import Optional
from uuid import uuid4

from config.loader import feral_data_home
from memory.context_builder import (
    build_context_for_llm as context_build_context_for_llm,
    build_context_for_llm_async as context_build_context_for_llm_async,
    compact_session as context_compact_session,
    heuristic_summarize as context_heuristic_summarize,
    llm_summarize as context_llm_summarize,
    search_all as context_search_all,
)
from memory.embeddings import (
    EmbeddingProvider,
    EmbedQueue,
    chunk_text,
    blob_to_vec,
    cosine_similarity,
)
from memory.vector_index_backends import VectorIndexBackend
from memory.notes_legacy import (
    count_notes,
    delete_note,
    list_recent_notes,
    save_note,
    search_notes,
)
from memory.wiki import (
    wiki_compile as helper_wiki_compile,
    wiki_get_page as helper_wiki_get_page,
    wiki_list_pages as helper_wiki_list_pages,
    wiki_slug as helper_wiki_slug,
    wiki_stats as helper_wiki_stats,
    wiki_upsert_page as helper_wiki_upsert_page,
)

logger = logging.getLogger("feral.memory")

_SCHEMA_VERSION = 5

TEXT_WEIGHT = 0.3
VECTOR_WEIGHT = 0.7
DEFAULT_DECAY_RATE = 0.01


class MemoryStore:
    """
    The full FERAL memory layer with vector search, hybrid ranking,
    temporal decay, and multi-stage compaction.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        vec_index: Optional[VectorIndexBackend] = None,
    ):
        """Construct a MemoryStore.

        Parameters
        ----------
        db_path :
            SQLite DB path. Defaults to ``~/.feral/memory.db``.
        vec_index :
            Pluggable vector index backend conforming to
            :class:`memory.vector_index_backends.VectorIndexBackend`.
            If ``None``, defaults to the sqlite-vec backend (which is
            what FERAL has always shipped). ``BrainState.__init__``
            reads ``settings.memory.backend`` and injects the
            configured backend here — selecting ``chroma`` or
            ``qdrant`` in settings.yaml swaps this end-to-end.

            audit-r12 D4: pre-r12 this was hardwired to ``VectorIndex``
            (sqlite-vec only); ``settings.memory.backend`` was defined
            but read nowhere. The injection point closes that loop.
        """
        if db_path is None:
            data_dir = feral_data_home()
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "memory.db")

        self.db_path = db_path
        self._working: dict[str, deque[dict]] = {}
        self._working_max = 50
        self._working_max_sessions = 500
        self._sync_engine = None
        self._about_me_store = None
        self._embedder = EmbeddingProvider()
        self._kg = None

        self._init_db()

        if vec_index is None:
            # Default sqlite-vec backend — same behaviour as pre-r12,
            # just routed through the Protocol-typed selector. Other
            # backends (Chroma, Qdrant) are injected from BrainState
            # based on settings.memory.backend.
            from memory.vector_index_backends.sqlite_vec import SQLiteVecIndex
            vec_index = SQLiteVecIndex(
                dim=self._embedder.dimension,
                db_path=self.db_path,
                table_name="vec_chunks",
            )
        self._vec_index: VectorIndexBackend = vec_index
        # EmbedQueue writes vectors via the same ``upsert(chunk_id, vec)``
        # surface every VectorIndexBackend satisfies — so it works
        # uniformly with sqlite-vec, Chroma, or Qdrant. The queue's
        # other job (writing chunk text to the FTS5 ``memory_chunks``
        # table for keyword search) stays SQLite-specific and is
        # independent of the chosen vector backend.
        self._embed_queue = EmbedQueue(self._embedder, vec_index)
        # Remember the backend id for stats / logging — useful when the
        # operator is debugging "where did my vectors go".
        self._backend_id = getattr(vec_index, "backend_id", "unknown")

        self._init_knowledge_graph()
        if self._backend_id == "sqlite_vec":
            index_mode = "sqlite-vec (vec0)" if vec_index.indexed else "numpy fallback"
        else:
            index_mode = f"{self._backend_id} (indexed={vec_index.indexed}, count={vec_index.count})"
        logger.info(
            "Memory store v%d at %s | embeddings: %s | index: %s",
            _SCHEMA_VERSION, self.db_path, self._embedder.provider_name, index_mode,
        )

    def start_background_tasks(self):
        """Start the embed queue processor. Call after event loop is running."""
        self._embed_queue.start()
        logger.info("Embed queue started")

    def _init_knowledge_graph(self):
        try:
            from memory.knowledge_graph import KnowledgeGraph
            self._kg = KnowledgeGraph(self.db_path, self._embedder)
            kg_stats = self._kg.stats()
            logger.info(f"Knowledge graph: {kg_stats['entities']} entities, {kg_stats['relations']} relations")
        except Exception as e:
            logger.warning(f"Knowledge graph init failed: {e}")

    @property
    def kg(self):
        return self._kg

    @property
    def embedder(self) -> EmbeddingProvider:
        return self._embedder

    def set_sync_engine(self, engine):
        self._sync_engine = engine

    def set_about_me_store(self, about_me_store):
        """Attach an AboutMeStore so episode_save can auto-extract self-facts.

        The store reference stays optional — unit tests instantiate a bare
        MemoryStore without an about_me store attached, and both tiers work
        independently.
        """
        self._about_me_store = about_me_store

    def _log_sync(self, table: str, op_type: str, row_id: str, data: dict):
        if self._sync_engine:
            self._sync_engine.log_operation(table, op_type, row_id, data)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ─────────────────────────────────────────────
    # Schema
    # ─────────────────────────────────────────────

    def close(self):
        """Shut down background tasks and release resources."""
        try:
            self._embed_queue.stop()
        except Exception:
            pass

    def refresh(self) -> dict:
        """Re-validate the on-disk memory + sync WAL after suspected corruption.

        Returns a dict shaped like:
            {"ok": True, "memory_db": "ok", "sync_wal": "ok"}                       # healthy
            {"ok": False, "error": "wal_corruption", "memory_db": "...", "sync_wal": "..."}  # recoverable

        The caller (UI banner, sync_with_peer pre-flight, chaos test) is
        expected to refuse to apply remote changes until refresh() returns
        ok=True. The function never raises — it always returns a dict so
        the failure mode is "surface the error", never "crash the brain".
        """
        result: dict = {"ok": True}

        # Memory DB integrity check. We open a dedicated connection so a
        # corruption error doesn't poison the long-lived store connections.
        memory_status = "ok"
        memory_detail = ""
        try:
            conn = sqlite3.connect(self.db_path)
        except sqlite3.Error as exc:
            memory_status = "open_failed"
            memory_detail = str(exc)
        else:
            try:
                rows = conn.execute("PRAGMA integrity_check").fetchall()
                statuses = [r[0] for r in rows] if rows else []
                if statuses != ["ok"]:
                    memory_status = "corruption"
                    memory_detail = "; ".join(statuses) or "integrity_check returned no rows"
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
                memory_status = "corruption"
                memory_detail = str(exc)
            finally:
                conn.close()
        result["memory_db"] = memory_status
        if memory_status != "ok":
            result["memory_db_detail"] = memory_detail
            result["ok"] = False
            result["error"] = "memory_db_corruption"

        # Sync WAL integrity check, only if a SyncEngine is attached.
        if self._sync_engine is not None:
            try:
                wal_check = self._sync_engine._wal.integrity_check()
            except Exception as exc:
                wal_check = {"ok": False, "error": "wal_check_raised", "detail": str(exc)}
            if wal_check.get("ok"):
                result["sync_wal"] = "ok"
            else:
                result["sync_wal"] = wal_check.get("error", "wal_corruption")
                result["sync_wal_detail"] = wal_check.get("detail", "")
                result["ok"] = False
                result["error"] = wal_check.get("error", "wal_corruption")

        return result

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
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
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE ON notes BEGIN
                    DELETE FROM notes_fts WHERE rowid = old.rowid;
                    INSERT INTO notes_fts(rowid, content, tags) VALUES (new.rowid, new.content, new.tags);
                END
            """)

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
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS knowledge_fts_update AFTER UPDATE ON knowledge BEGIN
                    DELETE FROM knowledge_fts WHERE rowid = old.rowid;
                    INSERT INTO knowledge_fts(rowid, subject, predicate, object) VALUES (new.rowid, new.subject, new.predicate, new.object);
                END
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_subject ON knowledge(subject)")

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

            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id TEXT PRIMARY KEY,
                    source_table TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    chunk_index INTEGER DEFAULT 0,
                    text_content TEXT NOT NULL,
                    embedding BLOB,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON memory_chunks(source_table, source_id)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS wiki_pages (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    body_markdown TEXT NOT NULL,
                    source_refs TEXT DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_wiki_kind ON wiki_pages(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_wiki_updated ON wiki_pages(updated_at DESC)")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_pages_fts
                USING fts5(title, body_markdown, tokenize='porter')
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS wiki_pages_ai AFTER INSERT ON wiki_pages BEGIN
                    INSERT INTO wiki_pages_fts(rowid, title, body_markdown)
                    VALUES (new.rowid, new.title, new.body_markdown);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS wiki_pages_au AFTER UPDATE ON wiki_pages BEGIN
                    DELETE FROM wiki_pages_fts WHERE rowid = old.rowid;
                    INSERT INTO wiki_pages_fts(rowid, title, body_markdown)
                    VALUES (new.rowid, new.title, new.body_markdown);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS wiki_pages_ad AFTER DELETE ON wiki_pages BEGIN
                    DELETE FROM wiki_pages_fts WHERE rowid = old.rowid;
                END
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_snapshots (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    branch_name TEXT NOT NULL DEFAULT 'main',
                    label TEXT NOT NULL DEFAULT '',
                    working_json TEXT NOT NULL DEFAULT '[]',
                    history_json TEXT NOT NULL DEFAULT '[]',
                    source_snapshot_id TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_session ON session_snapshots(session_id, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_branch ON session_snapshots(branch_name, created_at DESC)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New conversation',
                    preview TEXT NOT NULL DEFAULT '',
                    messages_json TEXT NOT NULL DEFAULT '[]',
                    message_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC)")

            conn.commit()
        finally:
            conn.close()

    # ─────────────────────────────────────────────
    # Tier 1: Working Memory (in-RAM)
    # ─────────────────────────────────────────────

    def working_push(self, session_id: str, entry: dict):
        if session_id not in self._working:
            if len(self._working) >= self._working_max_sessions:
                oldest = min(self._working, key=lambda s: self._working[s][-1]["ts"] if self._working[s] else 0)
                del self._working[oldest]
            self._working[session_id] = deque(maxlen=self._working_max)
        self._working[session_id].append({**entry, "ts": time.time()})

    def working_get(self, session_id: str, limit: int = 20) -> list[dict]:
        buf = self._working.get(session_id, deque())
        return list(buf)[-limit:]

    def working_context_string(self, session_id: str, limit: int = 10) -> str:
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

    def working_replace(self, session_id: str, entries: list[dict]):
        buf = deque(maxlen=self._working_max)
        for item in entries[-self._working_max:]:
            entry = dict(item)
            entry.setdefault("ts", time.time())
            buf.append(entry)
        self._working[session_id] = buf

    # ─────────────────────────────────────────────
    # Conversation Threads (persistent chat history)
    # ─────────────────────────────────────────────

    def conversation_save(self, conversation_id: str, messages: list[dict], title: str = "") -> dict:
        """Save/update a conversation thread."""
        now = time.time()
        preview = ""
        for msg in reversed(messages):
            if msg.get("role") == "user" and msg.get("content"):
                preview = msg["content"][:120]
                break
        if not title and messages:
            for msg in messages:
                if msg.get("role") == "user" and msg.get("content"):
                    title = msg["content"][:80]
                    break
        title = title or "New conversation"

        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO conversations (id, title, preview, messages_json, message_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    preview = excluded.preview,
                    messages_json = excluded.messages_json,
                    message_count = excluded.message_count,
                    updated_at = excluded.updated_at
            """, (conversation_id, title, preview, json.dumps(messages[-500:]), len(messages), now, now))
            conn.commit()
        finally:
            conn.close()
        return {"id": conversation_id, "title": title, "message_count": len(messages), "updated_at": now}

    def conversation_append(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        source: str = "",
        title: str = "",
    ) -> dict:
        """Append a single message to an existing conversation or
        create-and-append if the conversation doesn't exist.

        PR 9 gap-fill: voice realtime proxies call this on every final
        transcript so the conversation list shows voice sessions next
        to chat threads — not just live-only events that disappear on
        reconnect. The ``source`` field carries the channel id
        (``voice_realtime_openai``, ``voice_realtime_gemini``) so the
        UI can render a small badge on voice threads.
        """
        existing = self.conversation_get(conversation_id) or {}
        messages = list(existing.get("messages", []) or [])
        messages.append({
            "id": f"m_{int(time.time() * 1000)}_{len(messages)}",
            "role": role,
            "content": content,
            "source": source,
            "ts": time.time(),
        })
        return self.conversation_save(
            conversation_id, messages, title=title or existing.get("title", ""),
        )

    def conversation_list(self, limit: int = 50) -> list[dict]:
        """List recent conversations (metadata only)."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, title, preview, message_count, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (min(limit, 200),),
            ).fetchall()
        finally:
            conn.close()
        return [
            {"id": r[0], "title": r[1], "preview": r[2], "message_count": r[3], "created_at": r[4], "updated_at": r[5]}
            for r in rows
        ]

    def conversation_get(self, conversation_id: str) -> dict | None:
        """Load a full conversation with messages."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT id, title, preview, messages_json, message_count, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "id": row[0], "title": row[1], "preview": row[2],
            "messages": json.loads(row[3]) if row[3] else [],
            "message_count": row[4], "created_at": row[5], "updated_at": row[6],
        }

    def conversation_delete(self, conversation_id: str) -> bool:
        conn = self._conn()
        try:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()
        finally:
            conn.close()
        return True

    def snapshot_session(
        self,
        *,
        session_id: str,
        history: list[dict],
        label: str = "",
        branch_name: str = "main",
        source_snapshot_id: str = "",
    ) -> dict:
        snapshot_id = str(uuid4())[:12]
        now = time.time()
        working = list(self._working.get(session_id, deque()))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO session_snapshots
                (id, session_id, branch_name, label, working_json, history_json, source_snapshot_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    session_id,
                    branch_name or "main",
                    label or "",
                    json.dumps(working),
                    json.dumps(history[-200:]),
                    source_snapshot_id or None,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "snapshot_id": snapshot_id,
            "session_id": session_id,
            "branch_name": branch_name or "main",
            "label": label or "",
            "created_at": now,
            "working_count": len(working),
            "history_count": len(history),
            "source_snapshot_id": source_snapshot_id or None,
        }

    def list_snapshots(
        self,
        *,
        session_id: str = "",
        branch_name: str = "",
        limit: int = 50,
    ) -> list[dict]:
        lim = max(1, min(limit, 200))
        conn = self._conn()
        try:
            if session_id and branch_name:
                rows = conn.execute(
                    """
                    SELECT id, session_id, branch_name, label, source_snapshot_id, created_at
                    FROM session_snapshots
                    WHERE session_id = ? AND branch_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (session_id, branch_name, lim),
                ).fetchall()
            elif session_id:
                rows = conn.execute(
                    """
                    SELECT id, session_id, branch_name, label, source_snapshot_id, created_at
                    FROM session_snapshots
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (session_id, lim),
                ).fetchall()
            elif branch_name:
                rows = conn.execute(
                    """
                    SELECT id, session_id, branch_name, label, source_snapshot_id, created_at
                    FROM session_snapshots
                    WHERE branch_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (branch_name, lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, session_id, branch_name, label, source_snapshot_id, created_at
                    FROM session_snapshots
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
        finally:
            conn.close()
        return [
            {
                "snapshot_id": r["id"],
                "session_id": r["session_id"],
                "branch_name": r["branch_name"],
                "label": r["label"],
                "source_snapshot_id": r["source_snapshot_id"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get_snapshot(self, snapshot_id: str) -> Optional[dict]:
        conn = self._conn()
        try:
            row = conn.execute(
                """
                SELECT id, session_id, branch_name, label, working_json, history_json, source_snapshot_id, created_at
                FROM session_snapshots
                WHERE id = ?
                """,
                (snapshot_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "snapshot_id": row["id"],
            "session_id": row["session_id"],
            "branch_name": row["branch_name"],
            "label": row["label"],
            "working": json.loads(row["working_json"] or "[]"),
            "history": json.loads(row["history_json"] or "[]"),
            "source_snapshot_id": row["source_snapshot_id"],
            "created_at": row["created_at"],
        }

    # ─────────────────────────────────────────────
    # Tier 2: Episodic Memory (with embeddings)
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
        eid = str(uuid4())[:12]
        now = time.time()
        emotions = emotions or []
        participants = participants or []

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT INTO episodes
                   (id, session_id, event_type, summary, detail, emotions, location, participants, importance, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, session_id, event_type, summary, detail,
                 json.dumps(emotions), location, json.dumps(participants), importance, now),
            )
            conn.commit()
        finally:
            conn.close()

        # Queue embedding reliably (retries on failure, updates vec index)
        text = f"{summary}\n{detail}".strip()
        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            self._embed_queue.enqueue(
                chunk_id=f"{eid}_c{i}", text=chunk,
                source_table="episodes", source_id=eid,
                chunk_index=i, db_path=self.db_path,
            )

        self._log_sync("episodes", "insert", eid, {
            "id": eid, "session_id": session_id, "event_type": event_type,
            "summary": summary, "detail": detail, "importance": importance, "created_at": now,
        })

        # Auto-suggest About Me facts from regex patterns in the episode text.
        # Every hit lands at confidence 0.5 / source=inferred_from_chat so
        # the user can confirm/reject via Settings → Self → About Me.
        if self._about_me_store is not None and text:
            try:
                self._about_me_store.extract_from_text(text)
            except Exception as exc:
                logger.debug("AboutMe auto-extractor failed silently: %s", exc)

        return {"id": eid, "event_type": event_type, "summary": summary, "created_at": now}

    async def episode_search_hybrid(self, query: str, limit: int = 10) -> list[dict]:
        """
        Hybrid search: FTS5 text (0.3) + vector similarity (0.7) with temporal decay.
        Uses sqlite-vec indexed search when available, numpy fallback otherwise.
        """
        conn = self._conn()
        try:
            # Phase 1: FTS5 text search
            fts_results = {}
            try:
                rows = conn.execute(
                    """SELECT e.id, e.session_id, e.event_type, e.summary, e.detail,
                              e.emotions, e.location, e.importance, e.created_at, e.decay_factor, rank
                       FROM episodes_fts f JOIN episodes e ON f.rowid = e.rowid
                       WHERE episodes_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (query, limit * 3),
                ).fetchall()
                for r in rows:
                    fts_results[r["id"]] = {
                        **self._episode_row_to_dict(r),
                        "fts_score": 1.0 / (1.0 + abs(r["rank"])),
                    }
            except Exception:
                pass

            # Phase 2: Vector search (indexed or fallback)
            vec_results = {}
            try:
                query_vec = await self._embedder.embed(query)

                if self._vec_index.indexed:
                    # O(log n) indexed search via sqlite-vec
                    hits = self._vec_index.search_cosine(query_vec, limit=limit * 3)
                    for chunk_id, sim in hits:
                        if sim < 0.25:
                            continue
                        eid = chunk_id.rsplit("_c", 1)[0]
                        if eid not in vec_results or sim > vec_results[eid]["vec_score"]:
                            vec_results[eid] = {"id": eid, "vec_score": sim}
                else:
                    # O(n) brute-force fallback
                    chunks = conn.execute(
                        "SELECT source_id, embedding FROM memory_chunks "
                        "WHERE source_table = 'episodes' AND embedding IS NOT NULL"
                    ).fetchall()
                    for c in chunks:
                        evec = blob_to_vec(c["embedding"])
                        sim = cosine_similarity(query_vec, evec)
                        eid = c["source_id"]
                        if sim > 0.25 and (eid not in vec_results or sim > vec_results[eid]["vec_score"]):
                            vec_results[eid] = {"id": eid, "vec_score": sim}
            except Exception as e:
                logger.debug(f"Vector search failed: {e}")

            # Phase 3: Merge + temporal decay + rank
            all_ids = set(fts_results.keys()) | set(vec_results.keys())
            episode_cache = {}
            if all_ids - set(fts_results.keys()):
                missing = all_ids - set(fts_results.keys())
                placeholders = ",".join("?" for _ in missing)
                rows = conn.execute(
                    f"SELECT * FROM episodes WHERE id IN ({placeholders})", list(missing),
                ).fetchall()
                for r in rows:
                    episode_cache[r["id"]] = self._episode_row_to_dict(r)
        finally:
            conn.close()
        now = time.time()
        merged = []
        for eid in all_ids:
            info = fts_results.get(eid) or episode_cache.get(eid)
            if not info:
                continue

            fts_score = fts_results.get(eid, {}).get("fts_score", 0)
            vec_score = vec_results.get(eid, {}).get("vec_score", 0)
            base_score = TEXT_WEIGHT * fts_score + VECTOR_WEIGHT * vec_score

            hours_since = (now - info.get("created_at", now)) / 3600.0
            decay = info.get("decay_factor", 1.0)
            temporal_factor = math.exp(-DEFAULT_DECAY_RATE * decay * hours_since)
            final_score = base_score * temporal_factor

            info["relevance_score"] = final_score
            merged.append(info)

        merged.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return self._mmr_rerank_episodes(merged, limit)

    def episode_search(self, query: str, limit: int = 10) -> list[dict]:
        """Synchronous FTS-only search (backward compat)."""
        conn = self._conn()
        try:
            try:
                rows = conn.execute(
                    """SELECT e.* FROM episodes_fts f
                       JOIN episodes e ON f.rowid = e.rowid
                       WHERE episodes_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (query, limit),
                ).fetchall()
            except Exception:
                rows = conn.execute(
                    """SELECT * FROM episodes WHERE summary LIKE ? OR detail LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
        finally:
            conn.close()
        return [self._episode_row_to_dict(r) for r in rows]

    def episode_recent(self, limit: int = 10, session_id: str = None) -> list[dict]:
        conn = self._conn()
        try:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM episodes WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM episodes ORDER BY created_at DESC LIMIT ?", (limit,),
                ).fetchall()
        finally:
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
            "emotions": json.loads(row["emotions"]) if isinstance(row["emotions"], str) else row["emotions"],
            "location": row["location"],
            "importance": row["importance"],
            "created_at": row["created_at"],
            "decay_factor": row["decay_factor"],
        }

    @staticmethod
    def _mmr_rerank_episodes(results: list[dict], limit: int, diversity: float = 0.3) -> list[dict]:
        if len(results) <= limit:
            return results
        selected = [results[0]]
        remaining = results[1:]
        while len(selected) < limit and remaining:
            best_idx = 0
            best_score = -999
            for i, cand in enumerate(remaining):
                relevance = cand.get("relevance_score", 0)
                max_overlap = max(
                    (0.5 if c.get("session_id") == cand.get("session_id") else 0.0)
                    for c in selected
                )
                mmr = (1.0 - diversity) * relevance - diversity * max_overlap
                if mmr > best_score:
                    best_score = mmr
                    best_idx = i
            selected.append(remaining.pop(best_idx))
        return selected

    # ─────────────────────────────────────────────
    # Tier 3: Semantic Memory (Knowledge Graph + Legacy Triples)
    # ─────────────────────────────────────────────

    def knowledge_store(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float = 1.0,
        source: str = "user",
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        now = time.time()
        try:
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
            else:
                kid = str(uuid4())[:12]
                conn.execute(
                    """INSERT INTO knowledge (id, subject, predicate, object, confidence, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (kid, subject, predicate, obj, confidence, source, now, now),
                )

            conn.commit()
        finally:
            conn.close()
        self._log_sync("knowledge", "insert", kid, {
            "id": kid, "subject": subject, "predicate": predicate, "object": obj,
            "confidence": confidence, "source": source, "created_at": now,
        })
        return {"id": kid, "subject": subject, "predicate": predicate, "object": obj}

    def knowledge_query(self, subject: str = "", predicate: str = "", limit: int = 20) -> list[dict]:
        conn = self._conn()
        try:
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
        finally:
            conn.close()
        return [
            {"id": r["id"], "subject": r["subject"], "predicate": r["predicate"],
             "object": r["object"], "confidence": r["confidence"], "source": r["source"],
             "updated_at": r["updated_at"]}
            for r in rows
        ]

    def knowledge_search(self, query: str, limit: int = 10) -> list[dict]:
        conn = self._conn()
        try:
            try:
                rows = conn.execute(
                    """SELECT k.* FROM knowledge_fts f
                       JOIN knowledge k ON f.rowid = k.rowid
                       WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (query, limit),
                ).fetchall()
            except Exception:
                rows = conn.execute(
                    """SELECT * FROM knowledge WHERE subject LIKE ? OR object LIKE ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
        finally:
            conn.close()
        return [
            {"id": r["id"], "subject": r["subject"], "predicate": r["predicate"],
             "object": r["object"], "confidence": r["confidence"]}
            for r in rows
        ]

    def knowledge_about(self, entity: str, limit: int = 20) -> list[dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT * FROM knowledge WHERE subject = ? OR object = ?
                   ORDER BY confidence DESC, updated_at DESC LIMIT ?""",
                (entity, entity, limit),
            ).fetchall()
        finally:
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
        self, session_id: str, skill_id: str, endpoint_id: str, args: dict,
        result_status: str, result_summary: str = "", latency_ms: float = 0,
    ) -> str:
        eid = str(uuid4())[:12]
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT INTO execution_log
                   (id, session_id, skill_id, endpoint_id, args, result_status, result_summary, latency_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, session_id, skill_id, endpoint_id, json.dumps(args)[:2000],
                 result_status, result_summary[:500], latency_ms, now),
            )
            conn.commit()
        finally:
            conn.close()
        return eid

    def log_feedback(self, execution_id: str, feedback: str):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("UPDATE execution_log SET user_feedback = ? WHERE id = ?", (feedback[:500], execution_id))
            conn.commit()
        finally:
            conn.close()

    def log_recent(self, skill_id: str = "", limit: int = 20) -> list[dict]:
        conn = self._conn()
        try:
            if skill_id:
                rows = conn.execute(
                    "SELECT * FROM execution_log WHERE skill_id = ? ORDER BY created_at DESC LIMIT ?",
                    (skill_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM execution_log ORDER BY created_at DESC LIMIT ?", (limit,),
                ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def log_success_rate(self, skill_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        try:
            total = conn.execute("SELECT COUNT(*) FROM execution_log WHERE skill_id = ?", (skill_id,)).fetchone()[0]
            successes = conn.execute(
                "SELECT COUNT(*) FROM execution_log WHERE skill_id = ? AND result_status = 'success'",
                (skill_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        return {"skill_id": skill_id, "total_executions": total, "successes": successes,
                "rate": successes / total if total > 0 else 0.0}

    # ─────────────────────────────────────────────
    # Unified Context Builder (for LLM injection)
    # ─────────────────────────────────────────────

    async def build_context_for_llm_async(
        self,
        session_id: str,
        query: str = "",
        max_tokens_budget: int = 2000,
        memory_filter: str = "",
    ) -> str:
        return await context_build_context_for_llm_async(
            self,
            session_id=session_id,
            query=query,
            max_tokens_budget=max_tokens_budget,
            memory_filter=memory_filter,
        )

    def build_context_for_llm(
        self,
        session_id: str,
        query: str = "",
        max_tokens_budget: int = 2000,
        memory_filter: str = "",
    ) -> str:
        return context_build_context_for_llm(
            self,
            session_id=session_id,
            query=query,
            max_tokens_budget=max_tokens_budget,
            memory_filter=memory_filter,
        )

    # ─────────────────────────────────────────────
    # Compaction (multi-stage summarization)
    # ─────────────────────────────────────────────

    async def compact_session(self, session_id: str, history: list[dict], llm=None,
                              preserve_last_n: int = 3, max_summary_chars: int = 16000) -> dict:
        return await context_compact_session(
            self,
            session_id=session_id,
            history=history,
            llm=llm,
            preserve_last_n=preserve_last_n,
            max_summary_chars=max_summary_chars,
        )

    async def _llm_summarize(self, messages: list[dict], llm, max_chars: int) -> str:
        return await context_llm_summarize(messages=messages, llm=llm, max_chars=max_chars)

    @staticmethod
    def _heuristic_summarize(messages: list[dict]) -> str:
        return context_heuristic_summarize(messages)

    # ─────────────────────────────────────────────
    # Unified Hybrid Search
    # ─────────────────────────────────────────────

    async def search_all(self, query: str, limit: int = 10) -> list[dict]:
        return await context_search_all(self, query=query, limit=limit)

    # ─────────────────────────────────────────────
    # Memory Wiki (durable markdown knowledge surface)
    # ─────────────────────────────────────────────

    @staticmethod
    def _wiki_slug(value: str) -> str:
        return helper_wiki_slug(value)

    def wiki_upsert_page(
        self,
        *,
        page_id: str,
        title: str,
        kind: str,
        body_markdown: str,
        source_refs: list[dict] | None = None,
    ) -> dict:
        return helper_wiki_upsert_page(
            self,
            page_id=page_id,
            title=title,
            kind=kind,
            body_markdown=body_markdown,
            source_refs=source_refs,
        )

    def wiki_get_page(self, page_id: str) -> Optional[dict]:
        return helper_wiki_get_page(self, page_id=page_id)

    def wiki_list_pages(self, *, query: str = "", kind: str = "", limit: int = 50) -> list[dict]:
        return helper_wiki_list_pages(self, query=query, kind=kind, limit=limit)

    def wiki_stats(self) -> dict:
        return helper_wiki_stats(self)

    def wiki_compile(
        self,
        *,
        notes_limit: int = 200,
        episodes_limit: int = 200,
        knowledge_limit: int = 400,
    ) -> dict:
        return helper_wiki_compile(
            self,
            notes_limit=notes_limit,
            episodes_limit=episodes_limit,
            knowledge_limit=knowledge_limit,
        )

    # ─────────────────────────────────────────────
    # Legacy Notes API (backward compat)
    # ─────────────────────────────────────────────

    def save(self, content: str, tags: list[str] = None, importance: str = "normal", source: str = "user") -> dict:
        return save_note(self, content=content, tags=tags, importance=importance, source=source)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return search_notes(self, query=query, limit=limit)

    def list_recent(self, limit: int = 10) -> list[dict]:
        return list_recent_notes(self, limit=limit)

    def delete(self, note_id: str) -> bool:
        return delete_note(self, note_id=note_id)

    def count(self) -> int:
        return count_notes(self)

    def stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        try:
            notes_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            episodes_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            knowledge_count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            exec_count = conn.execute("SELECT COUNT(*) FROM execution_log").fetchone()[0]
            wiki_count = conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]
            snapshot_count = conn.execute("SELECT COUNT(*) FROM session_snapshots").fetchone()[0]
            try:
                chunk_count = conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
            except Exception:
                chunk_count = 0
        finally:
            conn.close()
        working_sessions = len(self._working)

        kg_stats = self._kg.stats() if self._kg else {"entities": 0, "relations": 0}

        return {
            "notes": notes_count,
            "episodes": episodes_count,
            "knowledge_triples": knowledge_count,
            "execution_logs": exec_count,
            "wiki_pages": wiki_count,
            "session_snapshots": snapshot_count,
            "active_working_sessions": working_sessions,
            "embedded_chunks": chunk_count,
            "vec_index_count": self._vec_index.count,
            "vec_index_mode": "sqlite-vec" if self._vec_index.indexed else "numpy_fallback",
            "embedding_provider": self._embedder.provider_name,
            "embed_queue_pending": self._embed_queue.pending,
            "knowledge_graph": kg_stats,
        }
