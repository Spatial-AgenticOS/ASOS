"""
THEORA Knowledge Graph — Entity-Linked Semantic Graph
======================================================
Real knowledge graph with:
  - Entity table with embeddings + type + aliases
  - Relation table with confidence + evidence
  - Multi-hop traversal via recursive CTE
  - Entity extraction via LLM structured output
  - Entity linking via embedding similarity
  - Graph neighborhood context for LLM injection
"""

from __future__ import annotations
import json
import logging
import sqlite3
import time
from typing import Optional
from uuid import uuid4

import numpy as np

from memory.embeddings import (
    EmbeddingProvider,
    vec_to_blob,
    blob_to_vec,
    cosine_similarity,
)

logger = logging.getLogger("theora.memory.kg")

ENTITY_MERGE_THRESHOLD = 0.85
ENTITY_CANDIDATE_THRESHOLD = 0.70


class KnowledgeGraph:
    """
    Production knowledge graph backed by SQLite with embedding-based
    entity linking and multi-hop traversal.
    """

    def __init__(self, db_path: str, embedder: EmbeddingProvider):
        self.db_path = db_path
        self._embedder = embedder
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT DEFAULT 'thing',
                embedding BLOB,
                metadata TEXT DEFAULT '{}',
                mention_count INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

            CREATE TABLE IF NOT EXISTS entity_aliases (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_aliases_entity ON entity_aliases(entity_id);
            CREATE INDEX IF NOT EXISTS idx_aliases_alias ON entity_aliases(alias);

            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL,
                target_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                confidence REAL DEFAULT 1.0,
                evidence_text TEXT DEFAULT '',
                source_origin TEXT DEFAULT 'conversation',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relations(relation_type);

            CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts
            USING fts5(name, entity_type, metadata, tokenize='porter');

            CREATE TRIGGER IF NOT EXISTS entities_ai_fts AFTER INSERT ON entities BEGIN
                INSERT INTO entities_fts(rowid, name, entity_type, metadata)
                VALUES (new.rowid, new.name, new.entity_type, new.metadata);
            END;
            CREATE TRIGGER IF NOT EXISTS entities_ad_fts AFTER DELETE ON entities BEGIN
                DELETE FROM entities_fts WHERE rowid = old.rowid;
            END;
        """)
        conn.commit()
        conn.close()

    async def add_entity(
        self,
        name: str,
        entity_type: str = "thing",
        metadata: dict | None = None,
    ) -> dict:
        """Add or merge an entity. Uses embedding similarity for dedup."""
        existing = await self._find_entity_by_name(name)
        if existing:
            self._bump_mention(existing["id"])
            return existing

        linked = await self._link_entity(name)
        if linked:
            self._bump_mention(linked["id"])
            self._add_alias(linked["id"], name)
            return linked

        eid = str(uuid4())[:12]
        now = time.time()
        embedding = await self._embedder.embed(name)
        meta_json = json.dumps(metadata or {})

        conn = self._conn()
        conn.execute(
            """INSERT INTO entities (id, name, entity_type, embedding, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (eid, name, entity_type, vec_to_blob(embedding), meta_json, now, now),
        )
        conn.commit()
        conn.close()
        logger.info(f"Entity added: {name} ({entity_type}) [{eid}]")
        return {"id": eid, "name": name, "entity_type": entity_type}

    async def add_relation(
        self,
        source_name: str,
        relation_type: str,
        target_name: str,
        confidence: float = 1.0,
        evidence: str = "",
        source_type: str = "thing",
        target_type: str = "thing",
    ) -> dict:
        """Add a relation between two entities (creating them if needed)."""
        source = await self.add_entity(source_name, source_type)
        target = await self.add_entity(target_name, target_type)

        conn = self._conn()
        existing = conn.execute(
            """SELECT id, confidence FROM relations
               WHERE source_id = ? AND relation_type = ? AND target_id = ?""",
            (source["id"], relation_type, target["id"]),
        ).fetchone()

        now = time.time()
        if existing:
            new_conf = min(1.0, (existing["confidence"] + confidence) / 2.0 + 0.1)
            conn.execute(
                "UPDATE relations SET confidence = ?, evidence_text = ?, updated_at = ? WHERE id = ?",
                (new_conf, evidence[:1000], now, existing["id"]),
            )
            rid = existing["id"]
        else:
            rid = str(uuid4())[:12]
            conn.execute(
                """INSERT INTO relations
                   (id, source_id, relation_type, target_id, confidence, evidence_text, source_origin, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (rid, source["id"], relation_type, target["id"], confidence, evidence[:1000], "conversation", now, now),
            )

        conn.commit()
        conn.close()
        logger.info(f"Relation: ({source_name}) --[{relation_type}]--> ({target_name})")
        return {
            "id": rid,
            "source": source["name"],
            "relation": relation_type,
            "target": target["name"],
            "confidence": confidence,
        }

    def traverse(
        self,
        start_entity_name: str,
        max_depth: int = 3,
        limit: int = 50,
    ) -> list[dict]:
        """Multi-hop graph traversal using recursive CTE."""
        conn = self._conn()
        entity = conn.execute(
            "SELECT id, name FROM entities WHERE name = ? COLLATE NOCASE",
            (start_entity_name,),
        ).fetchone()
        if not entity:
            alias_row = conn.execute(
                "SELECT entity_id FROM entity_aliases WHERE alias = ? COLLATE NOCASE",
                (start_entity_name,),
            ).fetchone()
            if alias_row:
                entity = conn.execute(
                    "SELECT id, name FROM entities WHERE id = ?",
                    (alias_row["entity_id"],),
                ).fetchone()
        if not entity:
            conn.close()
            return []

        rows = conn.execute("""
            WITH RECURSIVE graph_walk(entity_id, entity_name, relation_type, target_id, target_name, depth, path) AS (
                SELECT
                    r.source_id, e_src.name, r.relation_type, r.target_id, e_tgt.name,
                    1, e_src.name || ' -> ' || r.relation_type || ' -> ' || e_tgt.name
                FROM relations r
                JOIN entities e_src ON r.source_id = e_src.id
                JOIN entities e_tgt ON r.target_id = e_tgt.id
                WHERE r.source_id = ? OR r.target_id = ?

                UNION ALL

                SELECT
                    r2.source_id, e2_src.name, r2.relation_type, r2.target_id, e2_tgt.name,
                    gw.depth + 1,
                    gw.path || ' | ' || e2_src.name || ' -> ' || r2.relation_type || ' -> ' || e2_tgt.name
                FROM relations r2
                JOIN entities e2_src ON r2.source_id = e2_src.id
                JOIN entities e2_tgt ON r2.target_id = e2_tgt.id
                JOIN graph_walk gw ON (r2.source_id = gw.target_id OR r2.target_id = gw.entity_id)
                WHERE gw.depth < ?
                    AND gw.path NOT LIKE '%' || e2_tgt.name || '%'
            )
            SELECT DISTINCT entity_name, relation_type, target_name, depth, path
            FROM graph_walk
            ORDER BY depth ASC
            LIMIT ?
        """, (entity["id"], entity["id"], max_depth, limit)).fetchall()
        conn.close()

        return [
            {
                "source": r["entity_name"],
                "relation": r["relation_type"],
                "target": r["target_name"],
                "depth": r["depth"],
                "path": r["path"],
            }
            for r in rows
        ]

    async def search_entities(self, query: str, limit: int = 10) -> list[dict]:
        """Hybrid FTS + embedding search for entities."""
        conn = self._conn()

        # Phase 1: FTS5 text search
        fts_results = {}
        try:
            rows = conn.execute(
                """SELECT e.id, e.name, e.entity_type, e.mention_count, rank
                   FROM entities_fts f JOIN entities e ON f.rowid = e.rowid
                   WHERE entities_fts MATCH ? ORDER BY rank LIMIT ?""",
                (query, limit * 2),
            ).fetchall()
            for r in rows:
                fts_results[r["id"]] = {
                    "id": r["id"], "name": r["name"], "type": r["entity_type"],
                    "mentions": r["mention_count"],
                    "fts_score": 1.0 / (1.0 + abs(r["rank"])),
                }
        except Exception:
            pass

        # Phase 2: Vector search — scan only entities (usually small set < 10k)
        query_vec = await self._embedder.embed(query)
        all_entities = conn.execute(
            "SELECT id, name, entity_type, mention_count, embedding FROM entities WHERE embedding IS NOT NULL"
        ).fetchall()
        conn.close()

        vec_results = {}
        for e in all_entities:
            evec = blob_to_vec(e["embedding"])
            sim = cosine_similarity(query_vec, evec)
            if sim > 0.3:
                vec_results[e["id"]] = {
                    "id": e["id"], "name": e["name"], "type": e["entity_type"],
                    "mentions": e["mention_count"],
                    "vec_score": sim,
                }

        # Phase 3: Merge with weights
        merged = {}
        all_ids = set(fts_results.keys()) | set(vec_results.keys())
        for eid in all_ids:
            fts = fts_results.get(eid, {})
            vec = vec_results.get(eid, {})
            info = fts or vec
            score = 0.3 * fts.get("fts_score", 0) + 0.7 * vec.get("vec_score", 0)
            merged[eid] = {**info, "score": score}
            merged[eid].pop("fts_score", None)
            merged[eid].pop("vec_score", None)

        ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return self._mmr_rerank(ranked, limit)

    def get_entity_neighborhood(self, entity_name: str, depth: int = 1) -> dict:
        """Get all relations for an entity and its immediate neighbors."""
        conn = self._conn()
        entity = conn.execute(
            "SELECT id, name, entity_type, metadata, mention_count FROM entities WHERE name = ? COLLATE NOCASE",
            (entity_name,),
        ).fetchone()
        if not entity:
            conn.close()
            return {}

        relations = conn.execute(
            """SELECT r.*, e_src.name as source_name, e_tgt.name as target_name
               FROM relations r
               JOIN entities e_src ON r.source_id = e_src.id
               JOIN entities e_tgt ON r.target_id = e_tgt.id
               WHERE r.source_id = ? OR r.target_id = ?
               ORDER BY r.confidence DESC""",
            (entity["id"], entity["id"]),
        ).fetchall()

        aliases = conn.execute(
            "SELECT alias FROM entity_aliases WHERE entity_id = ?",
            (entity["id"],),
        ).fetchall()
        conn.close()

        return {
            "entity": {
                "id": entity["id"],
                "name": entity["name"],
                "type": entity["entity_type"],
                "mentions": entity["mention_count"],
                "metadata": json.loads(entity["metadata"] or "{}"),
                "aliases": [a["alias"] for a in aliases],
            },
            "relations": [
                {
                    "source": r["source_name"],
                    "relation": r["relation_type"],
                    "target": r["target_name"],
                    "confidence": r["confidence"],
                }
                for r in relations
            ],
        }

    async def build_graph_context(self, query: str, max_chars: int = 2000) -> str:
        """Build a graph context string for LLM injection."""
        entities = await self.search_entities(query, limit=5)
        if not entities:
            return ""

        lines = ["## Knowledge Graph"]
        chars = 0
        for e in entities:
            neighborhood = self.get_entity_neighborhood(e["name"])
            if not neighborhood:
                continue
            ent = neighborhood["entity"]
            header = f"\n### {ent['name']} ({ent['type']})"
            if ent.get("aliases"):
                header += f" aka {', '.join(ent['aliases'])}"
            lines.append(header)
            chars += len(header)

            for rel in neighborhood["relations"][:10]:
                line = f"- {rel['source']} --[{rel['relation']}]--> {rel['target']} (conf: {rel['confidence']:.1f})"
                if chars + len(line) > max_chars:
                    break
                lines.append(line)
                chars += len(line)

            if chars > max_chars:
                break

        return "\n".join(lines) if len(lines) > 1 else ""

    async def extract_and_store(self, text: str, llm=None) -> list[dict]:
        """Extract entities and relations from text via LLM, then store them."""
        if not llm or not llm.available:
            return self._heuristic_extract(text)

        prompt = (
            "Extract knowledge triples from this text. Return a JSON array of objects, "
            "each with: subject, subject_type, predicate, object, object_type.\n"
            "Types: person, place, organization, concept, thing, event, time.\n"
            "Only extract factual statements. Skip opinions and questions.\n"
            f"Text: {text[:2000]}\n"
            "Output ONLY valid JSON array. No markdown."
        )

        try:
            response = await llm.chat([{"role": "user", "content": prompt}], tools=None)
            raw_text, _ = llm.extract_response(response)
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            triples = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"LLM extraction failed, using heuristic: {e}")
            return self._heuristic_extract(text)

        stored = []
        for t in triples:
            if not isinstance(t, dict):
                continue
            subj = t.get("subject", "").strip()
            pred = t.get("predicate", "").strip()
            obj = t.get("object", "").strip()
            if not all([subj, pred, obj]):
                continue
            rel = await self.add_relation(
                source_name=subj,
                relation_type=pred,
                target_name=obj,
                evidence=text[:500],
                source_type=t.get("subject_type", "thing"),
                target_type=t.get("object_type", "thing"),
            )
            stored.append(rel)
        return stored

    def _heuristic_extract(self, text: str) -> list[dict]:
        """
        Synchronous pattern-based extraction when LLM is unavailable.
        Stores relations directly in SQLite (no async needed for simple inserts).
        """
        import re
        patterns = [
            (r"(?:my name is|i am|i'm)\s+(\w+)", "user", "is_named", "person"),
            (r"i (?:live|reside) (?:in|at)\s+(.+?)(?:\.|,|$)", "user", "lives_in", "place"),
            (r"i (?:work|am employed) (?:at|for)\s+(.+?)(?:\.|,|$)", "user", "works_at", "organization"),
            (r"i (?:like|love|enjoy)\s+(.+?)(?:\.|,|$)", "user", "likes", "thing"),
            (r"(?:my (?:wife|husband|partner) is|i'm married to)\s+(\w+)", "user", "partner_is", "person"),
            (r"i (?:study|studied) (?:at|in)\s+(.+?)(?:\.|,|$)", "user", "studied_at", "organization"),
        ]
        results = []
        now = time.time()
        conn = self._conn()
        for pattern, subject, predicate, obj_type in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                obj = match.group(1).strip()
                if not obj or len(obj) < 2:
                    continue
                # Direct sync insert for entities and relations
                for ename, etype in [(subject, "person"), (obj, obj_type)]:
                    existing = conn.execute(
                        "SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (ename,)
                    ).fetchone()
                    if not existing:
                        eid = str(uuid4())[:12]
                        conn.execute(
                            "INSERT INTO entities (id, name, entity_type, metadata, created_at, updated_at) VALUES (?, ?, ?, '{}', ?, ?)",
                            (eid, ename, etype, now, now),
                        )
                src = conn.execute("SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (subject,)).fetchone()
                tgt = conn.execute("SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (obj,)).fetchone()
                if src and tgt:
                    rid = str(uuid4())[:12]
                    conn.execute(
                        "INSERT INTO relations (id, source_id, relation_type, target_id, confidence, evidence_text, source_origin, created_at, updated_at) VALUES (?, ?, ?, ?, 0.8, ?, 'heuristic', ?, ?)",
                        (rid, src["id"], predicate, tgt["id"], text[:200], now, now),
                    )
                results.append({"source": subject, "relation": predicate, "target": obj})
        conn.commit()
        conn.close()
        return results

    def stats(self) -> dict:
        conn = self._conn()
        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        relation_count = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        alias_count = conn.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0]
        conn.close()
        return {
            "entities": entity_count,
            "relations": relation_count,
            "aliases": alias_count,
        }

    async def _find_entity_by_name(self, name: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT id, name, entity_type FROM entities WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if not row:
            alias_row = conn.execute(
                "SELECT entity_id FROM entity_aliases WHERE alias = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if alias_row:
                row = conn.execute(
                    "SELECT id, name, entity_type FROM entities WHERE id = ?",
                    (alias_row["entity_id"],),
                ).fetchone()
        conn.close()
        if row:
            return {"id": row["id"], "name": row["name"], "entity_type": row["entity_type"]}
        return None

    async def _link_entity(self, name: str) -> Optional[dict]:
        """Find an existing entity with similar embedding (entity linking)."""
        if not self._embedder.available:
            return None
        name_vec = await self._embedder.embed(name)
        conn = self._conn()
        all_entities = conn.execute(
            "SELECT id, name, entity_type, embedding FROM entities WHERE embedding IS NOT NULL"
        ).fetchall()
        conn.close()

        best_match = None
        best_sim = 0.0
        for e in all_entities:
            evec = blob_to_vec(e["embedding"])
            sim = cosine_similarity(name_vec, evec)
            if sim > best_sim:
                best_sim = sim
                best_match = e

        if best_match and best_sim >= ENTITY_MERGE_THRESHOLD:
            logger.info(f"Entity linked: '{name}' -> '{best_match['name']}' (sim={best_sim:.3f})")
            return {"id": best_match["id"], "name": best_match["name"], "entity_type": best_match["entity_type"]}
        return None

    def _bump_mention(self, entity_id: str):
        conn = self._conn()
        conn.execute(
            "UPDATE entities SET mention_count = mention_count + 1, updated_at = ? WHERE id = ?",
            (time.time(), entity_id),
        )
        conn.commit()
        conn.close()

    def _add_alias(self, entity_id: str, alias: str):
        conn = self._conn()
        existing = conn.execute(
            "SELECT id FROM entity_aliases WHERE entity_id = ? AND alias = ? COLLATE NOCASE",
            (entity_id, alias),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO entity_aliases (id, entity_id, alias, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid4())[:12], entity_id, alias, time.time()),
            )
            conn.commit()
        conn.close()

    @staticmethod
    def _mmr_rerank(results: list[dict], limit: int, diversity: float = 0.3) -> list[dict]:
        """Maximal Marginal Relevance reranking for diversity."""
        if len(results) <= limit:
            return results
        selected = [results[0]]
        candidates = results[1:]
        while len(selected) < limit and candidates:
            best_idx = 0
            best_mmr = -1.0
            for i, cand in enumerate(candidates):
                relevance = cand.get("score", 0)
                max_sim = max(
                    (1.0 if c["name"].lower() == cand["name"].lower() else 0.0)
                    for c in selected
                )
                mmr = (1.0 - diversity) * relevance - diversity * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = i
            selected.append(candidates.pop(best_idx))
        return selected
