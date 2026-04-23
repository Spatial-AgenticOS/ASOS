"""REST routes for the digital twin's policy + approval queue."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.state import state

router = APIRouter(tags=["twin"])


def _require_engine():
    engine = getattr(state, "twin_policy", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="TwinPolicyEngine not initialised")
    return engine


# ── policies ─────────────────────────────────────────────────────


@router.get("/api/twin/policies")
async def list_policies():
    engine = _require_engine()
    return {
        "policies": [
            {
                "domain": p.domain,
                "mode": p.mode,
                "time_windows": p.time_windows,
                "max_per_day": p.max_per_day,
                "requires_user_online": p.requires_user_online,
            }
            for p in engine.store.list_policies()
        ]
    }


@router.get("/api/twin/policies/{domain}")
async def get_policy(domain: str):
    engine = _require_engine()
    p = engine.store.get_policy(domain)
    if p is None:
        raise HTTPException(status_code=404, detail="no policy")
    return {
        "domain": p.domain,
        "mode": p.mode,
        "time_windows": p.time_windows,
        "max_per_day": p.max_per_day,
        "requires_user_online": p.requires_user_online,
    }


@router.post("/api/twin/policies")
async def upsert_policy(body: dict):
    engine = _require_engine()
    body = body or {}
    try:
        from agents.twin_policy import TwinPolicy
        policy = TwinPolicy(
            domain=body["domain"],
            mode=body.get("mode", "draft_only"),
            time_windows=body.get("time_windows") or [],
            max_per_day=int(body.get("max_per_day", 10)),
            requires_user_online=bool(body.get("requires_user_online", False)),
        )
        engine.store.upsert_policy(policy)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing field: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "domain": policy.domain}


@router.delete("/api/twin/policies/{domain}")
async def delete_policy(domain: str):
    engine = _require_engine()
    ok = engine.store.delete_policy(domain)
    if not ok:
        raise HTTPException(status_code=404, detail="no policy")
    return {"success": True}


# ── approvals ────────────────────────────────────────────────────


@router.get("/api/twin/approvals")
async def list_approvals(status: str = "", limit: int = 50):
    engine = _require_engine()
    rows = engine.store.list_approvals(status=status, limit=limit)
    return {
        "count": len(rows),
        "approvals": [
            {
                "approval_id": r.approval_id,
                "created_at": r.created_at,
                "domain": r.domain,
                "action": r.action,
                "context": r.context,
                "status": r.status,
                "resolved_at": r.resolved_at,
                "resolved_by": r.resolved_by,
                "execution_result": r.execution_result,
            }
            for r in rows
        ],
    }


@router.post("/api/twin/approvals/{approval_id}/approve")
async def approve(approval_id: str):
    engine = _require_engine()
    row = engine.resolve(approval_id, verdict="approved")
    if row is None:
        raise HTTPException(status_code=404, detail="unknown approval")
    return {"success": True, "status": row.status}


@router.post("/api/twin/approvals/{approval_id}/reject")
async def reject(approval_id: str):
    engine = _require_engine()
    row = engine.resolve(approval_id, verdict="rejected")
    if row is None:
        raise HTTPException(status_code=404, detail="unknown approval")
    return {"success": True, "status": row.status}


# ── status ───────────────────────────────────────────────────────


@router.get("/api/twin/status")
async def twin_status():
    engine = _require_engine()
    policies = engine.store.list_policies()
    pending = engine.store.list_approvals(status="pending", limit=1)
    supervisor = getattr(state, "supervisor", None)
    return {
        "policies": len(policies),
        "pending_approvals": len(pending),
        "supervisor_paused": bool(getattr(supervisor, "paused", False)),
    }
