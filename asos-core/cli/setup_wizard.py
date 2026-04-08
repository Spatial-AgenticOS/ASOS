"""
THEORA Interactive Onboarding
==============================
Like `openclaw onboard` — one guided flow that configures everything.

Steps:
  1. Welcome + what THEORA is
  2. LLM provider + API key (validated)
  3. Model selection
  4. Tell the agent about YOU (USER.md)
  5. Agent personality / SOUL.md
  6. Optional tool keys (search, weather, image gen)
  7. Summary + how to start

All config is saved to ~/.theora/ — no env vars needed.
"""

from __future__ import annotations
import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

from config.loader import theora_home
from config.runtime import ollama_base_url

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

THEORA_HOME = theora_home()

PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "desc": "GPT-4o, realtime voice, DALL-E image gen",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "default_model": "gpt-4o",
        "voice": True,
        "key_hint": "Starts with sk-...",
    },
    "anthropic": {
        "name": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "desc": "Claude Sonnet/Opus, strong reasoning",
        "models": ["claude-sonnet-4-20250514", "claude-3.5-sonnet-20241022", "claude-3-opus-20240229"],
        "default_model": "claude-sonnet-4-20250514",
        "voice": False,
        "key_hint": "Starts with sk-ant-...",
    },
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GOOGLE_API_KEY",
        "desc": "Gemini 2.0 Flash, realtime voice, multimodal",
        "models": ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"],
        "default_model": "gemini-2.0-flash-exp",
        "voice": True,
        "key_hint": "From Google AI Studio",
    },
    "groq": {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "desc": "Ultra-fast inference, Llama/Mixtral models",
        "models": ["llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
        "default_model": "llama-3.1-70b-versatile",
        "voice": False,
        "key_hint": "From console.groq.com",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "env_key": "",
        "desc": "Free, private, runs on your machine",
        "models": [],
        "default_model": "",
        "voice": False,
        "key_hint": "No key needed — just install Ollama",
    },
}

TOOL_KEYS = [
    {
        "env": "TAVILY_API_KEY",
        "name": "Tavily",
        "desc": "Web search (best quality)",
        "hint": "From tavily.com — free tier available",
        "optional": True,
    },
    {
        "env": "OPENWEATHER_API_KEY",
        "name": "OpenWeatherMap",
        "desc": "Weather data",
        "hint": "From openweathermap.org — free tier",
        "optional": True,
    },
    {
        "env": "BRAVE_API_KEY",
        "name": "Brave Search",
        "desc": "Web search (alternative)",
        "hint": "From brave.com/search/api",
        "optional": True,
    },
]

PERSONALITY_PRESETS = {
    "assistant": {
        "label": "Personal Assistant",
        "desc": "Warm, direct, and efficient. Remembers your preferences.",
        "soul": textwrap.dedent("""\
            You are a warm, capable personal assistant. You speak naturally, like
            a trusted colleague who knows the user well. You're direct — no filler,
            no over-explaining — but never cold. You proactively notice patterns in
            the user's data and mention things that might be useful. You remember
            past conversations and learn preferences over time. When you don't know
            something, you say so honestly.
        """),
    },
    "engineer": {
        "label": "Technical Partner",
        "desc": "Precise, analytical, code-first. Minimal small talk.",
        "soul": textwrap.dedent("""\
            You are a senior engineer partner. You think in systems, prefer data
            over opinion, and communicate with precision. When asked a question,
            you give the answer first, then context. You use technical language
            naturally but explain when asked. You suggest better approaches when
            you see them. You don't sugarcoat — if something is wrong, you say it.
        """),
    },
    "coach": {
        "label": "Wellness Coach",
        "desc": "Encouraging, health-focused, motivational.",
        "soul": textwrap.dedent("""\
            You are a supportive health and wellness coach. You celebrate progress,
            no matter how small. You interpret health data with context and empathy —
            not just numbers. You encourage consistency over perfection. You know when
            to push and when to back off. You make health data approachable and
            actionable instead of overwhelming.
        """),
    },
    "minimal": {
        "label": "Minimal",
        "desc": "Extremely concise. Short answers. Zero filler.",
        "soul": textwrap.dedent("""\
            You are extremely concise. One sentence when possible. No greetings,
            no filler, no "certainly" or "of course". Just the answer. Use bullet
            points for lists. Numbers without prose. You only elaborate when the
            user explicitly asks for more detail.
        """),
    },
    "custom": {
        "label": "Custom",
        "desc": "Write your own personality from scratch.",
        "soul": "",
    },
}


def _looks_like_vision_model(model_name: str) -> bool:
    lower = (model_name or "").lower()
    return any(token in lower for token in ("llava", "moondream", "qwen2-vl", "minicpm-v", "bakllava", "gemma3"))


def run_setup():
    """Entry point — called by `theora setup` or the install script."""
    if HAS_RICH:
        wizard = OnboardWizard(Console())
    else:
        wizard = OnboardWizardPlain()
    try:
        asyncio.run(wizard.run())
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled. Run `theora setup` anytime to continue.\n")


class OnboardWizard:
    """Rich-powered interactive onboarding."""

    def __init__(self, console: Console):
        self.c = console
        self.config: dict = {}
        self.creds: dict = {}

    async def run(self):
        THEORA_HOME.mkdir(parents=True, exist_ok=True)
        self._load_existing_creds()

        self.c.print()
        self.c.print(Panel.fit(
            "[bold cyan]Welcome to THEORA[/]\n\n"
            "[dim]THEORA is an open-source AI operating system that lives on your machine.\n"
            "It can control your computer, talk to your devices, remember everything,\n"
            "and generate rich UI — all while keeping your data private.\n\n"
            "This wizard will set everything up in about 2 minutes.[/]",
            border_style="cyan",
            padding=(1, 2),
        ))
        self.c.print()

        await self._step_provider()
        await self._step_model()
        await self._step_about_you()
        await self._step_personality()
        await self._step_tool_keys()
        self._save_all()
        self._step_finish()

    def _load_existing_creds(self):
        creds_path = THEORA_HOME / "credentials.json"
        if creds_path.exists():
            try:
                self.creds = json.loads(creds_path.read_text())
            except Exception:
                self.creds = {}

    # ── Step 1: Provider ────────────────────────────────────

    async def _step_provider(self):
        self.c.print(Panel(
            "[bold]Step 1 · LLM Provider[/]\n"
            "[dim]Which AI model provider do you want to use?[/]",
            style="blue",
        ))

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Provider", style="cyan", width=18)
        table.add_column("Description", width=45)
        table.add_column("Voice", width=6)
        table.add_column("Status", width=16)

        provider_keys = list(PROVIDERS.keys())
        for i, pid in enumerate(provider_keys, 1):
            p = PROVIDERS[pid]
            env_key = p["env_key"]
            has_key = bool(self.creds.get(env_key) or os.getenv(env_key, "")) if env_key else False
            status = "[green]configured[/]" if has_key else "[dim]not set[/]"
            if pid == "ollama":
                status = "[dim]local[/]"
            voice = "[green]yes[/]" if p["voice"] else "[dim]no[/]"
            table.add_row(str(i), p["name"], p["desc"], voice, status)

        self.c.print(table)
        self.c.print()

        choice = Prompt.ask(
            "Choose provider",
            choices=provider_keys,
            default="openai",
        )

        provider = PROVIDERS[choice]
        self.config["provider"] = choice

        if choice == "ollama":
            await self._check_ollama()
        elif provider["env_key"]:
            existing = self.creds.get(provider["env_key"]) or os.getenv(provider["env_key"], "")
            if existing:
                masked = existing[:8] + "..." + existing[-4:] if len(existing) > 12 else "***"
                self.c.print(f"  Existing key found: {masked}")
                if Confirm.ask("  Use this key?", default=True):
                    api_key = existing
                else:
                    api_key = Prompt.ask(f"  Enter {provider['name']} API key", password=True)
            else:
                self.c.print(f"  [dim]{provider['key_hint']}[/]")
                api_key = Prompt.ask(f"  Enter {provider['name']} API key", password=True)

            if api_key:
                with Progress(SpinnerColumn(), TextColumn("{task.description}")) as prog:
                    prog.add_task("Validating key...", total=None)
                    valid = await self._validate_key(choice, api_key)

                if valid:
                    self.c.print("  [green]Key is valid![/]")
                    self.creds[provider["env_key"]] = api_key
                    os.environ[provider["env_key"]] = api_key
                else:
                    self.c.print("  [yellow]Could not validate key (might still work). Saving anyway.[/]")
                    self.creds[provider["env_key"]] = api_key
                    os.environ[provider["env_key"]] = api_key

        self.c.print()

    # ── Step 2: Model ───────────────────────────────────────

    async def _step_model(self):
        provider_id = self.config.get("provider", "openai")
        provider = PROVIDERS[provider_id]

        if provider_id == "ollama":
            models = await self._list_ollama_models()
            if models:
                self.c.print(Panel("[bold]Step 2 · Model[/]", style="blue"))
                for i, m in enumerate(models, 1):
                    self.c.print(f"  {i}. {m}")
                model = Prompt.ask("Choose model", default=models[0] if models else "llama3.1")
                self.config["model"] = model
                self.config["local_preset"] = "ollama_vision" if _looks_like_vision_model(model) else "ollama_text"

                vision_models = [m for m in models if _looks_like_vision_model(m)]
                if vision_models and Confirm.ask("Enable Ollama local vision path now?", default=True):
                    vlm_model = Prompt.ask("Vision model", default=vision_models[0])
                    self.config["vlm_provider"] = "ollama"
                    self.config["vlm_model"] = vlm_model
                    self.config["local_preset"] = "ollama_vision"
            else:
                self.c.print("  [dim]No Ollama models found. Pull one: ollama pull llama3.1[/]")
                self.config["model"] = "llama3.1"
                self.config["local_preset"] = "ollama_text"
            self.c.print()
            return

        if not provider["models"]:
            return

        self.c.print(Panel(
            "[bold]Step 2 · Model[/]\n"
            f"[dim]Which {provider['name']} model?[/]",
            style="blue",
        ))

        for i, m in enumerate(provider["models"], 1):
            default_marker = " [green](recommended)[/]" if m == provider["default_model"] else ""
            self.c.print(f"  {i}. {m}{default_marker}")

        model = Prompt.ask(
            "Choose model",
            choices=provider["models"],
            default=provider["default_model"],
        )
        self.config["model"] = model
        self.c.print()

    # ── Step 3: About YOU ──────────────────────────────────

    async def _step_about_you(self):
        self.c.print(Panel(
            "[bold]Step 3 · About You[/]\n"
            "[dim]Tell your agent about yourself so it can be more helpful.\n"
            "This is saved locally in ~/.theora/USER.md — only your agent reads it.[/]",
            style="blue",
        ))

        user_path = THEORA_HOME / "USER.md"
        existing = ""
        if user_path.exists():
            existing = user_path.read_text().strip()
            if existing and existing != _DEFAULT_USER_MD.strip():
                self.c.print(f"  [dim]Existing USER.md found ({len(existing)} chars)[/]")
                if not Confirm.ask("  Overwrite it?", default=False):
                    self.c.print("  [green]Keeping existing USER.md[/]\n")
                    return

        name = Prompt.ask("  Your name", default="")
        location = Prompt.ask("  Where do you live (city/country)", default="")
        occupation = Prompt.ask("  What do you do (job, student, etc)", default="")
        interests = Prompt.ask("  Interests / hobbies (comma-separated)", default="")
        health_goals = Prompt.ask("  Health goals or conditions to track (optional)", default="")
        anything_else = Prompt.ask("  Anything else your agent should know", default="")

        lines = ["# About Me\n"]
        if name:
            lines.append(f"My name is {name}.")
        if location:
            lines.append(f"I live in {location}.")
        if occupation:
            lines.append(f"I work as {occupation}." if "student" not in occupation.lower() else f"I'm a {occupation}.")
        if interests:
            lines.append(f"\n## Interests\n{interests}")
        if health_goals:
            lines.append(f"\n## Health\n{health_goals}")
        if anything_else:
            lines.append(f"\n## Notes\n{anything_else}")

        user_md = "\n".join(lines) + "\n"
        user_path.write_text(user_md)
        self.c.print(f"  [green]Saved to {user_path}[/]")
        self.c.print(f"  [dim]You can edit this file anytime to update your agent's knowledge about you.[/]")
        self.c.print()

    # ── Step 4: Agent Personality ───────────────────────────

    async def _step_personality(self):
        self.c.print(Panel(
            "[bold]Step 4 · Agent Personality[/]\n"
            "[dim]How should your agent behave? This defines its SOUL.md.[/]",
            style="blue",
        ))

        preset_keys = list(PERSONALITY_PRESETS.keys())
        for i, key in enumerate(preset_keys, 1):
            p = PERSONALITY_PRESETS[key]
            self.c.print(f"  {i}. [cyan]{p['label']}[/] — {p['desc']}")

        choice = Prompt.ask(
            "Choose personality",
            choices=preset_keys,
            default="assistant",
        )

        preset = PERSONALITY_PRESETS[choice]

        if choice == "custom":
            self.c.print("  Write your agent's personality (multi-line, press Enter twice to finish):")
            lines = []
            while True:
                line = Prompt.ask("  ", default="")
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            soul_text = "\n".join(lines).strip()
        else:
            soul_text = preset["soul"].strip()
            self.c.print(f"\n  [dim]{soul_text[:120]}...[/]\n")

        agent_name = Prompt.ask("  Agent name", default="THEORA")
        self.config["agent_name"] = agent_name

        # Write SOUL.md
        soul_path = THEORA_HOME / "SOUL.md"
        soul_content = f"# {agent_name}\n\n{soul_text}\n"
        soul_path.write_text(soul_content)
        self.c.print(f"  [green]SOUL.md saved[/]")

        # Write IDENTITY.yaml
        try:
            import yaml
        except ImportError:
            yaml = None

        identity = {
            "name": agent_name,
            "tagline": f"{agent_name} — your personal AI operating system",
            "personality": soul_text,
            "rules": [
                "Never share user data without explicit consent",
                "Explain before taking impactful actions",
                "Be honest about limitations",
                "Keep responses concise unless asked for detail",
                "Respect privacy — everything runs locally unless explicitly told otherwise",
            ],
            "greeting_style": "Brief and contextual. If you have recent data, mention something relevant.",
            "voice": {"tts_voice": "nova", "speed": 1.0},
        }

        identity_path = THEORA_HOME / "IDENTITY.yaml"
        if yaml:
            identity_path.write_text(yaml.dump(identity, default_flow_style=False, allow_unicode=True, sort_keys=False))
        else:
            identity_path.write_text(json.dumps(identity, indent=2))
        self.c.print(f"  [green]IDENTITY.yaml saved[/]")

        # Write MEMORY.md (seed)
        memory_path = THEORA_HOME / "MEMORY.md"
        if not memory_path.exists():
            memory_path.write_text("# Agent Memory\n\nLong-term curated memory. The agent updates this file as it learns.\n")
            self.c.print(f"  [green]MEMORY.md created[/]")

        self.c.print()

    # ── Step 5: Tool API Keys ──────────────────────────────

    async def _step_tool_keys(self):
        self.c.print(Panel(
            "[bold]Step 5 · Tool API Keys (Optional)[/]\n"
            "[dim]These unlock extra capabilities. Skip any you don't need — \n"
            "THEORA works without them (falls back to free alternatives).[/]",
            style="blue",
        ))

        for tk in TOOL_KEYS:
            existing = self.creds.get(tk["env"]) or os.getenv(tk["env"], "")
            if existing:
                self.c.print(f"  [green]{tk['name']}[/]: configured")
                continue

            if Confirm.ask(f"  Add {tk['name']}? ({tk['desc']})", default=False):
                self.c.print(f"    [dim]{tk['hint']}[/]")
                key = Prompt.ask(f"    {tk['name']} API key", password=True)
                if key.strip():
                    self.creds[tk["env"]] = key.strip()
                    self.c.print(f"    [green]Saved[/]")
            else:
                self.c.print(f"    [dim]Skipped[/]")

        self.c.print()

    # ── Save & Finish ──────────────────────────────────────

    def _save_all(self):
        """Persist credentials and config to disk."""
        # Credentials
        creds_path = THEORA_HOME / "credentials.json"
        creds_path.write_text(json.dumps(self.creds, indent=2))
        creds_path.chmod(0o600)

        # Config
        config_path = THEORA_HOME / "config.json"
        config_path.write_text(json.dumps(self.config, indent=2))

        # Settings consumed by ConfigLoader
        settings = {
            "llm": {
                "provider": self.config.get("provider", "openai"),
                "model": self.config.get("model", "gpt-4o-mini"),
            },
            "vision": {
                "enabled": bool(self.config.get("vlm_provider")),
                "provider": self.config.get("vlm_provider", ""),
                "model": self.config.get("vlm_model", ""),
            },
            "meta": {
                "local_preset": self.config.get("local_preset", ""),
            },
        }
        settings_path = THEORA_HOME / "settings.json"
        settings_path.write_text(json.dumps(settings, indent=2))

    def _step_finish(self):
        provider_name = PROVIDERS.get(self.config.get("provider", ""), {}).get("name", "?")
        model = self.config.get("model", "default")
        agent_name = self.config.get("agent_name", "THEORA")

        self.c.print(Panel.fit(
            f"[bold green]Setup Complete![/]\n\n"
            f"  Provider:    {provider_name}\n"
            f"  Model:       {model}\n"
            f"  Agent:       {agent_name}\n"
            f"  Config:      {THEORA_HOME}\n\n"
            f"[bold]Start your agent:[/]\n"
            f"  [cyan]theora start[/]\n\n"
            f"[dim]Files you can edit anytime:[/]\n"
            f"  {THEORA_HOME}/USER.md       — about you\n"
            f"  {THEORA_HOME}/SOUL.md       — agent personality\n"
            f"  {THEORA_HOME}/MEMORY.md     — agent's long-term memory\n"
            f"  {THEORA_HOME}/IDENTITY.yaml — structured identity config",
            border_style="green",
            padding=(1, 2),
        ))

    # ── Helpers ─────────────────────────────────────────────

    async def _validate_key(self, provider: str, key: str) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                if provider == "openai":
                    r = await client.get("https://api.openai.com/v1/models",
                                         headers={"Authorization": f"Bearer {key}"})
                    return r.status_code == 200
                elif provider == "anthropic":
                    r = await client.get("https://api.anthropic.com/v1/models",
                                         headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
                    return r.status_code == 200
                elif provider == "gemini":
                    r = await client.get(f"https://generativelanguage.googleapis.com/v1/models?key={key}")
                    return r.status_code == 200
                elif provider == "groq":
                    r = await client.get("https://api.groq.com/openai/v1/models",
                                         headers={"Authorization": f"Bearer {key}"})
                    return r.status_code == 200
        except Exception:
            pass
        return False

    async def _check_ollama(self):
        try:
            import httpx
            base = ollama_base_url()
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{base}/api/tags")
                if r.status_code == 200:
                    models = [m["name"] for m in r.json().get("models", [])]
                    if models:
                        self.c.print(f"  [green]Ollama running with {len(models)} model(s)[/]")
                    else:
                        self.c.print("  [yellow]Ollama running but no models. Pull one: ollama pull llama3.1[/]")
                    return
        except Exception:
            pass
        self.c.print("  [yellow]Ollama not running. Start it: ollama serve[/]")

    async def _list_ollama_models(self) -> list[str]:
        try:
            import httpx
            base = ollama_base_url()
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{base}/api/tags")
                if r.status_code == 200:
                    return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []


# ── Plain fallback (no rich) ───────────────────────────────

class OnboardWizardPlain:
    """Fallback for when rich is not installed."""

    def __init__(self):
        self.config: dict = {}
        self.creds: dict = {}

    async def run(self):
        THEORA_HOME.mkdir(parents=True, exist_ok=True)

        creds_path = THEORA_HOME / "credentials.json"
        if creds_path.exists():
            try:
                self.creds = json.loads(creds_path.read_text())
            except Exception:
                self.creds = {}

        print()
        print("=" * 50)
        print("  THEORA Setup")
        print("  (install 'rich' for a better experience: pip install rich)")
        print("=" * 50)
        print()

        # Provider
        print("Step 1: LLM Provider")
        print("  1. OpenAI     2. Anthropic    3. Gemini")
        print("  4. Groq       5. Ollama (local)")
        choice_map = {"1": "openai", "2": "anthropic", "3": "gemini", "4": "groq", "5": "ollama"}
        choice = input("  Choose (1-5) [1]: ").strip() or "1"
        provider_id = choice_map.get(choice, "openai")
        provider = PROVIDERS[provider_id]
        self.config["provider"] = provider_id

        if provider["env_key"]:
            existing = self.creds.get(provider["env_key"]) or os.getenv(provider["env_key"], "")
            if existing:
                print(f"  Key found: {existing[:8]}...")
                use = input("  Use this key? (Y/n): ").strip().lower()
                if use not in ("n", "no"):
                    api_key = existing
                else:
                    api_key = input(f"  Enter {provider['name']} API key: ").strip()
            else:
                api_key = input(f"  Enter {provider['name']} API key: ").strip()
            if api_key:
                self.creds[provider["env_key"]] = api_key
                os.environ[provider["env_key"]] = api_key
        print()

        # Model
        if provider["models"]:
            print("Step 2: Model")
            for i, m in enumerate(provider["models"], 1):
                default = " (default)" if m == provider["default_model"] else ""
                print(f"  {i}. {m}{default}")
            model_input = input(f"  Choose [{provider['default_model']}]: ").strip()
            self.config["model"] = model_input if model_input in provider["models"] else provider["default_model"]
        print()

        # About you
        print("Step 3: About You")
        print("  Tell your agent about yourself (saved to ~/.theora/USER.md)")
        name = input("  Your name: ").strip()
        location = input("  City/Country: ").strip()
        occupation = input("  Occupation: ").strip()
        interests = input("  Interests: ").strip()

        lines = ["# About Me\n"]
        if name:
            lines.append(f"My name is {name}.")
        if location:
            lines.append(f"I live in {location}.")
        if occupation:
            lines.append(f"I work as {occupation}.")
        if interests:
            lines.append(f"\n## Interests\n{interests}")
        (THEORA_HOME / "USER.md").write_text("\n".join(lines) + "\n")
        print("  Saved.")
        print()

        # Personality
        print("Step 4: Agent Personality")
        print("  1. Personal Assistant   2. Technical Partner")
        print("  3. Wellness Coach       4. Minimal")
        preset_map = {"1": "assistant", "2": "engineer", "3": "coach", "4": "minimal"}
        p_choice = input("  Choose (1-4) [1]: ").strip() or "1"
        preset_id = preset_map.get(p_choice, "assistant")
        soul = PERSONALITY_PRESETS[preset_id]["soul"]

        agent_name = input("  Agent name [THEORA]: ").strip() or "THEORA"
        self.config["agent_name"] = agent_name

        (THEORA_HOME / "SOUL.md").write_text(f"# {agent_name}\n\n{soul}\n")

        identity = {"name": agent_name, "personality": soul}
        try:
            import yaml
            (THEORA_HOME / "IDENTITY.yaml").write_text(
                yaml.dump(identity, default_flow_style=False, sort_keys=False)
            )
        except ImportError:
            (THEORA_HOME / "IDENTITY.yaml").write_text(json.dumps(identity, indent=2))
        print("  Saved.")
        print()

        # Tool keys
        print("Step 5: Extra API Keys (optional, press Enter to skip)")
        for tk in TOOL_KEYS:
            existing = self.creds.get(tk["env"]) or os.getenv(tk["env"], "")
            if existing:
                print(f"  {tk['name']}: configured")
                continue
            key = input(f"  {tk['name']} ({tk['desc']}): ").strip()
            if key:
                self.creds[tk["env"]] = key
        print()

        # Save
        creds_path = THEORA_HOME / "credentials.json"
        creds_path.write_text(json.dumps(self.creds, indent=2))
        try:
            creds_path.chmod(0o600)
        except Exception:
            pass
        (THEORA_HOME / "config.json").write_text(json.dumps(self.config, indent=2))

        print("=" * 50)
        print(f"  Setup complete!")
        print(f"  Agent: {agent_name}")
        print(f"  Config: {THEORA_HOME}")
        print()
        print("  Start your agent:")
        print("    theora start")
        print("=" * 50)
        print()


_DEFAULT_USER_MD = "# About Me\n\nTell your agent about yourself here.\n"
