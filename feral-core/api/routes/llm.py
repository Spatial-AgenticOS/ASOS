"""LLM status, provider catalog, model discovery, switching, preset endpoints.

The `providers` + `providers/{id}/models` routes are the contract the
CLI setup wizard and v2 /setup page both read so they can never drift
from the runtime's view of the world (see
`feral-core/providers/catalog.py`).
"""

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.state import state

logger = logging.getLogger("feral.api.llm")

router = APIRouter()


def _require_catalog():
    catalog = getattr(state, "provider_catalog", None)
    if catalog is None:
        raise HTTPException(status_code=503, detail="ProviderCatalog not initialised")
    return catalog


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
        "tts_voice": os.getenv("FERAL_TTS_VOICE", "nova"),
    }


# ----------------------------------------------------------------------
# Provider + model discovery (ProviderCatalog-backed)
# ----------------------------------------------------------------------


@router.get("/api/llm/providers")
async def list_llm_providers():
    """Return every registered provider with its static metadata + live status.

    Renders the side-by-side table in the CLI + v2 Setup flow. ``configured``
    is True when the provider either doesn't need a key or has one in env +
    vault; ``reachable`` stays null until the client calls ``probe`` so this
    route is cheap enough to call on every page load.
    """
    catalog = _require_catalog()
    descriptors = catalog.list_providers()
    payload = []
    for desc in descriptors:
        status = catalog.status_for(desc.provider_id)
        payload.append({
            **status.to_dict(),
            "credential_env_var": desc.credential_env_var,
            "aliases": list(desc.aliases),
            "notes": desc.notes,
        })
    return {"providers": payload, "count": len(payload)}


@router.get("/api/llm/providers/{provider_id}")
async def get_llm_provider(provider_id: str):
    catalog = _require_catalog()
    if catalog.get_descriptor(provider_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown provider_id {provider_id!r}")
    status = catalog.status_for(provider_id)
    return status.to_dict()


@router.get("/api/llm/providers/{provider_id}/models")
async def list_llm_provider_models(provider_id: str, live: bool = True, force: bool = False):
    """Return the model list for a provider.

    ``live=true`` (default) refreshes from the upstream API when the
    24-hour disk cache is stale. ``force=true`` ignores the TTL. The
    response carries ``source: "live"|"cache"|"fallback"`` so clients
    can render a "last refreshed Nm ago" hint.
    """
    catalog = _require_catalog()
    if catalog.get_descriptor(provider_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown provider_id {provider_id!r}")
    cached = await catalog.list_models(provider_id, live=live, force=force)
    return {
        "provider_id": provider_id,
        "models": cached.models,
        "source": cached.source,
        "last_refresh": cached.last_refresh,
        "count": len(cached.models),
    }


@router.post("/api/llm/providers/{provider_id}/probe")
async def probe_llm_provider(provider_id: str):
    """Probe a provider: can we reach it right now with the current creds?

    Used by the wizard to turn "needs API key" into "ready" the moment
    the user enters a valid key, and to render a clear unreachable
    state for Ollama / LMStudio when the local server isn't running.
    """
    catalog = _require_catalog()
    if catalog.get_descriptor(provider_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown provider_id {provider_id!r}")
    status = await catalog.probe(provider_id)
    return status.to_dict()


class ConfigureRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/llm/providers/{provider_id}/configure")
async def configure_llm_provider(provider_id: str, req: ConfigureRequest):
    """Re-bind an adapter with a fresh key / base URL without restarting.

    The API key is routed through the BlindVault (if wired); never
    written to ``settings.json`` in plaintext. ``settings.json`` only
    stores the currently-selected provider + model + base_url.
    """
    catalog = _require_catalog()
    if catalog.get_descriptor(provider_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown provider_id {provider_id!r}")
    try:
        catalog.configure(
            provider_id,
            api_key=req.api_key,
            base_url=req.base_url,
            **req.extra,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if req.api_key and state.vault is not None:
        desc = catalog.get_descriptor(provider_id)
        env_var = desc.credential_env_var if desc else ""
        if env_var:
            try:
                state.vault.store(env_var, req.api_key, stored_by="setup_wizard")
            except Exception as exc:
                logger.debug("vault.store failed for %s: %s", env_var, exc)
    if req.base_url and state.config is not None:
        try:
            state.config.update_settings("llm", "base_url", req.base_url)
        except Exception:
            pass
    return {"success": True, "status": catalog.status_for(provider_id).to_dict()}


# ----------------------------------------------------------------------
# Active LLM config (settings.json-backed)
# ----------------------------------------------------------------------


@router.get("/api/llm/config")
async def get_llm_config():
    """Return the current llm.* settings snapshot.

    Never includes the API key itself — just whether a key is
    configured for the selected provider.
    """
    if state.config is None:
        raise HTTPException(status_code=503, detail="ConfigLoader not initialised")
    provider = state.config.get("llm", "provider", "") or ""
    model = state.config.get("llm", "model", "") or ""
    base_url = state.config.get("llm", "base_url", "") or ""
    fallbacks = state.config.get("llm", "fallback_providers", []) or []
    catalog = getattr(state, "provider_catalog", None)
    configured = False
    if catalog is not None:
        desc = catalog.get_descriptor(provider)
        if desc is not None:
            configured = catalog.status_for(desc.provider_id).configured
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "fallback_providers": list(fallbacks),
        "configured": configured,
    }


class LLMConfigRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    fallback_providers: Optional[list[str]] = None


@router.post("/api/llm/config")
async def set_llm_config(req: LLMConfigRequest):
    """Persist llm.* settings + optional key routing into the vault."""
    catalog = _require_catalog()
    resolved = catalog.resolve_alias(req.provider) or req.provider
    if catalog.get_descriptor(resolved) is None:
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider {req.provider!r}; resolve via /api/llm/providers",
        )
    if state.config is None:
        raise HTTPException(status_code=503, detail="ConfigLoader not initialised")
    state.config.update_settings("llm", "provider", resolved)
    state.config.update_settings("llm", "model", req.model)
    if req.base_url is not None:
        state.config.update_settings("llm", "base_url", req.base_url)
    if req.fallback_providers is not None:
        state.config.update_settings("llm", "fallback_providers", req.fallback_providers)
    if req.api_key:
        desc = catalog.get_descriptor(resolved)
        env_var = desc.credential_env_var if desc else ""
        if env_var and state.vault is not None:
            try:
                state.vault.store(env_var, req.api_key, stored_by="setup_wizard")
                os.environ[env_var] = req.api_key
            except Exception as exc:
                logger.debug("vault.store for %s failed: %s", env_var, exc)
        catalog.configure(resolved, api_key=req.api_key, base_url=req.base_url)
    state.config.update_settings("meta", "setup_complete", True)
    return {"success": True, "provider": resolved, "model": req.model}
