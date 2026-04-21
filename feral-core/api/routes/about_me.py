"""REST routes exposing the AboutMeStore self-model.

Routes
------
GET    /api/about-me                 — list all facts (filter by kind/tag)
GET    /api/about-me/summary         — counts + system-prompt preview
POST   /api/about-me                 — create or upsert a fact
POST   /api/about-me/{id}/confirm    — bump confidence to 1.0
POST   /api/about-me/{id}/reject     — convert the fact to a taboo
DELETE /api/about-me/{id}            — hard-delete the fact
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agents.about_me import FACT_KINDS, FACT_SOURCES, AboutMeFact
from api.state import state

logger = logging.getLogger("feral.api.about_me")

router = APIRouter(tags=["about_me"])


class UpsertFactRequest(BaseModel):
    kind: str = Field(..., description=f"One of: {', '.join(FACT_KINDS)}")
    text: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source: str = Field(default="user_stated", description=f"One of: {', '.join(FACT_SOURCES)}")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: Optional[float] = None
    fact_id: Optional[str] = None


def _fact_to_dict(f: AboutMeFact) -> dict:
    return f.to_dict()


def _require_store():
    store = getattr(state, "about_me", None)
    if store is None:
        raise HTTPException(status_code=503, detail="AboutMeStore not initialised")
    return store


@router.get("/api/about-me")
async def list_facts(
    kind: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    include_expired: bool = Query(default=False),
):
    store = _require_store()
    if kind and kind not in FACT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown kind {kind!r}. Must be one of: {', '.join(FACT_KINDS)}",
        )
    facts = store.list(kind=kind, tag=tag, include_expired=include_expired)
    return {
        "facts": [_fact_to_dict(f) for f in facts],
        "count": len(facts),
        "kinds_supported": list(FACT_KINDS),
    }


@router.get("/api/about-me/summary")
async def about_me_summary():
    store = _require_store()
    summary = store.summary()
    summary["system_prompt_preview"] = store.system_prompt_chunk()
    return summary


@router.post("/api/about-me")
async def upsert_fact(req: UpsertFactRequest):
    store = _require_store()
    if req.kind not in FACT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown kind {req.kind!r}. Must be one of: {', '.join(FACT_KINDS)}",
        )
    if req.source not in FACT_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source {req.source!r}. Must be one of: {', '.join(FACT_SOURCES)}",
        )
    try:
        fact = store.upsert(
            kind=req.kind,  # type: ignore[arg-type]
            text=req.text,
            tags=req.tags,
            source=req.source,  # type: ignore[arg-type]
            confidence=req.confidence,
            expires_at=req.expires_at,
            fact_id=req.fact_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "fact": _fact_to_dict(fact)}


@router.post("/api/about-me/{fact_id}/confirm")
async def confirm_fact(fact_id: str):
    store = _require_store()
    fact = store.confirm(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail=f"Unknown fact id {fact_id}")
    return {"success": True, "fact": _fact_to_dict(fact)}


@router.post("/api/about-me/{fact_id}/reject")
async def reject_fact(fact_id: str):
    store = _require_store()
    fact = store.reject(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail=f"Unknown fact id {fact_id}")
    return {"success": True, "fact": _fact_to_dict(fact)}


@router.delete("/api/about-me/{fact_id}")
async def delete_fact(fact_id: str):
    store = _require_store()
    if not store.delete(fact_id):
        raise HTTPException(status_code=404, detail=f"Unknown fact id {fact_id}")
    return {"success": True}
