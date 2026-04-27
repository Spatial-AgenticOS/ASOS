from __future__ import annotations

import json
import logging

from models.protocol import FeralMessage, SDUIPayload, TextResponsePayload
from agents.chat_sanitizer import sanitize_assistant_display_text

logger = logging.getLogger("feral.orchestrator")


async def send_text(orchestrator, session_id: str, text: str):
    # Defense in depth: even non-streaming callers that hand us raw
    # model text benefit from the same artifact scrubber the stream
    # path uses.
    clean = sanitize_assistant_display_text(text) if text else text
    await orchestrator.send(
        session_id,
        FeralMessage(
            session_id=session_id,
            hop="brain",
            type="text_response",
            payload=TextResponsePayload(text=clean).model_dump(),
        ),
    )


async def try_send_sdui(orchestrator, session_id: str, text: str):
    """Try to parse text as SDUI JSON, fall back to plain text."""
    try:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:-3].strip()
        elif cleaned.startswith("```\n"):
            cleaned = cleaned[4:-3].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:-3].strip()
        sdui = json.loads(cleaned)
        if "type" in sdui:
            await orchestrator.send(
                session_id,
                FeralMessage(
                    session_id=session_id,
                    hop="brain",
                    type="sdui",
                    payload=SDUIPayload(root=sdui).model_dump(),
                ),
            )
            return
    except json.JSONDecodeError:
        pass
    await send_text(orchestrator, session_id, text)


async def try_genui_for_result(orchestrator, session_id: str, tool_call: dict, result_data: dict):
    """Generate and send SDUI for tool results when the data is rich enough."""
    if not isinstance(result_data, dict):
        return

    display_data = result_data.get("data") if isinstance(result_data.get("data"), dict) else result_data
    envelope_keys = {
        "success",
        "status_code",
        "error",
        "ok",
        "status",
        "created_at",
        "_anti_loop_guidance",
        "_anti_loop_streak",
    }
    display_data = {k: v for k, v in display_data.items() if k not in envelope_keys} if isinstance(display_data, dict) else display_data
    if not isinstance(display_data, dict) or not display_data:
        return

    parts = tool_call["name"].split("__", 1)
    skill_id = parts[0] if len(parts) == 2 else tool_call["name"]
    endpoint_id = parts[1] if len(parts) == 2 else ""
    skill = orchestrator.skills.skills.get(skill_id)
    if not skill:
        return

    endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
    ui_hint = endpoint.ui_hint if endpoint else None

    try:
        engine = getattr(orchestrator, "_genui_engine", None)
        if engine is not None:
            sdui = await engine.generate_for_data(
                data=display_data,
                skill_brand=skill.brand.model_dump(),
                ui_hint=ui_hint,
                endpoint_id=endpoint_id,
            )
        else:
            sdui = orchestrator.genui.generate(
                data=display_data,
                skill_brand=skill.brand.model_dump(),
                ui_hint=ui_hint,
                endpoint_id=endpoint_id,
            )
        if sdui and "type" in sdui:
            await orchestrator.send(
                session_id,
                FeralMessage(
                    session_id=session_id,
                    hop="brain",
                    type="sdui",
                    payload=SDUIPayload(root=sdui).model_dump(),
                ),
            )
    except Exception as e:
        logger.debug(f"GenUI generation for {tool_call['name']} skipped: {e}")
