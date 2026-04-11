"""
FERAL Skill Registry — Community Skill Server
================================================
A minimal FastAPI service for publishing, discovering, and installing
community skills. Deploy at registry.feral.io.

Run locally: uvicorn registry.server:app --port 8080
"""

from __future__ import annotations
import json
import hashlib
import time
import sqlite3
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="FERAL Skill Registry", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = os.getenv("REGISTRY_DB", str(Path.home() / ".feral" / "registry.db"))


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            author TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            manifest TEXT NOT NULL,
            downloads INTEGER DEFAULT 0,
            published_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            checksum TEXT NOT NULL,
            tags TEXT DEFAULT '[]'
        )
    """)
    conn.commit()
    return conn


class PublishRequest(BaseModel):
    manifest: dict
    author_token: str = Field(description="Author authentication token")


class SkillInfo(BaseModel):
    skill_id: str
    version: str
    author: str
    name: str
    description: str
    downloads: int
    published_at: float
    tags: list[str]
    checksum: str


@app.get("/")
def root():
    return {"name": "FERAL Skill Registry", "version": "1.0.0"}


@app.get("/api/v1/skills/search")
def search_skills_v1(
    q: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None),
    sort: str = Query("downloads", regex="^(downloads|published_at|name)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Search skills (v1 API used by marketplace client)."""
    results = _query_skills(q, category, sort, limit, offset)
    return {"results": results}


@app.get("/api/skills", response_model=list[SkillInfo])
def list_skills(
    q: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None),
    sort: str = Query("downloads", regex="^(downloads|published_at|name)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Search and browse published skills."""
    return _query_skills(q, category, sort, limit, offset)


def _query_skills(q, category, sort, limit, offset):
    db = get_db()
    query = "SELECT * FROM skills"
    params = []
    conditions = []

    if q:
        conditions.append("(name LIKE ? OR description LIKE ? OR skill_id LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if category:
        conditions.append("tags LIKE ?")
        params.append(f'%"{category}"%')

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    order_col = {"downloads": "downloads DESC", "published_at": "published_at DESC", "name": "name ASC"}
    query += f" ORDER BY {order_col.get(sort, 'downloads DESC')}"
    query += f" LIMIT {limit} OFFSET {offset}"

    rows = db.execute(query, params).fetchall()
    return [
        SkillInfo(
            skill_id=r["skill_id"], version=r["version"], author=r["author"],
            name=r["name"], description=r["description"], downloads=r["downloads"],
            published_at=r["published_at"], tags=json.loads(r["tags"]),
            checksum=r["checksum"],
        )
        for r in rows
    ]


@app.get("/api/v1/skills/{skill_id}")
def get_skill_v1(skill_id: str):
    """Get full manifest (v1 API)."""
    return _get_skill_impl(skill_id)


@app.get("/api/v1/skills/{skill_id}/download")
def download_skill_v1(skill_id: str, version: str = Query("latest")):
    """Download a skill manifest as JSON (v1 API used by marketplace client)."""
    from starlette.responses import Response
    data = _get_skill_impl(skill_id)
    manifest_bytes = json.dumps(data["manifest"], indent=2).encode()
    return Response(content=manifest_bytes, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename={skill_id}.json"})


@app.get("/api/skills/{skill_id}")
def get_skill(skill_id: str):
    """Get full manifest for a skill."""
    return _get_skill_impl(skill_id)


def _get_skill_impl(skill_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Skill '{skill_id}' not found")
    db.execute("UPDATE skills SET downloads = downloads + 1 WHERE skill_id = ?", (skill_id,))
    db.commit()
    return {
        "skill_id": row["skill_id"],
        "version": row["version"],
        "author": row["author"],
        "manifest": json.loads(row["manifest"]),
        "downloads": row["downloads"] + 1,
        "checksum": row["checksum"],
    }


@app.post("/api/v1/skills")
def publish_skill_v1(req: PublishRequest):
    """Publish a skill (v1 API)."""
    return _publish_skill_impl(req)


@app.post("/api/skills")
def publish_skill(req: PublishRequest):
    """Publish or update a skill."""
    return _publish_skill_impl(req)


def _publish_skill_impl(req: PublishRequest):
    manifest = req.manifest
    skill_id = manifest.get("skill_id")
    if not skill_id:
        raise HTTPException(400, "manifest must include skill_id")

    required = ["brand", "description", "endpoints"]
    for field in required:
        if field not in manifest:
            raise HTTPException(400, f"manifest must include '{field}'")

    brand = manifest.get("brand", {})
    name = brand.get("name", skill_id)
    version = manifest.get("version", "0.0.1")
    author = manifest.get("author", "unknown")
    description = manifest.get("description", "")
    categories = manifest.get("categories", [])
    manifest_json = json.dumps(manifest, sort_keys=True)
    checksum = hashlib.sha256(manifest_json.encode()).hexdigest()[:16]
    now = time.time()

    _validate_manifest_safety(manifest)

    db = get_db()
    existing = db.execute("SELECT skill_id FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()

    if existing:
        db.execute("""
            UPDATE skills SET version=?, name=?, description=?, manifest=?,
            updated_at=?, checksum=?, tags=? WHERE skill_id=?
        """, (version, name, description, manifest_json, now, checksum, json.dumps(categories), skill_id))
    else:
        db.execute("""
            INSERT INTO skills (skill_id, version, author, name, description, manifest,
            published_at, updated_at, checksum, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (skill_id, version, author, name, description, manifest_json, now, now, checksum, json.dumps(categories)))

    db.commit()
    return {"success": True, "skill_id": skill_id, "version": version, "checksum": checksum}


@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: str, author_token: str = Query(...)):
    db = get_db()
    db.execute("DELETE FROM skills WHERE skill_id = ?", (skill_id,))
    db.commit()
    return {"success": True}


@app.get("/api/stats")
def registry_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) as c FROM skills").fetchone()["c"]
    total_downloads = db.execute("SELECT COALESCE(SUM(downloads), 0) as d FROM skills").fetchone()["d"]
    return {"total_skills": total, "total_downloads": total_downloads}


def _validate_manifest_safety(manifest: dict):
    """Basic security validation — prevent malicious manifests."""
    endpoints = manifest.get("endpoints", [])
    for ep in endpoints:
        url = ep.get("url", "")
        if any(bad in url for bad in ["file://", "localhost", "127.0.0.1", "0.0.0.0", "169.254"]):
            raise HTTPException(400, f"Unsafe endpoint URL: {url}")
        method = ep.get("method", "GET")
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "WS_EXECUTE"):
            raise HTTPException(400, f"Invalid method: {method}")
