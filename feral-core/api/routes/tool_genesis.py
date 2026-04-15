"""Tool Genesis REST routes."""
from fastapi import APIRouter
from api.state import state

router = APIRouter(tags=["tool-genesis"])


@router.get("/api/tool-genesis/proposals")
async def get_proposals():
    if not state.tool_genesis:
        return {"proposals": []}
    return {"proposals": state.tool_genesis.get_proposals()}


@router.post("/api/tool-genesis/generate")
async def generate_tool(body: dict):
    if not state.tool_genesis:
        return {"error": "Tool Genesis not initialized"}
    seq_id = body.get("sequence_id", "")
    tool = await state.tool_genesis.generate_tool(seq_id)
    if tool:
        return {
            "success": True,
            "tool": {"tool_id": tool.tool_id, "name": tool.name, "description": tool.description},
        }
    return {"success": False, "error": "Generation failed"}


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
