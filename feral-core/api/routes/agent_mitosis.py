"""Agent Mitosis REST routes."""
from fastapi import APIRouter
from api.state import state

router = APIRouter(tags=["agent-mitosis"])


@router.get("/api/agents/proposals")
async def get_proposals():
    if not state.agent_mitosis:
        return {"proposals": []}
    return {"proposals": state.agent_mitosis.get_spawn_proposals()}


@router.post("/api/agents/spawn")
async def spawn_specialist(body: dict):
    if not state.agent_mitosis:
        return {"error": "Agent Mitosis not initialized"}
    pattern_id = body.get("pattern_id", "")
    specialist = await state.agent_mitosis.spawn_specialist(pattern_id)
    if specialist:
        return {
            "success": True,
            "agent": {
                "agent_id": specialist.agent_id,
                "name": specialist.name,
                "description": specialist.description,
            },
        }
    return {"success": False, "error": "Spawn failed"}


@router.get("/api/agents/list")
async def list_specialists():
    if not state.agent_mitosis:
        return {"agents": []}
    return {"agents": state.agent_mitosis.list_specialists()}


@router.post("/api/agents/feedback")
async def record_feedback(body: dict):
    if not state.agent_mitosis:
        return {"error": "Agent Mitosis not initialized"}
    agent_id = body.get("agent_id", "")
    positive = body.get("positive", True)
    state.agent_mitosis.record_feedback(agent_id, positive)
    return {"success": True}


@router.get("/api/agents/stats")
async def mitosis_stats():
    if not state.agent_mitosis:
        return {}
    return state.agent_mitosis.stats()
