"""Skill generation, approval, and listing endpoints."""

from fastapi import APIRouter

from api.state import state

router = APIRouter()


@router.post("/api/skills/generate")
async def generate_skill(body: dict):
    """Generate a new skill from a capability description."""
    capability = body.get("capability", "")
    service = body.get("service", "")
    if not capability:
        return {"error": "capability is required"}
    if not state.skill_gen:
        return {"error": "Skill generator not initialized"}
    manifest = await state.skill_gen.generate_skill(capability, service)
    if manifest:
        return {"ok": True, "manifest": manifest, "needs_approval": True}
    return {"ok": False, "error": "Failed to generate skill"}


@router.post("/api/skills/approve")
async def approve_skill(body: dict):
    """Approve a pending generated skill — registers it live."""
    skill_id = body.get("skill_id", "")
    if not skill_id:
        return {"error": "skill_id is required"}
    success = await state.skill_gen.approve_skill(skill_id)
    return {"ok": success, "skill_id": skill_id, "registered": success}


@router.post("/api/skills/reject")
async def reject_skill(body: dict):
    """Reject a pending generated skill."""
    skill_id = body.get("skill_id", "")
    state.skill_gen.reject_skill(skill_id)
    return {"ok": True, "skill_id": skill_id}


@router.get("/api/skills/pending")
async def pending_skills():
    """Get all skills waiting for user approval."""
    if not state.skill_gen:
        return {"pending": []}
    return {"pending": state.skill_gen.get_pending_skills()}


@router.get("/skills")
async def list_skills():
    return [
        {
            "skill_id": s.skill_id,
            "name": s.brand.name,
            "description": s.description,
            "endpoints": len(s.endpoints),
            "trigger_phrases": s.trigger_phrases,
        }
        for s in state.skill_registry.skills.values()
    ]
