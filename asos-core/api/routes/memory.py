"""Memory, knowledge graph, wiki, and episode endpoints."""

from fastapi import APIRouter

from api.state import state
from memory.ingest import MemoryIngestor

router = APIRouter()


# ── Knowledge Graph ──

def _knowledge_graph_d3(limit: int) -> dict:
    """Build D3-style {nodes, links} from the entity graph and legacy triples."""
    memory = state.memory
    nodes: dict[str, dict] = {}
    links: list[dict] = []

    kg = getattr(memory, "kg", None)
    if kg:
        conn = kg._conn()
        rows = conn.execute(
            """
            SELECT r.id AS rid, r.relation_type,
                   s.id AS sid, s.name AS sname, s.entity_type AS stype,
                   t.id AS tid, t.name AS tname, t.entity_type AS ttype
            FROM relations r
            JOIN entities s ON r.source_id = s.id
            JOIN entities t ON r.target_id = t.id
            ORDER BY r.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        for r in rows:
            sid, tid = r["sid"], r["tid"]
            if sid not in nodes:
                nodes[sid] = {
                    "id": sid,
                    "name": r["sname"],
                    "type": (r["stype"] or "thing"),
                }
            if tid not in nodes:
                nodes[tid] = {
                    "id": tid,
                    "name": r["tname"],
                    "type": (r["ttype"] or "thing"),
                }
            links.append(
                {
                    "source": sid,
                    "target": tid,
                    "relation": r["relation_type"],
                    "id": r["rid"],
                }
            )

    if not links:
        triples = memory.knowledge_query(limit=limit)
        seen: dict[str, str] = {}
        nxt = 0

        def nid(label: str) -> str:
            nonlocal nxt
            if label not in seen:
                seen[label] = f"k_{nxt}"
                nxt += 1
            return seen[label]

        for t in triples:
            subj, obj = t["subject"], t["object"]
            sid, tid = nid(subj), nid(obj)
            if sid not in nodes:
                nodes[sid] = {"id": sid, "name": subj, "type": "legacy"}
            if tid not in nodes:
                nodes[tid] = {"id": tid, "name": obj, "type": "legacy"}
            links.append(
                {
                    "source": sid,
                    "target": tid,
                    "relation": t["predicate"],
                    "id": t.get("id", ""),
                }
            )

    return {"nodes": list(nodes.values()), "links": links}


@router.get("/api/knowledge/graph")
async def get_knowledge_graph(limit: int = 50):
    """Return a D3-compatible graph: ``{ nodes, links }``."""
    try:
        return _knowledge_graph_d3(limit=max(1, min(limit, 500)))
    except Exception as e:
        return {"nodes": [], "links": [], "error": str(e)}


@router.get("/api/knowledge/entities")
async def search_knowledge_entities(q: str = "", limit: int = 20):
    """Search entities in the knowledge graph (FTS + embeddings when available)."""
    lim = max(1, min(limit, 100))
    kg = getattr(state.memory, "kg", None)
    try:
        if kg and q.strip():
            entities = await kg.search_entities(q.strip(), limit=lim)
            return {"entities": entities, "source": "graph"}
        if kg and not q.strip():
            conn = kg._conn()
            rows = conn.execute(
                """
                SELECT id, name, entity_type AS type, mention_count AS mentions
                FROM entities
                ORDER BY mention_count DESC, updated_at DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
            conn.close()
            return {
                "entities": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "type": r["type"],
                        "mentions": r["mentions"],
                    }
                    for r in rows
                ],
                "source": "graph",
            }
    except Exception as e:
        return {"entities": [], "error": str(e), "source": "graph"}

    rows = (
        state.memory.knowledge_search(q.strip(), limit=lim)
        if q.strip()
        else state.memory.knowledge_query(limit=lim)
    )
    out = []
    for r in rows:
        if "subject" in r:
            out.append(
                {
                    "name": r["subject"],
                    "relation": r.get("predicate"),
                    "object": r.get("object"),
                }
            )
        else:
            out.append(r)
    return {"entities": out, "source": "legacy_triples"}


# ── Internal Memory CRUD ──

@router.post("/internal/memory/save")
async def memory_save(body: dict):
    content = body.get("content", "")
    tags = body.get("tags", [])
    importance = body.get("importance", "normal")
    if not content:
        return {"error": "content is required"}
    return state.memory.save(content=content, tags=tags, importance=importance)


@router.get("/internal/memory/search")
async def memory_search(query: str = "", limit: int = 10):
    if not query:
        return []
    return state.memory.search(query=query, limit=limit)


@router.get("/internal/memory/recent")
async def memory_recent(limit: int = 10):
    return state.memory.list_recent(limit=limit)


@router.delete("/internal/memory/{note_id}")
async def memory_delete(note_id: str):
    return {"deleted": state.memory.delete(note_id)}


@router.get("/internal/memory/stats")
async def memory_stats():
    return state.memory.stats()


@router.post("/internal/knowledge/store")
async def knowledge_store(body: dict):
    subject = body.get("subject", "")
    predicate = body.get("predicate", "")
    obj = body.get("object", "")
    if not all([subject, predicate, obj]):
        return {"error": "subject, predicate, and object are required"}
    return state.memory.knowledge_store(subject=subject, predicate=predicate, obj=obj)


@router.get("/internal/knowledge/query")
async def knowledge_query(subject: str = "", predicate: str = "", limit: int = 20):
    return state.memory.knowledge_query(subject=subject, predicate=predicate, limit=limit)


@router.get("/internal/knowledge/about/{entity}")
async def knowledge_about(entity: str, limit: int = 20):
    return state.memory.knowledge_about(entity, limit=limit)


@router.get("/api/knowledge/relationship")
async def knowledge_relationship(entity_a: str = "", entity_b: str = "", max_depth: int = 4):
    """Query the relationship between two entities (e.g. 'What does X know about Y?')."""
    if not entity_a or not entity_b:
        return {"error": "Both entity_a and entity_b are required"}
    try:
        from memory.enhanced_search import relationship_query
        return relationship_query(state.memory._knowledge_graph, entity_a, entity_b, max_depth)
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/knowledge/visualize")
async def knowledge_visualize(entity: str = "", depth: int = 2, limit: int = 50):
    """Return graph visualization data (nodes + edges) centered on an entity."""
    if not entity:
        return {"nodes": [], "edges": [], "error": "entity parameter required"}
    try:
        from memory.enhanced_search import graph_visualization_data
        return graph_visualization_data(state.memory._knowledge_graph, entity, max_depth=depth, limit=limit)
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}


@router.get("/internal/episodes/recent")
async def episodes_recent(limit: int = 10, session_id: str = ""):
    return state.memory.episode_recent(limit=limit, session_id=session_id or None)


@router.get("/internal/execution-log")
async def execution_log(skill_id: str = "", limit: int = 20):
    return state.memory.log_recent(skill_id=skill_id, limit=limit)


# ── Wiki ──

@router.post("/api/wiki/compile")
async def wiki_compile(body: dict | None = None):
    """Compile notes/episodes/knowledge into durable wiki pages."""
    payload = body or {}
    return state.memory.wiki_compile(
        notes_limit=int(payload.get("notes_limit", 200)),
        episodes_limit=int(payload.get("episodes_limit", 200)),
        knowledge_limit=int(payload.get("knowledge_limit", 400)),
    )


@router.get("/api/wiki/pages")
async def wiki_pages(q: str = "", kind: str = "", limit: int = 50):
    pages = state.memory.wiki_list_pages(query=q, kind=kind, limit=limit)
    return {"pages": pages}


@router.get("/api/wiki/pages/{page_id}")
async def wiki_page(page_id: str):
    page = state.memory.wiki_get_page(page_id)
    if not page:
        return {"error": f"Wiki page not found: {page_id}"}
    return page


@router.get("/api/wiki/stats")
async def wiki_stats():
    return state.memory.wiki_stats()


@router.post("/api/wiki/ingest")
async def wiki_ingest(body: dict):
    """Ingest a raw note and optionally compile wiki pages."""
    content = (body or {}).get("content", "")
    if not content:
        return {"error": "content is required"}
    tags = body.get("tags", [])
    importance = body.get("importance", "normal")
    compile_after = bool(body.get("compile_after", True))
    note = state.memory.save(content=content, tags=tags, importance=importance, source="wiki_ingest")
    compile_result = state.memory.wiki_compile() if compile_after else {"compiled": False}
    return {"note": note, "compile": compile_result}


@router.post("/api/wiki/ingest/text")
async def wiki_ingest_text(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    ingestor = MemoryIngestor(state.memory)
    try:
        return ingestor.ingest_text(
            content=(body or {}).get("content", ""),
            source_label=(body or {}).get("source_label", "ui"),
            compile_after=bool((body or {}).get("compile_after", True)),
        )
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/wiki/ingest/pdf")
async def wiki_ingest_pdf(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    ingestor = MemoryIngestor(state.memory)
    try:
        return ingestor.ingest_pdf(
            path=(body or {}).get("path", ""),
            compile_after=bool((body or {}).get("compile_after", True)),
        )
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/wiki/ingest/repo")
async def wiki_ingest_repo(body: dict):
    if not state.memory:
        return {"error": "Memory store not initialized"}
    raw_extensions = (body or {}).get("extensions_filter", [])
    if isinstance(raw_extensions, str):
        ext_list = [e.strip() for e in raw_extensions.split(",") if e.strip()]
    elif isinstance(raw_extensions, list):
        ext_list = [str(e).strip() for e in raw_extensions if str(e).strip()]
    else:
        ext_list = []

    ingestor = MemoryIngestor(state.memory)
    try:
        return ingestor.ingest_repo(
            path=(body or {}).get("path", ""),
            extensions_filter=ext_list or None,
            compile_after=bool((body or {}).get("compile_after", True)),
            max_files=int((body or {}).get("max_files", 300)),
        )
    except Exception as e:
        return {"error": str(e)}
