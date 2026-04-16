from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from config.loader import feral_home


def wiki_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "unknown"


def wiki_upsert_page(
    store,
    *,
    page_id: str,
    title: str,
    kind: str,
    body_markdown: str,
    source_refs: list[dict] | None = None,
) -> dict:
    now = time.time()
    refs = source_refs or []
    conn = sqlite3.connect(store.db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
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
    finally:
        conn.close()
    return {
        "id": page_id,
        "title": title,
        "kind": kind,
        "updated_at": now,
        "source_refs": refs,
    }


def wiki_get_page(store, page_id: str) -> Optional[dict]:
    conn = store._conn()
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


def wiki_list_pages(store, *, query: str = "", kind: str = "", limit: int = 50) -> list[dict]:
    lim = max(1, min(limit, 200))
    conn = store._conn()
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
            "id": row["id"],
            "title": row["title"],
            "kind": row["kind"],
            "source_refs": json.loads(row["source_refs"] or "[]"),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def wiki_stats(store) -> dict:
    conn = store._conn()
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
    store,
    *,
    notes_limit: int = 200,
    episodes_limit: int = 200,
    knowledge_limit: int = 400,
) -> dict:
    conn = store._conn()
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
        wiki_upsert_page(
            store,
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
        wiki_upsert_page(
            store,
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
        page_id = f"entity.{wiki_slug(subject)}"
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
        wiki_upsert_page(
            store,
            page_id=page_id,
            title=title,
            kind="entity",
            body_markdown=body,
            source_refs=refs,
        )
        entity_pages += 1

    identity_page_written = False
    memory_md = feral_home() / "MEMORY.md"
    if memory_md.exists():
        memory_text = Path(memory_md).read_text(encoding="utf-8", errors="replace")
        wiki_upsert_page(
            store,
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
        "# FERAL Memory Wiki",
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
    wiki_upsert_page(
        store,
        page_id="index",
        title="Wiki Index",
        kind="index",
        body_markdown="\n".join(index_lines),
        source_refs=[],
    )

    stats = wiki_stats(store)
    return {
        "compiled": True,
        "notes_pages": note_pages,
        "episode_pages": episode_pages,
        "entity_pages": entity_pages,
        "identity_page": identity_page_written,
        "total_pages": stats["pages"],
        "kinds": stats["kinds"],
    }
