from __future__ import annotations

import json
import sqlite3
import time
from uuid import uuid4

from memory.embeddings import chunk_text


def save_note(
    store,
    content: str,
    tags: list[str] | None = None,
    importance: str = "normal",
    source: str = "user",
) -> dict:
    note_id = str(uuid4())[:8]
    now = time.time()
    tags = tags or []
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "INSERT INTO notes (id, content, tags, importance, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (note_id, content, json.dumps(tags), importance, source, now, now),
    )
    conn.commit()
    conn.close()

    # Embed notes too (not just episodes)
    chunks = chunk_text(content)
    for i, chunk in enumerate(chunks):
        store._embed_queue.enqueue(
            chunk_id=f"note_{note_id}_c{i}",
            text=chunk,
            source_table="notes",
            source_id=note_id,
            chunk_index=i,
            db_path=store.db_path,
        )

    store.knowledge_store(
        subject="user_note",
        predicate="says",
        obj=content[:300],
        source=f"notes:{note_id}",
    )
    store._log_sync(
        "notes",
        "insert",
        note_id,
        {
            "id": note_id,
            "content": content,
            "tags": json.dumps(tags),
            "importance": importance,
            "source": source,
            "created_at": now,
        },
    )
    return {
        "id": note_id,
        "content": content,
        "tags": tags,
        "importance": importance,
        "created_at": now,
        "status": "saved",
    }


def search_notes(store, query: str, limit: int = 10) -> list[dict]:
    conn = store._conn()
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
        {
            "id": row["id"],
            "content": row["content"],
            "tags": json.loads(row["tags"]),
            "importance": row["importance"],
            "created_at": row["created_at"],
            "relevance_score": abs(row["relevance_score"]),
        }
        for row in rows
    ]


def list_recent_notes(store, limit: int = 10) -> list[dict]:
    conn = store._conn()
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


def delete_note(store, note_id: str) -> bool:
    conn = sqlite3.connect(store.db_path)
    cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def count_notes(store) -> int:
    conn = sqlite3.connect(store.db_path)
    count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    conn.close()
    return count
