"""Setup, configuration, identity, and credential endpoints."""

import os
import socket

from fastapi import APIRouter, Request

from api.keys import load_api_key
from api.state import state
from config.loader import feral_home
from config.runtime import ollama_base_url

router = APIRouter()


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@router.get("/api/session/client-key")
async def session_client_key(request: Request):
    """Expose FERAL_API_KEY to same-origin browser on localhost (or when already authenticated)."""
    from security.session_auth import is_localhost

    key = load_api_key()
    if not key:
        return {"key": None}
    host = request.client.host if request.client else None
    auth = request.headers.get("authorization", "")
    if is_localhost(host) or auth == f"Bearer {key}":
        return {"key": key}
    return {"key": None}


@router.get("/api/setup/phone-access")
async def phone_access():
    """Three supported ways to use FERAL from a phone."""
    from config.runtime import brain_port

    port = brain_port()
    ip = _lan_ip()
    base_http = f"http://{ip}:{port}"
    ws_daemon = f"ws://{ip}:{port}/v1/daemon"
    ws_session = f"ws://{ip}:{port}/v1/session"
    return {
        "local_ip": ip,
        "port": port,
        "paths": [
            {
                "id": "native_app",
                "label": "FERAL Node app (recommended)",
                "steps": [
                    "Install the FERAL Node app (iOS / Android)",
                    "Open Settings → Devices → pair phone",
                    "Scan the QR code",
                ],
                "qr_path": "/api/devices/pair/qr",
            },
            {
                "id": "browser",
                "label": "Phone web browser",
                "steps": [
                    "Put the phone on the same Wi‑Fi as this machine",
                    f"Open {base_http}",
                    "Enter the API key from Settings (or ~/.feral/api_key)",
                ],
                "url": base_http,
            },
            {
                "id": "daemon",
                "label": "Phone bridge daemon (advanced)",
                "steps": [
                    "On the phone (e.g. Termux) install the feral-phone-bridge package",
                    "Point it at the brain WebSocket",
                ],
                "command": f"feral-phone-bridge --brain {ws_daemon} --api-key <FERAL_API_KEY>",
                "ws_daemon": ws_daemon,
                "ws_session": ws_session,
            },
        ],
    }


# ── Setup ──

@router.get("/api/setup/status")
async def setup_status():
    """Check if initial setup has been completed."""
    home = feral_home()
    user_md = home / "USER.md"
    has_identity = False
    if user_md.exists():
        content = user_md.read_text().strip()
        has_identity = (
            bool(content)
            and "Tell your agent about yourself" not in content
            and ("My name is" in content or len(content) > 50)
        )
    return {
        "setup_complete": state.config.setup_complete,
        "has_identity": has_identity,
        "settings": state.config.to_client_safe_dict(),
    }


@router.post("/api/setup/complete")
async def complete_setup(body: dict):
    """Mark setup as complete and apply settings."""
    settings = body.get("settings", {})
    credentials = body.get("credentials", {})
    identity = body.get("identity", {})

    if settings:
        state.config.save_user_settings(settings)
    if credentials:
        if credentials.get("GEMINI_API_KEY") and not credentials.get("GOOGLE_API_KEY"):
            credentials["GOOGLE_API_KEY"] = credentials["GEMINI_API_KEY"]
        if credentials.get("GOOGLE_API_KEY") and not credentials.get("GEMINI_API_KEY"):
            credentials["GEMINI_API_KEY"] = credentials["GOOGLE_API_KEY"]
        for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY",
                     "GOOGLE_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
                     "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY"):
            if credentials.get(key):
                os.environ[key] = credentials[key]
        state.config.save_credentials(credentials)

    if identity:
        _write_identity_files(identity)

    state.config.mark_setup_complete()
    state.config.discover()

    return {"ok": True, "setup_complete": True}


# ── Config ──

@router.get("/api/config")
async def get_config():
    """Get current configuration (safe for client, no secrets)."""
    return state.config.to_client_safe_dict()


@router.post("/api/config/update")
async def update_config(body: dict):
    """Update a setting. Body: {section, key, value}"""
    section = body.get("section", "")
    key = body.get("key", "")
    value = body.get("value")
    if not section or not key:
        return {"error": "section and key are required"}
    state.config.update_settings(section, key, value)

    if section == "features" and key == "multi_agent" and state.orchestrator:
        enabled = value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes", "on")
        os.environ["FERAL_MULTI_AGENT"] = str(enabled).lower()
        state.orchestrator._multi_agent_enabled = enabled
        if enabled and state.orchestrator._multi_agent is None:
            state.orchestrator._init_multi_agent()
        if not enabled:
            state.orchestrator._multi_agent = None

    elif section == "llm" and state.orchestrator and state.orchestrator.llm:
        llm_config = state.config._merged.get("llm", {})
        new_provider = llm_config.get("provider", state.orchestrator.llm.provider)
        new_model = llm_config.get("model", "")
        new_base = llm_config.get("base_url", "")
        new_key = os.environ.get(f"{new_provider.upper()}_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        state.orchestrator.llm.switch_provider(new_provider, model=new_model, base_url=new_base, api_key=new_key)

    elif section == "features":
        enabled = str(value).lower() in ("true", "1", "yes", "on")
        if key == "streaming" and state.orchestrator:
            state.orchestrator._streaming_enabled = enabled
            os.environ["FERAL_STREAMING"] = str(enabled).lower()
        elif key == "proactive":
            if state.orchestrator:
                state.orchestrator._proactive_enabled = enabled
            os.environ["FERAL_PROACTIVE"] = str(enabled).lower()
            if hasattr(state, 'proactive') and state.proactive:
                if enabled:
                    import asyncio
                    asyncio.create_task(state.proactive.start())
                else:
                    await state.proactive.stop()
        elif key == "vision":
            os.environ["FERAL_VISION_ENABLED"] = str(enabled).lower()
            if state.orchestrator:
                state.orchestrator._vision_enabled = enabled
            if hasattr(state, 'screen_loop') and state.screen_loop:
                if enabled:
                    import asyncio
                    asyncio.create_task(state.screen_loop.start())
                else:
                    state.screen_loop.stop()
        elif key == "self_learning":
            os.environ["FERAL_SELF_LEARNING"] = str(enabled).lower()

    elif section == "security" and key == "autonomy_mode":
        if state.orchestrator and hasattr(state.orchestrator, 'tool_runner'):
            state.orchestrator.tool_runner.set_autonomy_mode(str(value))

    return {"ok": True, "section": section, "key": key, "value": value}


@router.post("/api/config/credentials")
async def save_credentials(body: dict):
    """Save API credentials. Body: {OPENAI_API_KEY: "...", skill_keys: {...}}"""
    creds = {}
    for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        if key in body:
            creds[key] = body[key]
            os.environ[key] = body[key]
    if "skill_keys" in body:
        creds["skill_keys"] = body["skill_keys"]
        for skill_id, api_key in body["skill_keys"].items():
            os.environ[f"FERAL_KEY_{skill_id}"] = api_key
    state.config.save_credentials(creds)

    if state.orchestrator and state.orchestrator.llm:
        for key_name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
                         "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"):
            if key_name in creds and creds[key_name]:
                provider = state.orchestrator.llm.provider
                state.orchestrator.llm.switch_provider(provider, api_key=creds[key_name])
                break

    if state.channel_manager:
        channel_keys = {
            "FERAL_TELEGRAM_BOT_TOKEN": "telegram",
            "FERAL_DISCORD_BOT_TOKEN": "discord",
            "FERAL_SLACK_BOT_TOKEN": "slack",
        }
        for env_key, channel_type in channel_keys.items():
            token = os.environ.get(env_key, "")
            if token and channel_type not in [ch for ch in state.channel_manager._channels]:
                import asyncio
                asyncio.create_task(state.channel_manager.start_channel(channel_type, {"bot_token": token, "enabled": True}))

    return {"ok": True, "keys_saved": list(creds.keys())}


async def _validate_key_for_provider(provider: str, api_key: str, base_url: str = None) -> tuple[bool, str]:
    """Return (is_valid, message). Makes a real HTTP call to the provider."""
    import httpx

    provider = provider.lower().strip()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "openai":
                r = await client.get(
                    f"{base_url or 'https://api.openai.com'}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "anthropic":
                r = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                )
            elif provider in ("gemini", "google"):
                r = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                )
            elif provider == "groq":
                r = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "deepseek":
                r = await client.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "xai":
                r = await client.get(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "cohere":
                r = await client.get(
                    "https://api.cohere.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "mistral":
                r = await client.get(
                    "https://api.mistral.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "together":
                r = await client.get(
                    "https://api.together.xyz/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "openrouter":
                r = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "ollama":
                url = base_url or ollama_base_url()
                r = await client.get(f"{url}/api/tags")
            elif provider == "lmstudio":
                url = base_url or "http://localhost:1234"
                r = await client.get(f"{url}/v1/models")
            elif provider == "perplexity":
                r = await client.get(
                    "https://api.perplexity.ai/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if r.status_code in (200, 400, 405):
                    return True, "Key validates (method-not-allowed is OK for perplexity)"
            elif provider in ("kimi", "moonshot"):
                r = await client.get(
                    "https://api.moonshot.cn/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider in ("qwen", "dashscope"):
                r = await client.get(
                    "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            else:
                return False, f"Unknown provider: {provider}"

            if r.status_code in (200, 201):
                return True, "Key is valid"
            elif r.status_code in (401, 403):
                return False, f"Invalid or unauthorized key (HTTP {r.status_code})"
            else:
                return False, f"Unexpected response HTTP {r.status_code}: {r.text[:200]}"
    except httpx.TimeoutException:
        return False, "Timeout connecting to provider"
    except httpx.ConnectError as e:
        return False, f"Connection error: {e}"
    except Exception as e:
        return False, f"Validation error: {type(e).__name__}: {e}"


@router.post("/api/config/validate-key")
async def validate_key(body: dict):
    """Validate an LLM API key by making a test request."""
    provider = body.get("provider", "openai")
    api_key = body.get("api_key", "")
    base_url = body.get("base_url", "")

    if not api_key and provider not in ("ollama", "lmstudio"):
        return {"valid": False, "error": "No API key provided"}

    valid, message = await _validate_key_for_provider(provider, api_key, base_url or None)
    return {"valid": valid, "provider": provider, "message": message}


# ── Identity ──

@router.get("/api/identity")
async def get_identity():
    """Get the agent identity configuration."""
    identity_path = feral_home() / "IDENTITY.yaml"
    if identity_path.exists():
        try:
            import yaml
            with open(identity_path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {"name": "FERAL", "personality": "", "rules": [], "greeting_style": "", "voice": {"tts_voice": "nova"}}


@router.post("/api/identity")
async def update_identity(body: dict):
    """Update the agent identity configuration."""
    identity_path = feral_home() / "IDENTITY.yaml"
    try:
        import yaml
        with open(identity_path, "w") as f:
            yaml.dump(body, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


# ── Helpers ──

def _build_greeting() -> str:
    """Build a contextual greeting based on identity files."""
    home = feral_home()
    agent_name = "FERAL"
    user_name = ""

    identity_path = home / "IDENTITY.yaml"
    if identity_path.exists():
        try:
            import yaml
            with open(identity_path) as f:
                data = yaml.safe_load(f) or {}
            agent_name = data.get("name", "FERAL")
        except Exception:
            pass

    user_md = home / "USER.md"
    if user_md.exists():
        try:
            for line in user_md.read_text().splitlines():
                if line.startswith("My name is "):
                    user_name = line.replace("My name is ", "").rstrip(".")
                    break
        except Exception:
            pass

    if user_name:
        return f"{agent_name} connected. Hey {user_name}, how can I help?"
    return f"{agent_name} connected. How can I help?"


def _write_identity_files(identity: dict):
    """Write USER.md, SOUL.md, and IDENTITY.yaml from the setup wizard identity payload."""
    home = feral_home()
    home.mkdir(parents=True, exist_ok=True)

    user_name = identity.get("userName", "").strip()
    location = identity.get("location", "").strip()
    occupation = identity.get("occupation", "").strip()
    interests = identity.get("interests", "").strip()
    agent_name = identity.get("agentName", "FERAL").strip() or "FERAL"
    personality_id = identity.get("personality", "assistant")

    personality_map = {
        "assistant": (
            "You are a warm, capable personal assistant. You speak naturally, like "
            "a trusted colleague who knows the user well. You're direct — no filler, "
            "no over-explaining — but never cold. You proactively notice patterns in "
            "the user's data and mention things that might be useful."
        ),
        "engineer": (
            "You are a precise technical partner. You prefer concrete answers, code, "
            "and data over vague suggestions. You think step-by-step and explain your "
            "reasoning. You're comfortable with complexity and don't over-simplify."
        ),
        "coach": (
            "You are an encouraging wellness coach. You're proactive about the user's "
            "health and wellbeing, noticing patterns in their data. You celebrate "
            "progress, suggest improvements gently, and keep the tone supportive."
        ),
        "minimal": (
            "You are brief and factual. No small talk. No filler. Answer the question, "
            "report the data, execute the task. If there's nothing to say, say nothing."
        ),
    }
    soul = personality_map.get(personality_id, personality_map["assistant"])

    lines = ["# About Me\n"]
    if user_name:
        lines.append(f"My name is {user_name}.")
    if location:
        lines.append(f"I live in {location}.")
    if occupation:
        lines.append(f"I work as {occupation}.")
    if interests:
        lines.append(f"\n## Interests\n{interests}")
    if any([user_name, location, occupation, interests]):
        (home / "USER.md").write_text("\n".join(lines) + "\n")

    (home / "SOUL.md").write_text(f"# {agent_name}\n\n{soul}\n")

    try:
        import yaml
        identity_data = {
            "name": agent_name,
            "tagline": "Your personal AI operating system — local, private, always learning.",
            "personality": soul,
            "rules": [
                "Never make up sensor data or health readings. Only report what's actually connected.",
                "If a tool call fails, explain what went wrong in plain language.",
                "Keep responses concise — 1-3 sentences for simple questions.",
                "Respect user privacy. Everything runs locally unless they explicitly ask to share.",
            ],
            "greeting_style": (
                "Keep greetings brief and contextual. If you know the user's name, use it. "
                "Don't list all your capabilities unless asked."
            ),
            "voice": {"style": "conversational", "tts_voice": "nova", "speed": 1.0},
        }
        (home / "IDENTITY.yaml").write_text(yaml.dump(identity_data, default_flow_style=False, sort_keys=False))
    except ImportError:
        import json
        (home / "IDENTITY.yaml").write_text(json.dumps({"name": agent_name, "personality": soul}, indent=2))
