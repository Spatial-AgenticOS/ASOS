"""W17: Sessions REST surface.

Currently exposes a single endpoint::

    POST /api/sessions/{session_id}/spawn
        body: {kind, scope_key, model_override?}
        returns: {child_session_id}

The route is GATED by the Supervisor: if the Supervisor is paused or a
``policy_gate`` is registered and returns ``"denied"``, the request is
audited and rejected before the spawner runs. This keeps the human-in-
the-loop "big red pause button" semantics intact for any future
session-management endpoints we add here.

See docs/OPENCLAW_LESSONS.md §2 (no-bypass doctrine) and §10 W17.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from api.state import state
from agents.subagent_spawner import SubagentNotAllowed

logger = logging.getLogger("feral.api.sessions")

router = APIRouter(tags=["sessions"])


def _require_supervisor():
    sup = getattr(state, "supervisor", None)
    if sup is None:
        raise HTTPException(status_code=503, detail="Supervisor not initialised")
    return sup


def _gate_through_supervisor(
    sup,
    *,
    session_id: str,
    kind: str,
    scope_key: str,
    model_override: str | None,
) -> None:
    """Apply the supervisor pause + policy_gate before any spawn work.

    This mirrors the gate pattern in ``agents/supervisor.py`` so the
    route does not bypass approval. We construct a SupervisorEvent
    on the same shape the wrapper uses, then check pause and policy.
    """
    from agents.supervisor import (
        SupervisorBlocked,
        SupervisorEvent,
        _hash_payload,
        _summarise,
    )

    payload = {
        "kind": kind,
        "scope_key": scope_key,
        "model_override": model_override,
    }
    event = SupervisorEvent(
        event_id=str(uuid4()),
        ts=time.time(),
        source="api",
        kind="sessions_spawn",
        session_id=str(session_id or ""),
        actor="user",
        payload_hash=_hash_payload(payload),
        payload_summary=_summarise(payload),
        decision="allowed",
        latency_ms=0,
        detail={"route": "POST /api/sessions/{id}/spawn"},
    )

    if getattr(sup, "paused", False):
        event.decision = "denied"
        event.detail["reason"] = "supervisor_paused"
        sup._record(event)
        raise HTTPException(status_code=423, detail="Supervisor is paused")

    gate = getattr(sup, "policy_gate", None)
    if gate is not None:
        try:
            verdict = gate(event) or "allowed"
        except Exception as exc:
            logger.exception("policy_gate raised: %s", exc)
            verdict = "allowed"
        event.decision = verdict
        if verdict == "denied":
            event.detail["reason"] = "policy_denied"
            sup._record(event)
            raise HTTPException(status_code=403, detail="Policy denied")
        if verdict == "queued":
            event.detail["reason"] = "policy_queued"
            sup._record(event)
            raise HTTPException(status_code=202, detail="Spawn queued by policy")

    sup._record(event)


@router.post("/api/sessions/{session_id}/spawn")
async def post_spawn_subsession(session_id: str, body: dict | None = None):
    """Spawn a child subsession of *session_id*.

    Body shape: ``{"kind": str, "scope_key": str, "model_override"?: str}``.
    Returns ``{"child_session_id": str}`` on success.
    """
    body = body or {}
    kind = body.get("kind")
    scope_key = body.get("scope_key")
    model_override = body.get("model_override")

    if not isinstance(kind, str) or not kind.strip():
        raise HTTPException(status_code=400, detail="'kind' is required")
    if not isinstance(scope_key, str) or not scope_key.strip():
        raise HTTPException(status_code=400, detail="'scope_key' is required")
    if model_override is not None and not isinstance(model_override, str):
        raise HTTPException(status_code=400, detail="'model_override' must be a string")

    sup = _require_supervisor()
    _gate_through_supervisor(
        sup,
        session_id=session_id,
        kind=kind,
        scope_key=scope_key,
        model_override=model_override,
    )

    orch = getattr(state, "orchestrator", None)
    if orch is None or not hasattr(orch, "spawn_subsession"):
        raise HTTPException(status_code=503, detail="Orchestrator not initialised")

    try:
        child_id = await orch.spawn_subsession(
            session_id,
            kind,
            scope_key=scope_key,
            model_override=model_override,
        )
    except SubagentNotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.exception("spawn_subsession failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"spawn failed: {exc}") from exc

    return {"child_session_id": child_id}
