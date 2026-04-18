"""
FERAL Config Loader — Layered Configuration System
=====================================================
Inspired by claw-code-parity's ConfigLoader: merges settings from
multiple sources in priority order.

Hierarchy (highest priority wins):
  1. Environment variables (FERAL_*)
  2. Local config  (.feral/settings.local.json) — machine-specific, gitignored
  3. Project config (.feral/settings.json) — shared with team
  4. User config    (~/.feral/settings.json) — user-global defaults

Credentials are stored separately in ~/.feral/credentials.json
and NEVER merged into settings (blind vault pattern).

Skills are discovered from:
  - ~/.feral/skills/           (user-installed)
  - .feral/skills/             (project-local)
  - Built-in manifests in feral-core/skills/manifests/
"""

from __future__ import annotations
import copy
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("feral.config")

DEFAULT_SETTINGS = {
    "version": "0.4.0",
    "llm": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base_url": "",
        "fallback_providers": [],
    },
    "audio": {
        "stt_provider": "openai",
        "stt_model": "whisper-1",
        "tts_provider": "openai",
        "tts_model": "tts-1",
        "tts_voice": "nova",
    },
    "vision": {
        "enabled": False,
        "max_frame_kb": 512,
        "scene_cooldown": 10,
    },
    "features": {
        "streaming": False,
        "proactive": False,
        "self_learning": True,
        "multi_agent": True,
    },
    "security": {
        "node_api_key": "",
    },
    "skills": {
        "enabled": [],
        "disabled": [],
        "external_directories": [],
    },
    "nodes": {
        "auto_connect": True,
    },
    "ui": {
        "theme": "dark",
        "show_debug": False,
    },
}


def feral_home() -> Path:
    """Resolve the FERAL user config directory (XDG-compliant on Linux)."""
    env_home = os.environ.get("FERAL_HOME")
    if env_home:
        return Path(env_home)

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "feral"

    return Path.home() / ".feral"


def feral_data_home() -> Path:
    """Resolve the FERAL data directory (XDG-compliant on Linux)."""
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "feral"
    return Path.home() / ".feral"


class ConfigLoader:
    """
    Loads and merges FERAL configuration from multiple sources.
    """

    def __init__(self, project_dir: Optional[str] = None):
        self.user_home = feral_home()
        self.data_home = feral_data_home()
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._merged: dict = {}
        self._sources: list[dict] = []
        self._credentials: dict = {}
        self._setup_complete = False

    def discover(self) -> dict:
        """
        Load and merge all config sources. Returns the merged settings dict.
        """
        self._merged = copy.deepcopy(DEFAULT_SETTINGS)
        self._sources = []

        # Layer 1: User config (~/.feral/settings.json)
        user_path = self.user_home / "settings.json"
        self._load_and_merge(user_path, "user")

        # Layer 2: Project config (.feral/settings.json)
        project_path = self.project_dir / ".feral" / "settings.json"
        self._load_and_merge(project_path, "project")

        # Layer 3: Local config (.feral/settings.local.json) — gitignored
        local_path = self.project_dir / ".feral" / "settings.local.json"
        self._load_and_merge(local_path, "local")

        # Layer 4: Environment variable overrides
        self._apply_env_overrides()

        # Load credentials separately
        self._load_credentials()

        # Auto-derive fallback providers from stored keys if not explicitly set
        self._merged.setdefault("llm", {})
        self._merged["llm"]["fallback_providers"] = self._derive_fallback_providers()

        # Check if setup has been completed
        self._setup_complete = self._check_setup_complete()

        sources_desc = ", ".join(s.get("_source", "?") for s in self._sources)
        logger.info(f"Config loaded from: [{sources_desc}] | Setup complete: {self._setup_complete}")
        return self._merged

    def _load_and_merge(self, path: Path, source: str):
        if not path.exists():
            return
        try:
            with open(path) as f:
                data = json.load(f)
            data["_source"] = source
            self._sources.append(data)
            self._deep_merge(self._merged, data)
            logger.debug(f"Loaded config from {path}")
        except Exception as e:
            logger.warning(f"Failed to load config from {path}: {e}")

    def _apply_env_overrides(self):
        """Map FERAL_* environment variables to config keys."""
        env_map = {
            "OPENAI_API_KEY": None,  # handled by credentials
            "FERAL_LLM_PROVIDER": ("llm", "provider"),
            "FERAL_LLM_MODEL": ("llm", "model"),
            "FERAL_LLM_BASE_URL": ("llm", "base_url"),
            "FERAL_VISION_ENABLED": ("vision", "enabled"),
            "FERAL_VISION_MAX_FRAME_KB": ("vision", "max_frame_kb"),
            "FERAL_STREAMING": ("features", "streaming"),
            "FERAL_PROACTIVE": ("features", "proactive"),
            "FERAL_MULTI_AGENT": ("features", "multi_agent"),
            "FERAL_SCENE_COOLDOWN": ("vision", "scene_cooldown"),
            "FERAL_STT_PROVIDER": ("audio", "stt_provider"),
            "FERAL_TTS_PROVIDER": ("audio", "tts_provider"),
            "FERAL_TTS_VOICE": ("audio", "tts_voice"),
            "NODE_API_KEY": ("security", "node_api_key"),
        }

        for env_key, config_path in env_map.items():
            value = os.environ.get(env_key)
            if value is None or config_path is None:
                continue
            section, key = config_path
            if section not in self._merged:
                self._merged[section] = {}
            # Type coercion
            if isinstance(self._merged[section].get(key), bool):
                self._merged[section][key] = value.lower() in ("true", "1", "yes")
            elif isinstance(self._merged[section].get(key), int):
                try:
                    self._merged[section][key] = int(value)
                except ValueError:
                    pass
            else:
                self._merged[section][key] = value

    def _load_credentials(self):
        """Load credentials from a separate file (never merged into settings)."""
        cred_path = self.user_home / "credentials.json"
        if cred_path.exists():
            try:
                with open(cred_path) as f:
                    self._credentials = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load credentials: {e}")

        # Also check env for API keys
        _api_key_envs = (
            "OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY",
            "EXA_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY", "BRAVE_API_KEY",
            "GITHUB_TOKEN", "SPOTIFY_CLIENT_ID",
        )
        for env_key in _api_key_envs:
            value = os.environ.get(env_key)
            if value:
                self._credentials[env_key] = value

        # Skill-specific keys from FERAL_KEY_* pattern
        for key, value in os.environ.items():
            if key.startswith("FERAL_KEY_"):
                skill_id = key[10:].lower()  # FERAL_KEY_web_search -> web_search
                if "skill_keys" not in self._credentials:
                    self._credentials["skill_keys"] = {}
                self._credentials["skill_keys"][skill_id] = value

    def _derive_fallback_providers(self) -> list[str]:
        """Auto-populate fallback_providers from providers that have stored keys."""
        existing = self._merged.get("llm", {}).get("fallback_providers") or []
        if existing:
            return existing

        _KEY_MAP = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "groq": "GROQ_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "xai": "XAI_API_KEY",
            "cohere": "COHERE_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }

        primary = self._merged.get("llm", {}).get("provider", "openai").lower()
        providers = []
        for prov, key_name in _KEY_MAP.items():
            if prov == primary:
                continue
            key = os.environ.get(key_name, "").strip()
            if not key and key_name == "GEMINI_API_KEY":
                key = os.environ.get("GOOGLE_API_KEY", "").strip()
            if not key:
                key = self._credentials.get(key_name, "").strip() if isinstance(self._credentials.get(key_name), str) else ""
            if key:
                providers.append(prov)
        return providers

    def _check_setup_complete(self) -> bool:
        """Check if the full setup has been done (LLM key + identity)."""
        if self._merged.get("meta", {}).get("setup_complete"):
            return True
        has_llm_key = bool(
            self._credentials.get("OPENAI_API_KEY")
            or self._credentials.get("ANTHROPIC_API_KEY")
            or self._credentials.get("GOOGLE_API_KEY")
            or self._credentials.get("GROQ_API_KEY")
            or self._credentials.get("OPENROUTER_API_KEY")
            or self._credentials.get("DEEPSEEK_API_KEY")
            or self._credentials.get("MOONSHOT_API_KEY")
            or self._credentials.get("DASHSCOPE_API_KEY")
            or self._merged.get("llm", {}).get("provider") == "ollama"
        )
        if not has_llm_key:
            return False
        user_md = self.user_home / "USER.md"
        if not user_md.exists():
            return False
        content = user_md.read_text().strip()
        if not content or "Tell your agent about yourself" in content:
            return False
        if "My name is" not in content and len(content) < 50:
            return False
        return True

    @staticmethod
    def _deep_merge(base: dict, overlay: dict):
        """Recursively merge overlay into base, overlay wins on conflicts."""
        for key, value in overlay.items():
            if key.startswith("_"):
                continue
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigLoader._deep_merge(base[key], value)
            else:
                base[key] = value

    # ─── Public API ───

    @property
    def settings(self) -> dict:
        if not self._merged:
            self.discover()
        return self._merged

    @property
    def credentials(self) -> dict:
        return self._credentials

    @property
    def setup_complete(self) -> bool:
        return self._setup_complete

    def get(self, section: str, key: str, default=None):
        return self._merged.get(section, {}).get(key, default)

    def get_credential(self, key: str, default: str = "") -> str:
        return self._credentials.get(key, default)

    def get_skill_key(self, skill_id: str) -> Optional[str]:
        return self._credentials.get("skill_keys", {}).get(skill_id)

    # ─── Write API ───

    def save_user_settings(self, settings: dict):
        """Write settings to the user config file."""
        self.user_home.mkdir(parents=True, exist_ok=True)
        path = self.user_home / "settings.json"
        with open(path, "w") as f:
            json.dump(settings, f, indent=2)
        logger.info(f"User settings saved to {path}")

    def save_credentials(self, credentials: dict):
        """Write credentials to the credentials file (separate from settings)."""
        self.user_home.mkdir(parents=True, exist_ok=True)
        path = self.user_home / "credentials.json"
        self._credentials.update(credentials)
        with open(path, "w") as f:
            json.dump(self._credentials, f, indent=2)
        os.chmod(path, 0o600)  # Read/write only by owner
        logger.info(f"Credentials saved to {path}")

    def update_settings(self, section: str, key: str, value):
        """Update a single setting and persist to user config."""
        if section not in self._merged:
            self._merged[section] = {}
        self._merged[section][key] = value

        # Load existing user settings and update
        user_path = self.user_home / "settings.json"
        user_settings = {}
        if user_path.exists():
            try:
                with open(user_path) as f:
                    user_settings = json.load(f)
            except Exception:
                pass
        if section not in user_settings:
            user_settings[section] = {}
        user_settings[section][key] = value
        self.save_user_settings(user_settings)

    def mark_setup_complete(self):
        """Mark that initial setup has been completed."""
        self.update_settings("meta", "setup_complete", True)
        self._setup_complete = True

    def discover_skills_directories(self) -> list[Path]:
        """Find all directories that may contain skill manifests."""
        dirs = []
        # Built-in
        builtin = Path(__file__).parent.parent / "skills" / "manifests"
        if builtin.exists():
            dirs.append(builtin)
        # User-installed
        user_skills = self.user_home / "skills"
        if user_skills.exists():
            dirs.append(user_skills)
        # Project-local
        project_skills = self.project_dir / ".feral" / "skills"
        if project_skills.exists():
            dirs.append(project_skills)
        # External directories from config
        for ext_dir in self._merged.get("skills", {}).get("external_directories", []):
            p = Path(ext_dir)
            if p.exists():
                dirs.append(p)
        return dirs

    def export_as_env(self) -> dict[str, str]:
        """Export settings as environment variables for backward compatibility."""
        env = {}
        llm = self._merged.get("llm", {})
        env["FERAL_LLM_PROVIDER"] = llm.get("provider", "openai")
        env["FERAL_LLM_MODEL"] = llm.get("model", "gpt-4o-mini")
        if llm.get("base_url"):
            env["FERAL_LLM_BASE_URL"] = llm["base_url"]

        vision = self._merged.get("vision", {})
        env["FERAL_VISION_ENABLED"] = str(vision.get("enabled", False)).lower()
        env["FERAL_VISION_MAX_FRAME_KB"] = str(vision.get("max_frame_kb", 512))

        features = self._merged.get("features", {})
        env["FERAL_STREAMING"] = str(features.get("streaming", False)).lower()
        env["FERAL_PROACTIVE"] = str(features.get("proactive", False)).lower()
        env["FERAL_MULTI_AGENT"] = str(features.get("multi_agent", True)).lower()

        env["NODE_API_KEY"] = self._merged.get("security", {}).get("node_api_key", "")

        # Credentials — LLMs + messaging channels
        credential_env_keys = (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
            "GROQ_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
            "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY",
            "TAVILY_API_KEY", "BRAVE_API_KEY", "EXA_API_KEY",
            "SERPER_API_KEY", "PERPLEXITY_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID",
            "GITHUB_TOKEN", "SPOTIFY_CLIENT_ID",
            "FERAL_TELEGRAM_BOT_TOKEN",
            "FERAL_SLACK_BOT_TOKEN", "FERAL_SLACK_APP_TOKEN", "FERAL_SLACK_SIGNING_SECRET",
            "FERAL_DISCORD_BOT_TOKEN",
            "FERAL_WHATSAPP_PHONE_NUMBER_ID", "FERAL_WHATSAPP_ACCESS_TOKEN",
            "FERAL_WHATSAPP_VERIFY_TOKEN", "FERAL_WHATSAPP_APP_SECRET",
        )
        for cred_key in credential_env_keys:
            if self._credentials.get(cred_key):
                env[cred_key] = self._credentials[cred_key]

        return env

    def to_client_safe_dict(self) -> dict:
        """Return settings safe to send to the client (no credentials)."""
        safe = dict(self._merged)
        safe.pop("security", None)
        safe["setup_complete"] = self._setup_complete
        safe["has_llm_key"] = bool(
            self._credentials.get("OPENAI_API_KEY")
            or self._credentials.get("ANTHROPIC_API_KEY")
            or self._credentials.get("GOOGLE_API_KEY")
            or self._credentials.get("GROQ_API_KEY")
        )
        safe["has_skill_keys"] = list(self._credentials.get("skill_keys", {}).keys())
        safe["skill_directories"] = [str(d) for d in self.discover_skills_directories()]
        return safe
