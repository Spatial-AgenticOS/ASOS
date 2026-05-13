"""PR 10: file/media upload route.

Single canonical entrypoint for chat composer attachments::

    POST /api/uploads          (multipart/form-data; file=<bytes>)
    GET  /api/uploads          list recent
    GET  /api/uploads/{id}     metadata for one upload
    GET  /api/uploads/{id}/raw stream the original bytes
    DELETE /api/uploads/{id}   remove (operator-initiated)
    GET  /api/uploads/stats    storage stats (count + quotas)

This route replaces the broken split where the web client sent
multipart and the wiki PDF endpoint expected JSON. Wiki PDF ingest
now goes through ``POST /api/uploads`` → orchestrator-attached
reference → memory wiki, but that is a downstream concern.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.state import state
from memory.uploads import UploadQuotaExceeded

logger = logging.getLogger("feral.api.uploads")

router = APIRouter(tags=["uploads"])


def _require_store():
    store = getattr(state, "uploads", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Upload store not initialised. Restart `feral brain` so the "
                "upload service can bind to $FERAL_HOME/uploads."
            ),
        )
    return store


@router.post("/api/uploads")
async def upload_file(file: UploadFile = File(...)):
    """Accept a multipart file and return the canonical ``UploadRecord``.

    The store enforces a per-file size quota and a total-store quota.
    A quota violation returns 413 (Payload Too Large) with the limit
    in the detail — never a silent truncation."""
    store = _require_store()
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="file is required")

    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to read upload: {exc}") from exc

    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    try:
        record = store.store(
            data=data,
            filename=file.filename,
            content_type=(file.content_type or "application/octet-stream"),
        )
    except UploadQuotaExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("upload store failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"upload failed: {exc}") from exc

    return record.as_dict()


@router.get("/api/uploads")
async def list_uploads(limit: int = 50):
    store = _require_store()
    return {"uploads": [r.as_dict() for r in store.list_recent(limit=limit)]}


@router.get("/api/uploads/stats")
async def upload_stats():
    return _require_store().stats()


@router.get("/api/uploads/{upload_id}")
async def get_upload(upload_id: str):
    store = _require_store()
    record = store.get(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown upload_id")
    return record.as_dict()


@router.get("/api/uploads/{upload_id}/raw")
async def get_upload_raw(upload_id: str):
    store = _require_store()
    record = store.get(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown upload_id")
    return FileResponse(
        record.path,
        media_type=record.content_type,
        filename=record.filename,
    )


@router.delete("/api/uploads/{upload_id}")
async def delete_upload(upload_id: str):
    store = _require_store()
    if not store.delete(upload_id):
        raise HTTPException(status_code=404, detail="unknown upload_id")
    return {"deleted": upload_id}
