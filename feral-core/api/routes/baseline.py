"""Baseline learning engine REST endpoints."""

from dataclasses import asdict
from fastapi import APIRouter, Query

from api.state import state

router = APIRouter(tags=["baseline"])


@router.get("/api/baseline/summary")
async def baseline_summary():
    if not state.baseline_engine:
        return {"error": "Baseline engine not initialised", "metrics_tracked": 0, "recent_alerts": 0, "categories": []}
    return state.baseline_engine.summary()


@router.get("/api/baseline/metrics")
async def baseline_metrics():
    if not state.baseline_engine:
        return {"metrics": []}
    metrics = state.baseline_engine.get_all_baselines()
    return {
        "metrics": [asdict(m) for m in metrics],
    }


@router.get("/api/baseline/alerts")
async def baseline_alerts(since: float = Query(default=None)):
    if not state.baseline_engine:
        return {"alerts": []}
    alerts = state.baseline_engine.get_alerts(since=since)
    return {
        "alerts": [asdict(a) for a in alerts],
    }
