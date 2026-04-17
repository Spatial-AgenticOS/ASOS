"""Dashboard, system info, health, and activity endpoints."""

import os
import time
from fastapi import APIRouter

try:
    from _version import __version__
except ImportError:
    try:
        from importlib.metadata import version as _pkg_version
        __version__ = _pkg_version("feral-ai")
    except Exception:
        __version__ = "0.0.0-unknown"
from api.state import state
from config.loader import feral_home

router = APIRouter()


@router.get("/api/identity/greeting")
async def identity_greeting():
    """Personalized greeting for the smart empty state."""
    hour = time.localtime().tm_hour
    if hour < 12:
        tod = "Good morning"
    elif hour < 18:
        tod = "Good afternoon"
    else:
        tod = "Good evening"

    name = ""
    user_path = feral_home() / "USER.md"
    try:
        if user_path.exists():
            content = user_path.read_text()
            for line in content.splitlines():
                if line.strip().startswith("- Name:"):
                    name = line.split(":", 1)[1].strip().split()[0]
                    break
    except Exception:
        pass

    greeting = f"{tod}, {name}." if name else f"{tod}."

    health_summary = ""
    try:
        frames = []
        if state.perception:
            for sid in list(getattr(state.perception, '_frames', {}).keys()):
                f = state.perception.get_frame(sid)
                if f and f.heart_rate > 0:
                    frames.append(f)
        if frames:
            f = frames[0]
            health_summary = f"Heart rate {f.heart_rate} bpm, SpO2 {f.spo2_pct}%."
    except Exception:
        pass

    last_memory = ""
    try:
        recent = state.memory.episode_recent(limit=1, session_id=None)
        if recent:
            last_memory = (recent[0].get("summary", "") or "")[:120]
    except Exception:
        pass

    return {
        "name": name,
        "greeting": greeting,
        "health_summary": health_summary,
        "last_memory": last_memory,
    }


@router.get("/health")
async def health():
    """Health check endpoint for Docker HEALTHCHECK and load balancers."""
    boot_data = state._boot_report.to_dict() if hasattr(state, '_boot_report') else {}
    return {"status": "ok", "version": __version__, "boot": boot_data}


@router.get("/api/info")
async def api_info():
    stats = state.memory.stats()
    return {
        "name": "FERAL Brain",
        "version": __version__,
        "status": "running",
        "sessions": len(state.sessions),
        "daemons": list(state.daemons.keys()),
        "devices": len(state.devices),
        "skills": len(state.skill_registry.skills),
        "memory": stats,
        "audio_available": state.audio.available,
        "realtime_available": state.realtime_proxy.available if state.realtime_proxy else False,
    }


@router.get("/api/system/info")
async def system_info():
    """Full system info for the dashboard."""
    stats = state.memory.stats()
    hw_stats = state.device_registry.stats if state.device_registry else {}
    mcp_client_stats = state.mcp_client.stats if state.mcp_client else {}
    channel_stats = state.channel_manager.stats if state.channel_manager else {}
    skill_gen_stats = state.skill_gen.stats if state.skill_gen else {}
    return {
        "version": __version__,
        "config": state.config.to_client_safe_dict(),
        "memory": stats,
        "sessions": len(state.sessions),
        "nodes": list(state.daemons.keys()),
        "devices": len(state.devices),
        "skills": [
            {"skill_id": s.skill_id, "name": s.brand.name, "endpoints": len(s.endpoints)}
            for s in state.skill_registry.skills.values()
        ],
        "audio_available": state.audio.available,
        "hardware": hw_stats,
        "mcp": {
            "server_active": state.mcp_server is not None,
            "client": mcp_client_stats,
        },
        "channels": channel_stats,
        "skill_generator": skill_gen_stats,
        "security": {
            "vault_keys": len(state.vault.list_keys()) if state.vault else 0,
            "max_tier": state.sandbox.max_tier if state.sandbox else "active",
            "policy": state.policy._data.get("name", "default") if state.policy else "none",
        },
        "voice": {
            "audio_available": state.audio.available,
            "realtime_available": state.realtime_proxy.available if state.realtime_proxy else False,
            "active_realtime_sessions": len(state.realtime_proxy._sessions) if state.realtime_proxy else 0,
        },
        "taskflows": state.taskflows.stats() if state.taskflows else {},
        "vision": {
            "change_detector": state.change_detector.stats() if state.change_detector else {},
            "scene_available": state.scene.available if state.scene else False,
        },
        "integrations": {
            "oauth": state.oauth.status() if state.oauth else {},
            "spotify": state.spotify.connected if state.spotify else False,
            "home_assistant": state.home_assistant.connected if state.home_assistant else False,
            "notion": state.notion.connected if state.notion else False,
            "webhooks": state.event_bus.stats() if state.event_bus else {},
        },
        "marketplace": {
            "installed_skills": len(state.marketplace.list_installed()) if state.marketplace else 0,
        },
        "multi_agent": state.orchestrator._multi_agent.stats if state.orchestrator and state.orchestrator._multi_agent else {},
        "orchestrator": state.orchestrator.runtime_status if state.orchestrator else {},
    }


def _check_llm_available() -> bool:
    """Real LLM availability check: key is configured and not in cooldown."""
    if not state.orchestrator:
        return False
    llm = getattr(state.orchestrator, 'llm', None)
    if not llm:
        return False
    try:
        return llm.is_available()
    except Exception:
        return False


async def _get_dashboard_data() -> dict:
    stats = state.memory.stats()
    devices_list = []
    latest_health = {}
    for node_id in state.daemons:
        dev = state.devices.get(node_id, {})
        devices_list.append({"node_id": node_id, "type": dev.get("device_type", dev.get("node_type", "unknown")), "connected": True})
    for sid in state.sessions:
        frame = state.perception.get_frame(sid)
        if frame:
            if frame.heart_rate:
                latest_health["heart_rate"] = frame.heart_rate
            if frame.spo2_pct:
                latest_health["spo2"] = frame.spo2_pct
            if frame.skin_temperature_c:
                latest_health["temperature"] = frame.skin_temperature_c
    boot_data = state._boot_report.to_dict() if hasattr(state, '_boot_report') else {}

    is_demo = getattr(state, "_demo", None) is not None or os.environ.get("FERAL_DEV_DEMO", "").lower() in ("1", "true", "yes")

    somatic_state = {}
    if hasattr(state, 'somatic_engine') and state.somatic_engine and state.sessions:
        for sid in state.sessions:
            vec = state.somatic_engine.get_vector(sid)
            somatic_state = {
                "cognitive_load": vec.cognitive_load,
                "heart_rate": vec.heart_rate,
                "hrv_ms": vec.hrv_ms,
                "spo2_pct": vec.spo2_pct,
                "activity_level": vec.activity_level,
                "circadian_phase": vec.circadian_phase,
            }
            break

    channel_types = []
    if state.channel_manager and hasattr(state.channel_manager, 'channels'):
        for ch_id, ch in state.channel_manager.channels.items():
            if getattr(ch, 'enabled', False):
                channel_types.append({"type": ch_id, "connected": getattr(ch, '_running', False)})

    return {
        "devices": devices_list, "device_count": len(state.daemons),
        "channels": channel_types,
        "session_count": len(state.sessions), "health": latest_health,
        "memory": stats, "skills_count": len(state.skill_registry.skills),
        "llm_available": _check_llm_available(),
        "audio_available": state.audio.available,
        "sync": state.sync_engine.stats if state.sync_engine else {},
        "wasm_available": state.wasm_sandbox.available if state.wasm_sandbox else False,
        "wake_word_enabled": state.wake_word.enabled if state.wake_word else False,
        "taskflows": state.taskflows.stats() if state.taskflows else {},
        "boot": boot_data,
        "demo": is_demo,
        "is_demo_mode": getattr(state, "_demo", None) is not None,
        "somatic": somatic_state,
    }


@router.get("/api/dashboard")
async def dashboard_data():
    """Aggregated data for the live dashboard — weather, devices, health, activity."""
    return await _get_dashboard_data()


@router.get("/api/activity")
async def get_activity():
    """Recent brain activity log."""
    return {"entries": list(state.activity_log)}
