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
    """Spawn a specialist agent via one of two paths:

    1. ``pattern_id`` path — legacy Mitosis path. The engine generates a
       system prompt from a recurring ``TaskPattern`` via LLM.
    2. persona-manifest path — caller supplies a full persona body
       (``system_prompt``, ``tool_permissions``, ``memory_filter``, etc.)
       and we register it directly without calling the LLM. This is the
       v2 Agents "Spawn specialist from persona" path; before this fix
       the button sent this body shape and it was silently dropped.

    If both are present, persona-manifest wins (it's the explicit case).
    """
    if not state.agent_mitosis:
        return {"success": False, "error": "Agent Mitosis not initialized"}

    system_prompt = (body.get("system_prompt") or "").strip()
    name = (body.get("name") or "").strip()
    if system_prompt and name:
        # Persona-manifest path — no LLM call, no pattern required.
        specialist = state.agent_mitosis.register_specialist_from_manifest(
            agent_id=body.get("agent_id") or None,
            name=name,
            description=(body.get("description") or "").strip(),
            system_prompt=system_prompt,
            tool_permissions=body.get("tool_permissions") or [],
            source_pattern=(body.get("source_pattern") or "").strip(),
            schedule=body.get("schedule"),
            memory_filter=body.get("memory_filter"),
        )
        return {
            "success": True,
            "source": "persona_manifest",
            "agent": {
                "agent_id": specialist.agent_id,
                "name": specialist.name,
                "description": specialist.description,
                "tool_permissions": specialist.tool_permissions,
                "memory_filter": specialist.memory_filter,
            },
        }

    pattern_id = (body.get("pattern_id") or "").strip()
    if not pattern_id:
        return {
            "success": False,
            "error": "Either pattern_id or {name + system_prompt} required.",
        }

    specialist = await state.agent_mitosis.spawn_specialist(pattern_id)
    if specialist:
        return {
            "success": True,
            "source": "pattern",
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
