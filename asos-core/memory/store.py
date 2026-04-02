"""
THEORA Memory System — SQLite-Backed Knowledge Store
=====================================================
Stores notes, memories, and facts that the user wants to remember.
This is the backend for the Notes & Memory skill.
"""

from __future__ import annotations
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

logger = logging.getLogger("theora.memory")


class MemoryStore:
    """
    SQLite-backed memory store.
    
    Supports:
    - Save notes with tags and importance levels
    - Full-text search across all saved notes
    - List recent notes
    - Delete notes
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = Path.home() / ".theora"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "memory.db")

        self.db_path = db_path
        self._init_db()
        logger.info(f"Memory store initialized at {self.db_path}")

    def _init_db(self):
        """Initialize the database schema."""
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
        # Full-text search index
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
            USING fts5(content, tags, tokenize='porter')
        """)
        # Trigger to keep FTS in sync
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
        conn.commit()
        conn.close()

    def save(self, content: str, tags: list[str] = None, importance: str = "normal", source: str = "user") -> dict:
        """Save a note to memory."""
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

        logger.info(f"Saved note {note_id}: {content[:80]}...")

        return {
            "id": note_id,
            "content": content,
            "tags": tags,
            "importance": importance,
            "created_at": now,
            "status": "saved",
        }

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search notes using full-text search."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Try FTS first, fall back to LIKE
        try:
            rows = conn.execute(
                """
                SELECT n.id, n.content, n.tags, n.importance, n.created_at,
                       rank as relevance_score
                FROM notes_fts f
                JOIN notes n ON f.rowid = n.rowid
                WHERE notes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except Exception:
            # Fallback to LIKE search
            rows = conn.execute(
                "SELECT id, content, tags, importance, created_at, 0.5 as relevance_score FROM notes WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()

        conn.close()

        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "content": row["content"],
                "tags": json.loads(row["tags"]),
                "importance": row["importance"],
                "created_at": row["created_at"],
                "relevance_score": abs(row["relevance_score"]),
            })

        return results

    def list_recent(self, limit: int = 10) -> list[dict]:
        """List the most recently saved notes."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            "SELECT id, content, tags, importance, created_at FROM notes ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        conn.close()

        return [
            {
                "id": row["id"],
                "content": row["content"],
                "tags": json.loads(row["tags"]),
                "importance": row["importance"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def delete(self, note_id: str) -> bool:
        """Delete a note by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def count(self) -> int:
        """Count total notes."""
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        conn.close()
        return count
