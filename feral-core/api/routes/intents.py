from fastapi import APIRouter
from api.state import state

router = APIRouter(tags=["intents"])


@router.post("/api/intents/compile")
async def compile_intent(body: dict):
    if not state.intent_compiler:
        return {"error": "Intent Compiler not initialized"}
    intent_text = body.get("intent", "")
    if not intent_text:
        return {"error": "intent text is required"}
    plan = await state.intent_compiler.compile_intent(intent_text)
    return {
        "success": True,
        "plan": {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "actions": [
                {
                    "action_id": a.action_id,
                    "description": a.description,
                    "tool_hint": a.tool_hint,
                    "difficulty": a.difficulty,
                    "completed": a.completed,
                }
                for a in plan.micro_actions
            ],
            "progress": plan.progress,
            "status": plan.status,
        },
    }


@router.get("/api/intents/list")
async def list_intents():
    if not state.intent_compiler:
        return {"plans": []}
    return {"plans": state.intent_compiler.list_plans()}


@router.get("/api/intents/today")
async def today_actions():
    if not state.intent_compiler:
        return {"actions": []}
    return {"actions": state.intent_compiler.get_today_actions()}


@router.post("/api/intents/{plan_id}/complete/{action_id}")
async def complete_action(plan_id: str, action_id: str, body: dict = {}):
    if not state.intent_compiler:
        return {"error": "Not initialized"}
    result = body.get("result", "")
    ok = state.intent_compiler.complete_action(plan_id, action_id, result)
    return {"success": ok}


@router.get("/api/intents/stats")
async def intent_stats():
    if not state.intent_compiler:
        return {}
    return state.intent_compiler.stats()
