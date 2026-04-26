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
    6-hour disk cache is stale. ``force=true`` ignores the TTL — that's
    what the "Refresh models" button hits. The response carries
    ``source: "live"|"cache"|"fallback"`` and an optional ``warning``
    string set when the live attempt failed (e.g. wrong API key) so the
    v2 picker can render a chip explaining the stale list.
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
        "warning": cached.warning or "",
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


def _persist_key(env_var: str, api_key: str) -> dict:
    """Write *api_key* through every persistence layer we have.

    Returns ``{ok, vault, credentials_json, env, warnings}`` so the
    caller (REST endpoint) can surface honest success/failure state
    to the UI instead of silently swallowing errors.
    """
    warnings: list[str] = []
    vault_ok = False
    creds_ok = False

    if env_var:
        os.environ[env_var] = api_key

    if state.vault is not None and env_var:
        try:
            state.vault.store(env_var, api_key, stored_by="settings")
            vault_ok = True
        except Exception as exc:
            warnings.append(f"vault.store({env_var}) failed: {exc}")
            logger.warning("vault.store failed for %s: %s", env_var, exc)

    if state.config is not None and env_var:
        try:
            state.config.save_credentials({env_var: api_key})
            creds_ok = True
        except Exception as exc:
            warnings.append(f"save_credentials({env_var}) failed: {exc}")
            logger.warning("save_credentials failed for %s: %s", env_var, exc)

    return {
        "ok": vault_ok or creds_ok,
        "vault": vault_ok,
        "credentials_json": creds_ok,
        "env": bool(env_var),
        "warnings": warnings,
    }


@router.post("/api/llm/providers/{provider_id}/configure")
async def configure_llm_provider(provider_id: str, req: ConfigureRequest):
    """Re-bind an adapter with a fresh key / base URL without restarting.

    The API key is:
      1. written to the BlindVault (primary, encrypted-at-rest store).
      2. routed through ``ConfigLoader.save_credentials`` which, post-W24b,
         also writes to the BlindVault (and NEVER to plaintext
         ``credentials.json``) — this second call keeps the in-memory
         ``ConfigLoader._credentials`` dict in sync for boot-time env
         export and is otherwise idempotent with step 1.
      3. exported to ``os.environ`` so the running ``LLMProvider`` sees
         it without waiting for a reboot.

    ``settings.json`` itself never stores the plaintext key — only the
    currently-selected provider + model + base_url.
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

    desc = catalog.get_descriptor(provider_id)
    env_var = desc.credential_env_var if desc else ""
    persisted: dict = {"ok": True, "warnings": []}
    if req.api_key:
        persisted = _persist_key(env_var, req.api_key)

    if req.base_url and state.config is not None:
        try:
            state.config.update_settings("llm", "base_url", req.base_url)
        except Exception as exc:
            logger.debug("update_settings(base_url) failed: %s", exc)

    return {
        "success": True,
        "status": catalog.status_for(provider_id).to_dict(),
        "persisted": persisted,
    }


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


@router.get("/api/llm/health")
async def llm_health():
    """Active provider + every fallback + cooldown state.

    Used by the v2 Settings → Providers → Fallbacks card to render
    green/amber/red dots per candidate so the user can see exactly why
    the agent fell over to a different provider this minute.
    """
    if not state.orchestrator or not state.orchestrator.llm:
        return {"available": False, "active": None, "candidates": [], "fallback_providers": []}
    return state.orchestrator.llm.health_snapshot()


@router.post("/api/llm/config")
async def set_llm_config(req: LLMConfigRequest):
    """Persist llm.* settings + route the key into vault + credentials +
    env + hot-swap the running LLMProvider.

    This is the single entry point the v2 Settings → Providers "Save &
    switch" button hits. After this call completes successfully the
    next chat turn uses the new provider — no reboot needed.
    """
    catalog = _require_catalog()
    resolved = catalog.resolve_alias(req.provider) or req.provider
    if catalog.get_descriptor(resolved) is None:
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider {req.provider!r}; resolve via /api/llm/providers",
        )
    if state.config is None:
        raise HTTPException(status_code=503, detail="ConfigLoader not initialised")

    # Auto-prepend the previous primary as a fallback so failover works
    # by default. User can still explicitly pass `fallback_providers`
    # (including []) to override this.
    previous_provider = state.config.get("llm", "provider", "") or ""
    state.config.update_settings("llm", "provider", resolved)
    state.config.update_settings("llm", "model", req.model)
    if req.base_url is not None:
        state.config.update_settings("llm", "base_url", req.base_url)
    if req.fallback_providers is not None:
        fallbacks = list(req.fallback_providers)
    else:
        existing = state.config.get("llm", "fallback_providers", []) or []
        fallbacks = [p for p in existing if p != resolved]
        if previous_provider and previous_provider != resolved and previous_provider not in fallbacks:
            fallbacks.insert(0, previous_provider)
    state.config.update_settings("llm", "fallback_providers", fallbacks)

    desc = catalog.get_descriptor(resolved)
    env_var = desc.credential_env_var if desc else ""
    persisted: dict = {"ok": True, "warnings": []}
    if req.api_key:
        persisted = _persist_key(env_var, req.api_key)
        catalog.configure(resolved, api_key=req.api_key, base_url=req.base_url)

    state.config.update_settings("meta", "setup_complete", True)

    # Hot-swap the running LLMProvider so the next chat turn uses the
    # new config without waiting for a Brain reboot. Happens even when
    # no api_key was supplied (user just switching between already-
    # configured providers).
    reconfigure_result: dict = {"ok": False, "reason": "orchestrator_missing"}
    if state.orchestrator and state.orchestrator.llm:
        try:
            reconfigure_result = await state.orchestrator.llm.reconfigure(
                provider=resolved,
                model=req.model,
                api_key=req.api_key or "",
                base_url=req.base_url or "",
            )
            # Push the new fallback list into the running LLM so
            # chat_with_failover picks it up on the very next turn.
            cur = state.orchestrator.llm._config if isinstance(state.orchestrator.llm._config, dict) else {}
            state.orchestrator.llm.set_config({**cur, "fallback_providers": fallbacks})
        except Exception as exc:
            logger.warning("reconfigure after set_llm_config failed: %s", exc)
            reconfigure_result = {"ok": False, "reason": str(exc)}

    return {
        "success": True,
        "provider": resolved,
        "model": req.model,
        "persisted": persisted,
        "reconfigured": reconfigure_result,
    }
