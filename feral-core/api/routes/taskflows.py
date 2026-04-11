"""TaskFlow CRUD endpoints."""

from fastapi import APIRouter

from api.state import state

router = APIRouter()


@router.post("/api/taskflows")
async def create_taskflow(body: dict):
    """Create a persistent background TaskFlow."""
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    steps = body.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return {"error": "steps (non-empty list) is required"}
    session_id = body.get("session_id", "")
    title = body.get("title", "Background TaskFlow")
    context = body.get("context", {})
    try:
        flow = state.taskflows.create_flow(
            session_id=session_id,
            title=title,
            steps=steps,
            context=context,
        )
        return flow
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/taskflows")
async def list_taskflows(status: str = "", session_id: str = "", limit: int = 50):
    if not state.taskflows:
        return {"flows": []}
    return {"flows": state.taskflows.list_flows(status=status, session_id=session_id, limit=limit)}


@router.get("/api/taskflows/{flow_id}")
async def get_taskflow(flow_id: str):
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    flow = state.taskflows.get_flow(flow_id)
    if not flow:
        return {"error": f"TaskFlow not found: {flow_id}"}
    return flow


@router.post("/api/taskflows/{flow_id}/resume")
async def resume_taskflow(flow_id: str):
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    flow = state.taskflows.resume_flow(flow_id)
    if not flow:
        return {"error": f"TaskFlow not found: {flow_id}"}
    return flow


@router.post("/api/taskflows/{flow_id}/cancel")
async def cancel_taskflow(flow_id: str):
    if not state.taskflows:
        return {"error": "TaskFlow runtime not initialized"}
    flow = state.taskflows.cancel_flow(flow_id)
    if not flow:
        return {"error": f"TaskFlow not found: {flow_id}"}
    return flow
