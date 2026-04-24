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


def _resolve_twin():
    """Return the bound :class:`DigitalTwin` instance, or ``None``.

    Lightweight test boots use a ``MagicMock`` for ``state``, which
    means a bare ``getattr(state, "digital_twin", None)`` returns an
    auto-generated mock (truthy but useless). We detect that by
    requiring the ``list_executors`` method to actually exist on the
    real DigitalTwin class — anything else is treated as "no twin
    wired" and the route falls back to the pre-honesty behaviour
    (every persisted policy is returned).
    """
    twin = getattr(state, "digital_twin", None)
    if twin is None:
        return None
    list_fn = getattr(twin, "list_executors", None)
    if not callable(list_fn):
        return None
    try:
        from agents.digital_twin import DigitalTwin
    except Exception:
        return None
    if not isinstance(twin, DigitalTwin):
        return None
    return twin


def _wired_domains(twin) -> set[str]:
    if twin is None:
        return set()
    try:
        return {entry["domain"] for entry in twin.list_executors()}
    except Exception:
        return set()


def _domain_label(twin, domain: str) -> str:
    if twin is None:
        return ""
    try:
        return twin._domain_labels.get(domain, "")  # noqa: SLF001
    except Exception:
        return ""


# ── policies ─────────────────────────────────────────────────────


@router.get("/api/twin/policies")
async def list_policies():
    """Return only policies whose executor is wired right now.

    Two-bucket payload:
      * ``policies``: domains that have BOTH a stored policy AND a
        wired executor — these get the live Draft / Auto / Off toggles.
      * ``disconnected``: domains the user previously configured but
        whose backing channel/integration has since been removed —
        rendered as a dimmed row with a Reconnect hint and no toggles
        active.

    A separate ``available`` list (every wired executor regardless of
    whether the user has a policy yet) lets the v2 UI render an
    "Available executors" section for honest discovery.
    """
    engine = _require_engine()
    twin = _resolve_twin()
    wired = _wired_domains(twin)
    available_entries: list[dict] = []
    if twin is not None:
        try:
            available_entries = list(twin.list_executors())
        except Exception:
            available_entries = []

    active: list[dict] = []
    disconnected: list[dict] = []
    for p in engine.store.list_policies():
        row = {
            "domain": p.domain,
            "mode": p.mode,
            "time_windows": p.time_windows,
            "max_per_day": p.max_per_day,
            "requires_user_online": p.requires_user_online,
            "label": _domain_label(twin, p.domain),
            "wired": twin is None or p.domain in wired,
        }
        if twin is None or p.domain in wired:
            active.append(row)
        else:
            disconnected.append(row)

    return {
        "policies": active,
        "disconnected": disconnected,
        "available": available_entries,
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
