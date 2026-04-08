"""
THEORA Memory System — Production Cognitive Architecture
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
import re
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Optional
from uuid import uuid4

import numpy as np

from config.loader import theora_data_home, theora_home
from memory.embeddings import (
    EmbeddingProvider,
    VectorIndex,
    EmbedQueue,
    chunk_text,
    vec_to_blob,
    blob_to_vec,
    cosine_similarity,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

logger = logging.getLogger("theora.memory")

_SCHEMA_VERSION = 5

TEXT_WEIGHT = 0.3
VECTOR_WEIGHT = 0.7
DEFAULT_DECAY_RATE = 0.01


class MemoryStore:
    """
    The full THEORA memory layer with vector search, hybrid ranking,
    temporal decay, and multi-stage compaction.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = theora_data_home()
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "memory.db")

        self.db_path = db_path
        self._working: dict[str, deque[dict]] = {}
        self._working_max = 50
        self._sync_engine = None
        self._embedder = EmbeddingProvider()
        self._kg = None

        self._init_db()

        self._vec_index = VectorIndex(self.db_path, self._embedder.dimension, "vec_chunks")
        self._embed_queue = EmbedQueue(self._embedder, self._vec_index)

        self._init_knowledge_graph()
        index_mode = "sqlite-vec (vec0)" if self._vec_index.indexed else "numpy fallback"
        logger.info(f"Memory store v{_SCHEMA_VERSION} at {self.db_path} | embeddings: {self._embedder.provider_name} | index: {index_mode}")

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

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)

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

        # Legacy knowledge triples (kept for backward compat, KG is preferred)
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

        # Embedding chunks table for vector search
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

        conn.execute(
            """
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
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_session ON session_snapshots(session_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_branch ON session_snapshots(branch_name, created_at DESC)")

        conn.commit()
        conn.close()

    # ─────────────────────────────────────────────
    # Tier 1: Working Memory (in-RAM)
    # ─────────────────────────────────────────────

    def working_push(self, session_id: str, entry: dict):
        if session_id not in self._working:
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
        row = conn.execute(
            """
            SELECT id, session_id, branch_name, label, working_json, history_json, source_snapshot_id, created_at
            FROM session_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
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
        conn.execute(
            """INSERT INTO episodes
               (id, session_id, event_type, summary, detail, emotions, location, participants, importance, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, session_id, event_type, summary, detail,
             json.dumps(emotions), location, json.dumps(participants), importance, now),
        )
        conn.commit()
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
        return {"id": eid, "event_type": event_type, "summary": summary, "created_at": now}

    async def episode_search_hybrid(self, query: str, limit: int = 10) -> list[dict]:
        """
        Hybrid search: FTS5 text (0.3) + vector similarity (0.7) with temporal decay.
        Uses sqlite-vec indexed search when available, numpy fallback otherwise.
        """
        conn = self._conn()

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
        conn.close()
        return [self._episode_row_to_dict(r) for r in rows]

    def episode_recent(self, limit: int = 10, session_id: str = None) -> list[dict]:
        conn = self._conn()
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
        self._log_sync("knowledge", "insert", kid, {
            "id": kid, "subject": subject, "predicate": predicate, "object": obj,
            "confidence": confidence, "source": source, "created_at": now,
        })
        return {"id": kid, "subject": subject, "predicate": predicate, "object": obj}

    def knowledge_query(self, subject: str = "", predicate: str = "", limit: int = 20) -> list[dict]:
        conn = self._conn()
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
            {"id": r["id"], "subject": r["subject"], "predicate": r["predicate"],
             "object": r["object"], "confidence": r["confidence"], "source": r["source"],
             "updated_at": r["updated_at"]}
            for r in rows
        ]

    def knowledge_search(self, query: str, limit: int = 10) -> list[dict]:
        conn = self._conn()
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
        conn.close()
        return [
            {"id": r["id"], "subject": r["subject"], "predicate": r["predicate"],
             "object": r["object"], "confidence": r["confidence"]}
            for r in rows
        ]

    def knowledge_about(self, entity: str, limit: int = 20) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM knowledge WHERE subject = ? OR object = ?
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
        self, session_id: str, skill_id: str, endpoint_id: str, args: dict,
        result_status: str, result_summary: str = "", latency_ms: float = 0,
    ) -> str:
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
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE execution_log SET user_feedback = ? WHERE id = ?", (feedback[:500], execution_id))
        conn.commit()
        conn.close()

    def log_recent(self, skill_id: str = "", limit: int = 20) -> list[dict]:
        conn = self._conn()
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
        conn = sqlite3.connect(self.db_path)
        total = conn.execute("SELECT COUNT(*) FROM execution_log WHERE skill_id = ?", (skill_id,)).fetchone()[0]
        successes = conn.execute(
            "SELECT COUNT(*) FROM execution_log WHERE skill_id = ? AND result_status = 'success'",
            (skill_id,),
        ).fetchone()[0]
        conn.close()
        return {"skill_id": skill_id, "total_executions": total, "successes": successes,
                "rate": successes / total if total > 0 else 0.0}

    # ─────────────────────────────────────────────
    # Unified Context Builder (for LLM injection)
    # ─────────────────────────────────────────────

    async def build_context_for_llm_async(self, session_id: str, query: str = "", max_tokens_budget: int = 2000) -> str:
        """Async context builder using hybrid search + knowledge graph."""
        sections = []
        budget_per_section = max_tokens_budget // 4

        working = self.working_context_string(session_id, limit=8)
        if working:
            sections.append(f"## Recent Context\n{working[:budget_per_section]}")

        if query and self._kg:
            graph_ctx = await self._kg.build_graph_context(query, max_chars=budget_per_section)
            if graph_ctx:
                sections.append(graph_ctx)
        elif query:
            knowledge = self.knowledge_search(query, limit=5)
            if knowledge:
                k_lines = [f"- {k['subject']} {k['predicate']} {k['object']}" for k in knowledge]
                sections.append(f"## Known Facts\n" + "\n".join(k_lines)[:budget_per_section])

        if query:
            episodes = await self.episode_search_hybrid(query, limit=3)
        else:
            episodes = self.episode_recent(limit=3, session_id=session_id)
        if episodes:
            ep_lines = [f"- [{e['event_type']}] {e['summary']}" for e in episodes]
            sections.append(f"## Past Events\n" + "\n".join(ep_lines)[:budget_per_section])

        recent_execs = self.log_recent(limit=5)
        if recent_execs:
            ex_lines = [f"- {ex.get('skill_id', '?')}: {ex.get('result_status', '?')}" for ex in recent_execs]
            sections.append(f"## Recent Actions\n" + "\n".join(ex_lines)[:budget_per_section])

        return "\n\n".join(sections) if sections else ""

    def build_context_for_llm(self, session_id: str, query: str = "", max_tokens_budget: int = 2000) -> str:
        """Synchronous context builder (backward compat)."""
        sections = []
        budget_per_section = max_tokens_budget // 4

        working = self.working_context_string(session_id, limit=8)
        if working:
            sections.append(f"## Recent Context\n{working[:budget_per_section]}")

        if query:
            knowledge = self.knowledge_search(query, limit=5)
            if knowledge:
                k_lines = [f"- {k['subject']} {k['predicate']} {k['object']}" for k in knowledge]
                sections.append(f"## Known Facts\n" + "\n".join(k_lines)[:budget_per_section])

        if query:
            episodes = self.episode_search(query, limit=3)
        else:
            episodes = self.episode_recent(limit=3, session_id=session_id)
        if episodes:
            ep_lines = [f"- [{e['event_type']}] {e['summary']}" for e in episodes]
            sections.append(f"## Past Events\n" + "\n".join(ep_lines)[:budget_per_section])

        recent_execs = self.log_recent(limit=5)
        if recent_execs:
            ex_lines = [f"- {ex.get('skill_id', '?')}: {ex.get('result_status', '?')}" for ex in recent_execs]
            sections.append(f"## Recent Actions\n" + "\n".join(ex_lines)[:budget_per_section])

        return "\n\n".join(sections) if sections else ""

    # ─────────────────────────────────────────────
    # Compaction (multi-stage summarization)
    # ─────────────────────────────────────────────

    async def compact_session(self, session_id: str, history: list[dict], llm=None,
                              preserve_last_n: int = 3, max_summary_chars: int = 16000) -> dict:
        """
        Multi-stage session compaction. Summarizes older messages while
        preserving the last N turns and identity context.
        """
        if len(history) <= preserve_last_n + 2:
            return {"compacted": False, "reason": "too_short"}

        preserved = history[-preserve_last_n:]
        summarizable = history[:-preserve_last_n]

        if not llm or not llm.available:
            summary = self._heuristic_summarize(summarizable)
        else:
            summary = await self._llm_summarize(summarizable, llm, max_summary_chars)

        compacted_history = [
            {"role": "system", "content": f"[Session Summary]\n{summary}"},
            *preserved,
        ]

        if self.kg:
            try:
                conversation_text = " ".join(
                    m.get("content", "") for m in summarizable
                    if isinstance(m.get("content"), str)
                )
                if conversation_text:
                    await self.kg.extract_and_store(conversation_text[:3000], llm)
            except Exception as e:
                logger.debug(f"KG extraction during compaction failed: {e}")

        return {
            "compacted": True,
            "original_length": len(history),
            "new_length": len(compacted_history),
            "summary_chars": len(summary),
            "history": compacted_history,
        }

    async def _llm_summarize(self, messages: list[dict], llm, max_chars: int) -> str:
        """Multi-stage LLM summarization of conversation history."""
        text_parts = []
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, str):
                text_parts.append(f"[{role}] {content[:500]}")
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text_parts.append(f"[{role}] {c['text'][:500]}")

        full_text = "\n".join(text_parts)

        chunk_size = 6000
        if len(full_text) <= chunk_size:
            chunks = [full_text]
        else:
            chunks = [full_text[i:i + chunk_size] for i in range(0, len(full_text), chunk_size)]

        summaries = []
        for chunk in chunks:
            prompt = (
                "Summarize this conversation segment concisely. Preserve:\n"
                "- Key facts and decisions\n"
                "- User preferences and personal info\n"
                "- Tool call results and outcomes\n"
                "- Any unresolved questions or tasks\n\n"
                f"{chunk}"
            )
            try:
                response = await llm.chat([{"role": "user", "content": prompt}], tools=None)
                text, _ = llm.extract_response(response)
                summaries.append(text)
            except Exception as e:
                logger.warning(f"Summarization chunk failed: {e}")
                summaries.append(chunk[:500])

        result = "\n\n".join(summaries)
        return result[:max_chars]

    @staticmethod
    def _heuristic_summarize(messages: list[dict]) -> str:
        lines = []
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"[{role}] {content[:100]}")
        return "\n".join(lines[-20:])

    # ─────────────────────────────────────────────
    # Unified Hybrid Search
    # ─────────────────────────────────────────────

    async def search_all(self, query: str, limit: int = 10) -> list[dict]:
        """Search across all memory tiers using hybrid ranking."""
        results = []

        episodes = await self.episode_search_hybrid(query, limit=limit)
        for e in episodes:
            results.append({**e, "tier": "episode", "score": e.get("relevance_score", 0)})

        notes = self.search(query, limit=limit)
        for n in notes:
            results.append({**n, "tier": "note", "score": n.get("relevance_score", 0.3)})

        knowledge = self.knowledge_search(query, limit=limit)
        for k in knowledge:
            results.append({
                "tier": "knowledge", "score": 0.5,
                "summary": f"{k['subject']} {k['predicate']} {k['object']}",
                **k,
            })

        if self._kg:
            entities = await self._kg.search_entities(query, limit=5)
            for e in entities:
                results.append({
                    "tier": "entity", "score": e.get("score", 0.5),
                    "summary": f"Entity: {e['name']} ({e.get('type', 'thing')})",
                    **e,
                })

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]

    # ─────────────────────────────────────────────
    # Memory Wiki (durable markdown knowledge surface)
    # ─────────────────────────────────────────────

    @staticmethod
    def _wiki_slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
        return slug or "unknown"

    def wiki_upsert_page(
        self,
        *,
        page_id: str,
        title: str,
        kind: str,
        body_markdown: str,
        source_refs: list[dict] | None = None,
    ) -> dict:
        now = time.time()
        refs = source_refs or []
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO wiki_pages (id, title, kind, body_markdown, source_refs, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              kind=excluded.kind,
              body_markdown=excluded.body_markdown,
              source_refs=excluded.source_refs,
              updated_at=excluded.updated_at
            """,
            (page_id, title, kind, body_markdown, json.dumps(refs), now, now),
        )
        conn.commit()
        conn.close()
        return {
            "id": page_id,
            "title": title,
            "kind": kind,
            "updated_at": now,
            "source_refs": refs,
        }

    def wiki_get_page(self, page_id: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT id, title, kind, body_markdown, source_refs, created_at, updated_at FROM wiki_pages WHERE id = ?",
            (page_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "kind": row["kind"],
            "body_markdown": row["body_markdown"],
            "source_refs": json.loads(row["source_refs"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def wiki_list_pages(self, *, query: str = "", kind: str = "", limit: int = 50) -> list[dict]:
        lim = max(1, min(limit, 200))
        conn = self._conn()
        rows = []
        if query.strip():
            if kind:
                rows = conn.execute(
                    """
                    SELECT w.id, w.title, w.kind, w.source_refs, w.updated_at
                    FROM wiki_pages_fts f
                    JOIN wiki_pages w ON f.rowid = w.rowid
                    WHERE wiki_pages_fts MATCH ? AND w.kind = ?
                    ORDER BY rank, w.updated_at DESC
                    LIMIT ?
                    """,
                    (query.strip(), kind, lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT w.id, w.title, w.kind, w.source_refs, w.updated_at
                    FROM wiki_pages_fts f
                    JOIN wiki_pages w ON f.rowid = w.rowid
                    WHERE wiki_pages_fts MATCH ?
                    ORDER BY rank, w.updated_at DESC
                    LIMIT ?
                    """,
                    (query.strip(), lim),
                ).fetchall()
        elif kind:
            rows = conn.execute(
                """
                SELECT id, title, kind, source_refs, updated_at
                FROM wiki_pages
                WHERE kind = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (kind, lim),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, title, kind, source_refs, updated_at
                FROM wiki_pages
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "kind": r["kind"],
                "source_refs": json.loads(r["source_refs"] or "[]"),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def wiki_stats(self) -> dict:
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]
        kinds = conn.execute(
            "SELECT kind, COUNT(*) AS count FROM wiki_pages GROUP BY kind ORDER BY count DESC"
        ).fetchall()
        conn.close()
        return {
            "pages": total,
            "kinds": [{"kind": row["kind"], "count": row["count"]} for row in kinds],
        }

    def wiki_compile(
        self,
        *,
        notes_limit: int = 200,
        episodes_limit: int = 200,
        knowledge_limit: int = 400,
    ) -> dict:
        conn = self._conn()
        notes = conn.execute(
            """
            SELECT id, content, tags, importance, source, created_at, updated_at
            FROM notes
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, notes_limit),),
        ).fetchall()
        episodes = conn.execute(
            """
            SELECT id, session_id, event_type, summary, detail, created_at
            FROM episodes
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, episodes_limit),),
        ).fetchall()
        triples = conn.execute(
            """
            SELECT id, subject, predicate, object, confidence, source, updated_at
            FROM knowledge
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, knowledge_limit),),
        ).fetchall()
        conn.close()

        note_pages = 0
        for row in notes:
            tags = json.loads(row["tags"] or "[]")
            title = f"Note {row['id']}"
            body = (
                f"# {title}\n\n"
                f"{row['content']}\n\n"
                f"## Metadata\n"
                f"- Importance: {row['importance']}\n"
                f"- Source: {row['source']}\n"
                f"- Tags: {', '.join(tags) if tags else 'none'}\n"
                f"- Updated: {row['updated_at']}\n"
            )
            self.wiki_upsert_page(
                page_id=f"note.{row['id']}",
                title=title,
                kind="note",
                body_markdown=body,
                source_refs=[
                    {"type": "note", "id": row["id"], "updated_at": row["updated_at"]},
                ],
            )
            note_pages += 1

        episode_pages = 0
        for row in episodes:
            title = f"Episode {row['id']} ({row['event_type']})"
            body = (
                f"# {title}\n\n"
                f"## Summary\n{row['summary']}\n\n"
                f"## Detail\n{row['detail'] or '-'}\n\n"
                f"## Metadata\n"
                f"- Session: {row['session_id']}\n"
                f"- Created: {row['created_at']}\n"
            )
            self.wiki_upsert_page(
                page_id=f"episode.{row['id']}",
                title=title,
                kind="episode",
                body_markdown=body,
                source_refs=[
                    {
                        "type": "episode",
                        "id": row["id"],
                        "session_id": row["session_id"],
                        "created_at": row["created_at"],
                    },
                ],
            )
            episode_pages += 1

        triples_by_subject: dict[str, list[dict]] = {}
        for row in triples:
            triples_by_subject.setdefault(row["subject"], []).append(
                {
                    "id": row["id"],
                    "predicate": row["predicate"],
                    "object": row["object"],
                    "confidence": row["confidence"],
                    "source": row["source"],
                    "updated_at": row["updated_at"],
                }
            )

        entity_pages = 0
        for subject, items in triples_by_subject.items():
            page_id = f"entity.{self._wiki_slug(subject)}"
            title = f"Entity: {subject}"
            lines = [f"# {title}", "", "## Facts"]
            for item in items[:200]:
                lines.append(
                    f"- {subject} **{item['predicate']}** {item['object']} "
                    f"(confidence={item['confidence']:.2f}, source={item['source']})"
                )
            body = "\n".join(lines)
            refs = [
                {
                    "type": "knowledge",
                    "id": item["id"],
                    "subject": subject,
                    "updated_at": item["updated_at"],
                }
                for item in items
            ]
            self.wiki_upsert_page(
                page_id=page_id,
                title=title,
                kind="entity",
                body_markdown=body,
                source_refs=refs,
            )
            entity_pages += 1

        identity_page_written = False
        memory_md = theora_home() / "MEMORY.md"
        if memory_md.exists():
            memory_text = memory_md.read_text(encoding="utf-8", errors="replace")
            self.wiki_upsert_page(
                page_id="identity.memory",
                title="Identity Memory",
                kind="identity",
                body_markdown=memory_text or "# Identity Memory\n\n(empty)",
                source_refs=[
                    {"type": "identity_file", "path": str(memory_md)},
                ],
            )
            identity_page_written = True

        index_lines = [
            "# THEORA Memory Wiki",
            "",
            "## Summary",
            f"- Notes compiled: {note_pages}",
            f"- Episodes compiled: {episode_pages}",
            f"- Entity pages compiled: {entity_pages}",
            f"- Identity page: {'yes' if identity_page_written else 'no'}",
            "",
            "## How to use",
            "- Search pages with `q` in `/api/wiki/pages`.",
            "- Fetch full page content from `/api/wiki/pages/{page_id}`.",
            "- Recompile after new memory writes using `/api/wiki/compile`.",
        ]
        self.wiki_upsert_page(
            page_id="index",
            title="Wiki Index",
            kind="index",
            body_markdown="\n".join(index_lines),
            source_refs=[],
        )

        stats = self.wiki_stats()
        return {
            "compiled": True,
            "notes_pages": note_pages,
            "episode_pages": episode_pages,
            "entity_pages": entity_pages,
            "identity_page": identity_page_written,
            "total_pages": stats["pages"],
            "kinds": stats["kinds"],
        }

    # ─────────────────────────────────────────────
    # Legacy Notes API (backward compat)
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

        # Embed notes too (not just episodes)
        chunks = chunk_text(content)
        for i, chunk in enumerate(chunks):
            self._embed_queue.enqueue(
                chunk_id=f"note_{note_id}_c{i}", text=chunk,
                source_table="notes", source_id=note_id,
                chunk_index=i, db_path=self.db_path,
            )

        self.knowledge_store(subject="user_note", predicate="says", obj=content[:300], source=f"notes:{note_id}")
        self._log_sync("notes", "insert", note_id, {
            "id": note_id, "content": content, "tags": json.dumps(tags),
            "importance": importance, "source": source, "created_at": now,
        })
        return {"id": note_id, "content": content, "tags": tags, "importance": importance, "created_at": now, "status": "saved"}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        conn = self._conn()
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
             "importance": r["importance"], "created_at": r["created_at"],
             "relevance_score": abs(r["relevance_score"])}
            for r in rows
        ]

    def list_recent(self, limit: int = 10) -> list[dict]:
        conn = self._conn()
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
        conn = sqlite3.connect(self.db_path)
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
        working_sessions = len(self._working)
        conn.close()

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
