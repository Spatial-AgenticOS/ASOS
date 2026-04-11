"""Setup, configuration, identity, and credential endpoints."""

import os
from fastapi import APIRouter

from api.state import state
from config.loader import theora_home
from config.runtime import ollama_base_url

router = APIRouter()


# ── Setup ──

@router.get("/api/setup/status")
async def setup_status():
    """Check if initial setup has been completed."""
    home = theora_home()
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
        for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
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
        os.environ["THEORA_MULTI_AGENT"] = str(enabled).lower()
        state.orchestrator._multi_agent_enabled = enabled
        if enabled and state.orchestrator._multi_agent is None:
            state.orchestrator._init_multi_agent()
        if not enabled:
            state.orchestrator._multi_agent = None
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
            os.environ[f"THEORA_KEY_{skill_id}"] = api_key
    state.config.save_credentials(creds)
    return {"ok": True, "keys_saved": list(creds.keys())}


@router.post("/api/config/validate-key")
async def validate_key(body: dict):
    """Validate an LLM API key by making a test request."""
    provider = body.get("provider", "openai")
    api_key = body.get("api_key", "")
    if not api_key:
        return {"valid": False, "error": "No API key provided"}

    import httpx
    try:
        if provider == "openai":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"valid": True, "provider": "openai", "models": len(resp.json().get("data", []))}
                return {"valid": False, "error": f"API returned {resp.status_code}"}
        elif provider == "groq":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                return {"valid": resp.status_code == 200, "provider": "groq"}
        elif provider == "ollama":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    body.get("base_url", ollama_base_url()) + "/api/tags",
                    timeout=5.0,
                )
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {"valid": True, "provider": "ollama", "models": len(models)}
                return {"valid": False, "error": "Ollama not reachable"}
        return {"valid": False, "error": f"Unknown provider: {provider}"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ── Identity ──

@router.get("/api/identity")
async def get_identity():
    """Get the agent identity configuration."""
    identity_path = theora_home() / "identity.yaml"
    if identity_path.exists():
        try:
            import yaml
            with open(identity_path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {"name": "THEORA", "personality": "", "rules": [], "greeting_style": "", "voice": {"tts_voice": "nova"}}


@router.post("/api/identity")
async def update_identity(body: dict):
    """Update the agent identity configuration."""
    identity_path = theora_home() / "identity.yaml"
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
    home = theora_home()
    agent_name = "THEORA"
    user_name = ""

    identity_path = home / "IDENTITY.yaml"
    if identity_path.exists():
        try:
            import yaml
            with open(identity_path) as f:
                data = yaml.safe_load(f) or {}
            agent_name = data.get("name", "THEORA")
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
    home = theora_home()
    home.mkdir(parents=True, exist_ok=True)

    user_name = identity.get("userName", "").strip()
    location = identity.get("location", "").strip()
    occupation = identity.get("occupation", "").strip()
    interests = identity.get("interests", "").strip()
    agent_name = identity.get("agentName", "THEORA").strip() or "THEORA"
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
