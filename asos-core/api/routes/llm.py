"""LLM status, switching, and preset endpoints."""

import os
from fastapi import APIRouter

from api.state import state

router = APIRouter()


@router.get("/api/llm/status")
async def llm_status():
    """LLM availability status for the client UI."""
    if not state.orchestrator:
        return {"available": False, "provider": "none", "reason": "Brain not initialized"}
    llm = state.orchestrator.llm
    if not llm:
        return {"available": False, "provider": "none", "reason": "No LLM configured"}
    return {
        "available": getattr(llm, "available", False),
        "provider": getattr(llm, "provider", "unknown"),
        "model": getattr(llm, "model", "unknown"),
    }


@router.post("/api/llm/switch")
async def llm_switch(body: dict):
    """Hot-swap the LLM provider at runtime."""
    if not state.orchestrator or not state.orchestrator.llm:
        return {"error": "Brain not initialized"}
    provider = body.get("provider", "")
    model = body.get("model", "")
    api_key = body.get("api_key", "")
    if not provider:
        return {"error": "provider is required"}
    await state.orchestrator.llm.switch_provider(provider, model=model, api_key=api_key)
    return {
        "success": True,
        "provider": state.orchestrator.llm.provider,
        "model": state.orchestrator.llm.model,
        "available": state.orchestrator.llm.available,
    }


@router.get("/api/llm/presets")
async def llm_presets():
    if not state.orchestrator or not state.orchestrator.llm:
        return {"presets": []}
    return {"presets": state.orchestrator.llm.list_presets()}


@router.post("/api/llm/presets/apply")
async def llm_apply_preset(body: dict):
    if not state.orchestrator or not state.orchestrator.llm:
        return {"error": "Brain not initialized"}
    preset_id = body.get("preset", "")
    if not preset_id:
        return {"error": "preset is required"}
    result = await state.orchestrator.llm.apply_preset(preset_id)
    if result.get("ok"):
        state.config.update_settings("llm", "provider", result.get("provider"))
        state.config.update_settings("llm", "model", result.get("model"))
        if result.get("preset") == "ollama_vision":
            state.config.update_settings("vision", "enabled", True)
            state.config.update_settings("vision", "provider", "ollama")
            state.config.update_settings("vision", "model", result.get("model", "llava"))
    return result


@router.get("/api/voice/status")
async def voice_status():
    """Voice subsystem status."""
    realtime_available = state.realtime_proxy.available if state.realtime_proxy else False
    audio_available = state.audio.available if state.audio else False
    active_sessions = len(state.realtime_proxy._sessions) if state.realtime_proxy else 0
    return {
        "realtime_available": realtime_available,
        "audio_available": audio_available,
        "active_realtime_sessions": active_sessions,
        "wake_word_enabled": bool(state.wake_word and state.wake_word.enabled),
        "tts_voice": os.getenv("THEORA_TTS_VOICE", "nova"),
    }
