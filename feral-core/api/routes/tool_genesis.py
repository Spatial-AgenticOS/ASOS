"""Tool Genesis REST routes.

Exposes the full propose → approve → promote → execute lifecycle so the
Settings UI and CLI can drive the capability-autopilot flow.
"""
from fastapi import APIRouter, HTTPException
from api.state import state

router = APIRouter(tags=["tool-genesis"])


def _engine_or_503():
    if not state.tool_genesis:
        raise HTTPException(status_code=503, detail="Tool Genesis not initialized")
    return state.tool_genesis


@router.get("/api/tool-genesis/proposals")
async def get_proposals():
    if not state.tool_genesis:
        return {"proposals": []}
    return {"proposals": state.tool_genesis.get_proposals()}


@router.get("/api/tool-genesis/pending")
async def pending_proposals():
    """Unapproved generated tools — for the Settings Proposed Skills card."""
    if not state.tool_genesis:
        return {"proposals": []}
    return {"proposals": state.tool_genesis.list_pending_proposals()}


@router.post("/api/tool-genesis/generate")
async def generate_tool(body: dict):
    engine = _engine_or_503()
    seq_id = body.get("sequence_id", "")
    tool = await engine.generate_tool(seq_id)
    if tool:
        return {
            "success": True,
            "tool": {
                "tool_id": tool.tool_id,
                "name": tool.name,
                "description": tool.description,
                "preview": (tool.python_code or "")[:800],
            },
        }
    return {"success": False, "error": "Generation failed"}


@router.post("/api/tool-genesis/propose")
async def propose_from_intent(body: dict):
    """LLM-draft a new skill from a free-form user intent."""
    engine = _engine_or_503()
    intent = (body or {}).get("intent") or (body or {}).get("text") or ""
    if not intent.strip():
        raise HTTPException(status_code=400, detail="intent is required")
    tool_id = await engine.propose_from_intent(intent)
    if not tool_id:
        return {"success": False, "error": "proposal_failed"}
    gt = engine.get_generated(tool_id)
    return {
        "success": True,
        "tool_id": tool_id,
        "preview": (gt.python_code if gt else "")[:800],
    }


@router.post("/api/tool-genesis/approve")
async def approve_tool(body: dict):
    """Approve a pending proposal AND immediately promote it into SkillRegistry."""
    engine = _engine_or_503()
    tool_id = (body or {}).get("tool_id")
    if not tool_id:
        raise HTTPException(status_code=400, detail="tool_id required")
    if not engine.approve_tool(tool_id):
        raise HTTPException(status_code=404, detail=f"No tool {tool_id}")
    result = engine.promote(tool_id, skill_registry=state.skills)
    return {"success": bool(result.get("promoted")), **result}


@router.post("/api/tool-genesis/execute")
async def execute_tool(body: dict):
    """Execute a generated tool with args (for quick tests or hybrid-approved reuse)."""
    engine = _engine_or_503()
    tool_id = (body or {}).get("tool_id")
    args = (body or {}).get("args") or {}
    if not tool_id:
        raise HTTPException(status_code=400, detail="tool_id required")
    result = await engine.execute_tool(tool_id, args)
    return result


@router.delete("/api/tool-genesis/{tool_id}")
async def delete_tool(tool_id: str):
    engine = _engine_or_503()
    if not engine.reject(tool_id):
        raise HTTPException(status_code=404, detail=f"No tool {tool_id}")
    return {"success": True, "deleted": tool_id}


@router.get("/api/tool-genesis/list")
async def list_generated():
    if not state.tool_genesis:
        return {"tools": []}
    return {"tools": state.tool_genesis.list_generated()}


@router.get("/api/tool-genesis/stats")
async def genesis_stats():
    if not state.tool_genesis:
        return {}
    return state.tool_genesis.stats()
