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
    """Re-enter execution for a paused consciousness entity.

    Unlike set_status('active') — which just flips a flag — this route
    rehydrates the entity's context_json and tells the matching runtime
    (TaskFlowRuntime / IntentCompiler / Orchestrator) to pick up where
    it left off. The per-kind rehydration map:

      - kind=flow    -> state.taskflows.resume_flow(flow_id)
                        (re-enters _run_flow at context.step)
      - kind=intent  -> state.intent_compiler.resume(intent_id)
                        (re-activates the intent in today()/list_active())
      - kind=thought -> orchestrator prepends the thought text to the
                        next turn's history via the 'paused_thought'
                        hook so the LLM sees the half-formed sentence
                        before the user's next message
      - kind=turn    -> no-op beyond status flip; the next client turn
                        naturally picks it up
      - kind=device_stream -> also a status-flip only; streams are
                        re-opened by the daemon on reconnect

    The set_status('active') call happens LAST so observers see the
    entity appear in list_active() only after the runtime has been
    nudged. If rehydration raises, the status stays paused and the
    caller gets ``{ok: False, error: "..."}``.
    """
    s = _store()
    entity_id = (body or {}).get("id")
    if not entity_id:
        raise HTTPException(status_code=400, detail="`id` required")

    entity = s.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Unknown consciousness entity {entity_id!r}")

    # Per-kind rehydration. Each branch is wrapped so a failure in one
    # runtime doesn't take the endpoint down — the caller sees
    # {ok: False, reason: ...} and can retry.
    rehydrated = {"kind": entity.kind, "method": "status_only"}

    try:
        if entity.kind == "flow":
            runtime = getattr(state, "taskflows", None)
            if runtime is not None and hasattr(runtime, "resume_flow"):
                runtime.resume_flow(entity.id)
                rehydrated["method"] = "taskflow_resume_flow"
            elif runtime is not None and hasattr(runtime, "get_flow"):
                # Older runtimes just flip status; the scheduler picks
                # it up on the next tick.
                rehydrated["method"] = "taskflow_get_flow_only"
        elif entity.kind == "intent":
            compiler = getattr(state, "intent_compiler", None)
            if compiler is not None and hasattr(compiler, "resume"):
                compiler.resume(entity.id)
                rehydrated["method"] = "intent_compiler_resume"
        elif entity.kind == "thought":
            orch = getattr(state, "orchestrator", None)
            text = (entity.context_json or {}).get("text", "")
            if orch is not None and text and hasattr(orch, "register_paused_thought"):
                orch.register_paused_thought(
                    session_id=entity.owner_session_id or "",
                    thought_id=entity.id,
                    text=text,
                )
                rehydrated["method"] = "orchestrator_register_paused_thought"
    except Exception as exc:
        logger.warning(
            "Rehydrating %s %s failed, leaving status=paused: %s",
            entity.kind, entity.id, exc,
        )
        return {"ok": False, "reason": str(exc), "rehydrated": rehydrated}

    ok = s.resume(entity_id)
    return {"ok": ok, "rehydrated": rehydrated}


@router.post("/api/consciousness/abandon")
async def post_abandon(body: dict) -> dict:
    s = _store()
    entity_id = (body or {}).get("id")
    if not entity_id:
        raise HTTPException(status_code=400, detail="`id` required")
    return {"ok": s.abandon(entity_id)}
