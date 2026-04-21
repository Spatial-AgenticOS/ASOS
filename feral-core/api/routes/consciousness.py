"""/api/consciousness/* — expose the in-flight operational state.

Five endpoints:

* ``GET  /api/consciousness/state``     — full list of active entities.
* ``GET  /api/consciousness/summary``   — one-paragraph natural summary
  used by the v2 Home "Welcome back, you were working on..." banner.
* ``POST /api/consciousness/snapshot``  — return a snapshot blob + write
  the default file so a crashing Brain still leaves a recoverable copy.
* ``POST /api/consciousness/restore``   — accept a snapshot blob OR read
  the default file on disk; returns the number of entities restored.
* ``POST /api/consciousness/heartbeat`` — keepalive for a specific id.

The store lives on ``state.consciousness``. When absent (old state
bootstraps pre-5-tier) the endpoints all return 503 with a helpful
error rather than crashing — keeps backwards-compat for installs
that didn't run the 2026.4.22+ boot path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from api.state import state

logger = logging.getLogger("feral.api.consciousness")

router = APIRouter(tags=["consciousness"])


def _store():
    s = getattr(state, "consciousness", None)
    if s is None:
        raise HTTPException(status_code=503, detail="Consciousness store not initialised")
    return s


@router.get("/api/consciousness/state")
async def get_state(
    kind: Optional[str] = None,
    owner_session_id: Optional[str] = None,
    include_abandoned: bool = False,
) -> dict:
    s = _store()
    entities = s.list_active(
        kind=kind,
        owner_session_id=owner_session_id,
        include_abandoned=include_abandoned,
    )
    return {
        "count": len(entities),
        "entities": [e.to_dict() for e in entities],
    }


@router.get("/api/consciousness/summary")
async def get_summary() -> dict:
    s = _store()
    return {"summary": s.natural_summary()}


@router.post("/api/consciousness/snapshot")
async def post_snapshot(body: dict | None = None) -> dict:
    """Write a snapshot blob to disk + return it.

    Called by shutdown hooks + by the UI's "I'm about to close the lid"
    button. The default path (``~/.feral/consciousness.json``) is used
    unless the body supplies ``path``.
    """
    from memory.consciousness import default_snapshot_path

    s = _store()
    blob = s.snapshot()
    path = Path((body or {}).get("path") or default_snapshot_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(blob, indent=2))
    except Exception as exc:
        logger.warning("Failed to write consciousness snapshot to %s: %s", path, exc)
    return {
        "ok": True,
        "count": blob.get("count", 0),
        "path": str(path),
        "blob": blob,
    }


@router.post("/api/consciousness/restore")
async def post_restore(body: dict | None = None) -> dict:
    """Restore from a blob or the default file on disk.

    Body options (all optional):
      * ``blob``: a dict with ``schema, entities`` keys — restored directly
      * ``path``: a file path containing the snapshot JSON

    Without either, reads the default path.
    """
    from memory.consciousness import default_snapshot_path

    s = _store()
    body = body or {}
    blob: Optional[dict[str, Any]] = body.get("blob")
    if blob is None:
        path = Path(body.get("path") or default_snapshot_path())
        if not path.exists():
            return {"ok": False, "restored": 0, "reason": f"no snapshot at {path}"}
        try:
            blob = json.loads(path.read_text())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"malformed snapshot: {exc}")

    restored = s.restore(blob or {})
    return {"ok": True, "restored": restored}


@router.post("/api/consciousness/heartbeat")
async def post_heartbeat(body: dict) -> dict:
    s = _store()
    entity_id = (body or {}).get("id")
    if not entity_id:
        raise HTTPException(status_code=400, detail="`id` required")
    ok = s.heartbeat(entity_id)
    return {"ok": ok}


@router.post("/api/consciousness/pause")
async def post_pause(body: dict) -> dict:
    s = _store()
    entity_id = (body or {}).get("id")
    if not entity_id:
        raise HTTPException(status_code=400, detail="`id` required")
    return {"ok": s.pause(entity_id)}


@router.post("/api/consciousness/resume")
async def post_resume(body: dict) -> dict:
    s = _store()
    entity_id = (body or {}).get("id")
    if not entity_id:
        raise HTTPException(status_code=400, detail="`id` required")
    return {"ok": s.resume(entity_id)}


@router.post("/api/consciousness/abandon")
async def post_abandon(body: dict) -> dict:
    s = _store()
    entity_id = (body or {}).get("id")
    if not entity_id:
        raise HTTPException(status_code=400, detail="`id` required")
    return {"ok": s.abandon(entity_id)}
