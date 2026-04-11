"""
FERAL Interactive Onboarding
==============================
Guided setup that configures everything: LLM provider, identity,
agent personality, tool keys, device pairing, and more.

Steps:
  1. Welcome + FERAL mission
  2. LLM provider + API key (validated)
  3. Model selection
  4. Tell the agent about YOU (USER.md) — expanded identity
  5. Agent personality / SOUL.md
  6. Device pairing (optional)
  7. Tool API keys (search, weather, image gen, GitHub, etc.)
  8. Summary + how to start

All config is saved to ~/.feral/ — no env vars needed.
"""

from __future__ import annotations
import asyncio
import json
import os
import socket
import textwrap

from config.loader import feral_home
from config.runtime import ollama_base_url

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

FERAL_HOME = feral_home()

# ═══════════════════════════════════════════════════════════
# LLM Providers — updated April 2026
# ═══════════════════════════════════════════════════════════

PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "base_url": "",
        "desc": "GPT-4.1, GPT-4o, o3-mini, realtime voice, DALL-E",
        "models": ["gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o", "gpt-4o-mini", "o3-mini"],
        "default_model": "gpt-4.1",
        "voice": True,
        "key_hint": "Starts with sk-...",
    },
    "anthropic": {
        "name": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "base_url": "",
        "desc": "Claude Sonnet 4, Claude Opus, strong reasoning",
        "models": ["claude-sonnet-4-20250514", "claude-3.5-sonnet-20241022", "claude-3-opus-20240229"],
        "default_model": "claude-sonnet-4-20250514",
        "voice": False,
        "key_hint": "Starts with sk-ant-...",
    },
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GOOGLE_API_KEY",
        "base_url": "",
        "desc": "Gemini 2.5 Flash/Pro, realtime voice, multimodal",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "default_model": "gemini-2.5-flash",
        "voice": True,
        "key_hint": "From Google AI Studio",
    },
    "openrouter": {
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "desc": "Gateway to 300+ models (OpenAI, Claude, Gemini, DeepSeek, Llama)",
        "models": [
            "openai/gpt-4.1",
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "default_model": "openai/gpt-4.1",
        "voice": False,
        "key_hint": "From openrouter.ai/keys",
    },
    "deepseek": {
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "desc": "DeepSeek V3 / R1, strong reasoning, low cost",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "voice": False,
        "key_hint": "From platform.deepseek.com",
    },
    "kimi": {
        "name": "Kimi (Moonshot)",
        "env_key": "MOONSHOT_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "desc": "Moonshot v1, 128K context, strong Chinese + English",
        "models": ["moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"],
        "default_model": "moonshot-v1-128k",
        "voice": False,
        "key_hint": "From platform.moonshot.cn",
    },
    "qwen": {
        "name": "Qwen (Alibaba)",
        "env_key": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "desc": "Qwen Max/Plus/Turbo, strong multilingual",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo"],
        "default_model": "qwen-max",
        "voice": False,
        "key_hint": "From dashscope.console.aliyun.com",
    },
    "groq": {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "desc": "Ultra-fast inference, Llama 3.3 / DeepSeek / Mixtral",
        "models": ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b", "mixtral-8x7b-32768"],
        "default_model": "llama-3.3-70b-versatile",
        "voice": False,
        "key_hint": "From console.groq.com",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "env_key": "",
        "base_url": "",
        "desc": "Free, private, runs on your machine — no API key needed",
        "models": [],
        "default_model": "",
        "voice": False,
        "key_hint": "No key needed — just install Ollama",
    },
}

# ═══════════════════════════════════════════════════════════
# Tool API Keys
# ═══════════════════════════════════════════════════════════

TOOL_KEYS = [
    {
        "env": "EXA_API_KEY",
        "name": "EXA Search",
        "desc": "Neural search (best quality, understands meaning)",
        "hint": "From exa.ai/dashboard — free tier available",
        "optional": True,
    },
    {
        "env": "TAVILY_API_KEY",
        "name": "Tavily",
        "desc": "Web search (fast, structured results)",
        "hint": "From tavily.com — free tier available",
        "optional": True,
    },
    {
        "env": "SERPER_API_KEY",
        "name": "Serper",
        "desc": "Google search results API",
        "hint": "From serper.dev — 2500 free queries",
        "optional": True,
    },
    {
        "env": "BRAVE_API_KEY",
        "name": "Brave Search",
        "desc": "Web search (privacy-focused alternative)",
        "hint": "From brave.com/search/api",
        "optional": True,
    },
    {
        "env": "OPENWEATHER_API_KEY",
        "name": "OpenWeatherMap",
        "desc": "Weather data and forecasts",
        "hint": "From openweathermap.org — free tier",
        "optional": True,
    },
    {
        "env": "GITHUB_TOKEN",
        "name": "GitHub",
        "desc": "Repo operations, issues, PRs",
        "hint": "From github.com/settings/tokens (classic or fine-grained)",
        "optional": True,
    },
    {
        "env": "SPOTIFY_CLIENT_ID",
        "name": "Spotify",
        "desc": "Music playback and playlist control",
        "hint": "From developer.spotify.com — also needs SPOTIFY_CLIENT_SECRET",
        "optional": True,
        "extra_keys": ["SPOTIFY_CLIENT_SECRET"],
    },
    {
        "env": "GOOGLE_CALENDAR_CREDENTIALS",
        "name": "Google Calendar",
        "desc": "Scheduling, event management",
        "hint": "From console.cloud.google.com — OAuth JSON path",
        "optional": True,
    },
]

# ═══════════════════════════════════════════════════════════
# Personality Presets
# ═══════════════════════════════════════════════════════════

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


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "YOUR_IP"


def run_setup():
    """Entry point — called by `feral setup` or the install script."""
    if HAS_RICH:
        wizard = OnboardWizard(Console())
    else:
        wizard = OnboardWizardPlain()
    try:
        asyncio.run(wizard.run())
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled. Run `feral setup` anytime to continue.\n")


# ═══════════════════════════════════════════════════════════
# Rich-powered wizard
# ═══════════════════════════════════════════════════════════

class OnboardWizard:

    def __init__(self, console: Console):
        self.c = console
        self.config: dict = {}
        self.creds: dict = {}

    async def run(self):
        FERAL_HOME.mkdir(parents=True, exist_ok=True)
        self._load_existing_creds()

        self._step_welcome()
        await self._step_provider()
        await self._step_model()
        await self._step_about_you()
        await self._step_personality()
        await self._step_device_pairing()
        await self._step_tool_keys()
        self._save_all()
        self._step_finish()

    def _load_existing_creds(self):
        creds_path = FERAL_HOME / "credentials.json"
        if creds_path.exists():
            try:
                self.creds = json.loads(creds_path.read_text())
            except Exception:
                self.creds = {}

    # ── Welcome + Mission ─────────────────────────────────

    def _step_welcome(self):
        self.c.print()
        self.c.print(Panel.fit(
            "[bold cyan]Welcome to FERAL[/]\n"
            "[bold]The Open AI Operating System[/]\n\n"
            "[dim]FERAL is not just another computer-use agent.[/]\n\n"
            "Unlike tools like OpenClaw that only control your screen,\n"
            "FERAL is a [bold]full platform[/]:\n\n"
            "  [cyan]•[/] Learns new skills on the fly — the agent teaches itself\n"
            "  [cyan]•[/] Controls hardware — glasses, robots, sensors, home devices\n"
            "  [cyan]•[/] Generates dynamic UI — no hardcoded apps, just data\n"
            "  [cyan]•[/] Privacy-first memory — your data stays on YOUR machine\n"
            "  [cyan]•[/] Multi-device — phone as bridge to glasses, wristbands, robots\n\n"
            "[dim]Built for AI developers to extend: add skills, hardware daemons,\n"
            "GenUI providers, and more. Our vision is a native AI OS built on NixOS\n"
            "that runs on PCs, phones, and embedded devices.[/]\n\n"
            "[bold green]This wizard sets everything up in about 3 minutes.[/]",
            border_style="cyan",
            padding=(1, 2),
        ))
        self.c.print()

    # ── Step 1: Provider ────────────────────────────────────

    async def _step_provider(self):
        self.c.print(Panel(
            "[bold]Step 1 · LLM Provider[/]\n"
            "[dim]Which AI model provider do you want to use?[/]",
            style="blue",
        ))

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Provider", style="cyan", width=20)
        table.add_column("Description", width=50)
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

        if provider.get("base_url"):
            self.config["base_url"] = provider["base_url"]

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

    # ── Step 3: About YOU (expanded) ──────────────────────

    async def _step_about_you(self):
        self.c.print(Panel(
            "[bold]Step 3 · About You[/]\n"
            "[dim]Tell your agent about yourself so it can be more helpful.\n"
            "This is saved locally in ~/.feral/USER.md — only your agent reads it.[/]",
            style="blue",
        ))

        user_path = FERAL_HOME / "USER.md"
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
        language = Prompt.ask("  Preferred language", default="English")
        occupation = Prompt.ask("  What do you do (job, student, etc)", default="")
        interests = Prompt.ask("  Interests / hobbies (comma-separated)", default="")

        self.c.print()
        self.c.print("  [dim]These help your agent match your style:[/]")
        tech_levels = ["beginner", "intermediate", "advanced", "developer"]
        tech_level = Prompt.ask(
            "  Tech skill level",
            choices=tech_levels,
            default="intermediate",
        )

        use_cases = ["personal-assistant", "developer-tool", "health-monitoring", "home-automation", "research", "other"]
        use_case = Prompt.ask(
            "  Primary use case",
            choices=use_cases,
            default="personal-assistant",
        )

        comm_styles = ["detailed", "concise", "casual", "formal"]
        comm_style = Prompt.ask(
            "  Communication preference",
            choices=comm_styles,
            default="concise",
        )

        # Optional FERAL community section
        self.c.print()
        is_feral = Confirm.ask("  Are you part of the FERAL ecosystem? (glasses/wristband)", default=False)
        health_goals = ""
        glasses_model = ""
        wristband = False
        if is_feral:
            health_goals = Prompt.ask("  Health goals or conditions to track", default="")
            glasses_model = Prompt.ask("  FERAL glasses model (W300/W610/other/none)", default="none")
            wristband = Confirm.ask("  FERAL wristband connected?", default=False)

        anything_else = Prompt.ask("  Anything else your agent should know", default="")

        lines = ["# About Me\n"]
        if name:
            lines.append(f"My name is {name}.")
        if location:
            lines.append(f"I live in {location}.")
        if language and language.lower() != "english":
            lines.append(f"I prefer to communicate in {language}.")
        if occupation:
            lines.append(f"I work as {occupation}." if "student" not in occupation.lower() else f"I'm a {occupation}.")

        lines.append("\n## Preferences")
        lines.append(f"- Tech level: {tech_level}")
        lines.append(f"- Primary use: {use_case}")
        lines.append(f"- Communication style: {comm_style}")

        if interests:
            lines.append(f"\n## Interests\n{interests}")

        if is_feral:
            lines.append("\n## FERAL Ecosystem")
            if health_goals:
                lines.append(f"- Health goals: {health_goals}")
            if glasses_model and glasses_model.lower() != "none":
                lines.append(f"- Glasses model: {glasses_model}")
            if wristband:
                lines.append("- Wristband: connected")

        if anything_else:
            lines.append(f"\n## Notes\n{anything_else}")

        user_md = "\n".join(lines) + "\n"
        user_path.write_text(user_md)
        self.c.print(f"  [green]Saved to {user_path}[/]")
        self.c.print("  [dim]You can edit this file anytime to update your agent's knowledge about you.[/]")
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

        agent_name = Prompt.ask("  Agent name", default="FERAL")
        self.config["agent_name"] = agent_name

        soul_path = FERAL_HOME / "SOUL.md"
        soul_content = f"# {agent_name}\n\n{soul_text}\n"
        soul_path.write_text(soul_content)
        self.c.print("  [green]SOUL.md saved[/]")

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

        identity_path = FERAL_HOME / "IDENTITY.yaml"
        if yaml:
            identity_path.write_text(yaml.dump(identity, default_flow_style=False, allow_unicode=True, sort_keys=False))
        else:
            identity_path.write_text(json.dumps(identity, indent=2))
        self.c.print("  [green]IDENTITY.yaml saved[/]")

        memory_path = FERAL_HOME / "MEMORY.md"
        if not memory_path.exists():
            memory_path.write_text("# Agent Memory\n\nLong-term curated memory. The agent updates this file as it learns.\n")
            self.c.print("  [green]MEMORY.md created[/]")

        self.config["multi_agent"] = Confirm.ask(
            "  Enable Multi-Agent mode (subagents + parallel workers)?",
            default=True,
        )
        mode_label = "enabled" if self.config["multi_agent"] else "disabled"
        self.c.print(f"  [green]Multi-Agent {mode_label}[/]")
        self.c.print()

    # ── Step 5: Device Pairing ─────────────────────────────

    async def _step_device_pairing(self):
        self.c.print(Panel(
            "[bold]Step 5 · Connect Your Devices (Optional)[/]\n"
            "[dim]FERAL can connect to your phone, glasses, wristband, and more.\n"
            "Your phone acts as a bridge between wearables and this computer.[/]",
            style="blue",
        ))

        self.c.print(
            "  [bold]How it works:[/]\n"
            "  ┌─────────────┐     ┌───────────┐     ┌────────────┐     ┌──────────┐\n"
            "  │  Glasses /  │────▶│   Phone   │────▶│   Brain    │────▶│  Actions │\n"
            "  │  Wristband  │     │  (Bridge) │     │ (This Mac) │     │ (Robot,  │\n"
            "  │  Sensors    │     │           │     │            │     │  Apps..) │\n"
            "  └─────────────┘     └───────────┘     └────────────┘     └──────────┘\n"
        )

        local_ip = _get_local_ip()
        self.c.print(f"  [dim]Your local IP: {local_ip}[/]")
        self.c.print(f"  [dim]Daemon WebSocket: ws://{local_ip}:9090/v1/daemon[/]")
        self.c.print()

        pair_phone = Confirm.ask("  Pair a phone as a bridge now?", default=False)
        if pair_phone:
            phone_url = Prompt.ask(
                "  Phone bridge URL (or press Enter to use auto-discovery)",
                default="",
            )
            if phone_url:
                self.config["phone_bridge_url"] = phone_url
                self.c.print("  [green]Phone bridge URL saved[/]")
            else:
                self.c.print("  [dim]Auto-discovery will find your phone when you start FERAL.[/]")
                self.config["phone_bridge_url"] = "auto"

        register_glasses = Confirm.ask("  Register FERAL glasses?", default=False)
        if register_glasses:
            model = Prompt.ask("  Glasses model (W300/W610/other)", default="W610")
            self.config["glasses_model"] = model
            self.c.print(f"  [green]Registered: {model}[/]")

        if not pair_phone and not register_glasses:
            self.c.print("  [dim]Skipped. You can pair devices later: feral devices pair[/]")

        self.c.print()

    # ── Step 6: Tool API Keys ──────────────────────────────

    async def _step_tool_keys(self):
        self.c.print(Panel(
            "[bold]Step 6 · Tool API Keys (Optional)[/]\n"
            "[dim]These unlock extra capabilities. Skip any you don't need — \n"
            "FERAL works without them (falls back to free alternatives).\n"
            "Your LLM key (if OpenAI) already enables DALL-E image generation.[/]",
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
                    if "extra_keys" in tk:
                        for ek in tk["extra_keys"]:
                            extra_val = Prompt.ask(f"    {ek}", password=True)
                            if extra_val.strip():
                                self.creds[ek] = extra_val.strip()
                    self.c.print("    [green]Saved[/]")
            else:
                self.c.print("    [dim]Skipped[/]")

        self.c.print()

    # ── Save & Finish ──────────────────────────────────────

    def _save_all(self):
        creds_path = FERAL_HOME / "credentials.json"
        creds_path.write_text(json.dumps(self.creds, indent=2))
        creds_path.chmod(0o600)

        config_path = FERAL_HOME / "config.json"
        config_path.write_text(json.dumps(self.config, indent=2))

        provider_id = self.config.get("provider", "openai")
        provider_info = PROVIDERS.get(provider_id, {})

        settings = {
            "llm": {
                "provider": provider_id,
                "model": self.config.get("model", "gpt-4o-mini"),
                "base_url": self.config.get("base_url", provider_info.get("base_url", "")),
            },
            "vision": {
                "enabled": bool(self.config.get("vlm_provider")),
                "provider": self.config.get("vlm_provider", ""),
                "model": self.config.get("vlm_model", ""),
            },
            "devices": {
                "phone_bridge_url": self.config.get("phone_bridge_url", ""),
                "glasses_model": self.config.get("glasses_model", ""),
            },
            "features": {
                "multi_agent": bool(self.config.get("multi_agent", True)),
            },
            "meta": {
                "local_preset": self.config.get("local_preset", ""),
                "setup_complete": True,
            },
        }
        settings_path = FERAL_HOME / "settings.json"
        settings_path.write_text(json.dumps(settings, indent=2))

    def _step_finish(self):
        provider_name = PROVIDERS.get(self.config.get("provider", ""), {}).get("name", "?")
        model = self.config.get("model", "default")
        agent_name = self.config.get("agent_name", "FERAL")

        self.c.print(Panel.fit(
            f"[bold green]Setup Complete![/]\n\n"
            f"  Provider:    {provider_name}\n"
            f"  Model:       {model}\n"
            f"  Agent:       {agent_name}\n"
            f"  Config:      {FERAL_HOME}\n\n"
            f"[bold]Start your agent:[/]\n"
            f"  [cyan]feral start[/]\n\n"
            f"[dim]Files you can edit anytime:[/]\n"
            f"  {FERAL_HOME}/USER.md       — about you\n"
            f"  {FERAL_HOME}/SOUL.md       — agent personality\n"
            f"  {FERAL_HOME}/MEMORY.md     — agent's long-term memory\n"
            f"  {FERAL_HOME}/IDENTITY.yaml — structured identity config",
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
                elif provider == "openrouter":
                    r = await client.get("https://openrouter.ai/api/v1/models",
                                         headers={"Authorization": f"Bearer {key}"})
                    return r.status_code == 200
                elif provider == "deepseek":
                    r = await client.get("https://api.deepseek.com/models",
                                         headers={"Authorization": f"Bearer {key}"})
                    return r.status_code == 200
                elif provider == "kimi":
                    r = await client.get("https://api.moonshot.cn/v1/models",
                                         headers={"Authorization": f"Bearer {key}"})
                    return r.status_code == 200
                elif provider == "qwen":
                    r = await client.get(
                        "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
                        headers={"Authorization": f"Bearer {key}"},
                    )
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


# ═══════════════════════════════════════════════════════════
# Plain fallback (no rich)
# ═══════════════════════════════════════════════════════════

class OnboardWizardPlain:

    def __init__(self):
        self.config: dict = {}
        self.creds: dict = {}

    async def run(self):
        FERAL_HOME.mkdir(parents=True, exist_ok=True)

        creds_path = FERAL_HOME / "credentials.json"
        if creds_path.exists():
            try:
                self.creds = json.loads(creds_path.read_text())
            except Exception:
                self.creds = {}

        print()
        print("=" * 60)
        print("  FERAL — The Open AI Operating System")
        print()
        print("  Not just another computer-use agent. FERAL is a full")
        print("  platform: learns skills, controls hardware, generates UI,")
        print("  privacy-first memory. Built for AI devs to extend.")
        print()
        print("  (install 'rich' for a better experience: pip install rich)")
        print("=" * 60)
        print()

        # Provider
        print("Step 1: LLM Provider")
        provider_keys = list(PROVIDERS.keys())
        for i, pid in enumerate(provider_keys, 1):
            p = PROVIDERS[pid]
            print(f"  {i}. {p['name']:20s} {p['desc']}")
        choice_idx = input(f"  Choose (1-{len(provider_keys)}) [1]: ").strip() or "1"
        try:
            provider_id = provider_keys[int(choice_idx) - 1]
        except (ValueError, IndexError):
            provider_id = "openai"
        provider = PROVIDERS[provider_id]
        self.config["provider"] = provider_id

        if provider.get("base_url"):
            self.config["base_url"] = provider["base_url"]

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

        # About you (expanded)
        print("Step 3: About You")
        print("  Tell your agent about yourself (saved to ~/.feral/USER.md)")
        name = input("  Your name: ").strip()
        location = input("  City/Country: ").strip()
        language = input("  Preferred language [English]: ").strip() or "English"
        occupation = input("  Occupation: ").strip()
        interests = input("  Interests: ").strip()
        print("  Tech level: 1. beginner  2. intermediate  3. advanced  4. developer")
        tech_idx = input("  Choose [2]: ").strip() or "2"
        tech_map = {"1": "beginner", "2": "intermediate", "3": "advanced", "4": "developer"}
        tech_level = tech_map.get(tech_idx, "intermediate")
        print("  Use case: 1. personal-assistant  2. developer-tool  3. health-monitoring")
        print("            4. home-automation  5. research  6. other")
        use_idx = input("  Choose [1]: ").strip() or "1"
        use_map = {"1": "personal-assistant", "2": "developer-tool", "3": "health-monitoring",
                   "4": "home-automation", "5": "research", "6": "other"}
        use_case = use_map.get(use_idx, "personal-assistant")
        print("  Communication: 1. detailed  2. concise  3. casual  4. formal")
        comm_idx = input("  Choose [2]: ").strip() or "2"
        comm_map = {"1": "detailed", "2": "concise", "3": "casual", "4": "formal"}
        comm_style = comm_map.get(comm_idx, "concise")

        feral_member = input("  Part of FERAL ecosystem (glasses/wristband)? (y/N): ").strip().lower()
        health_goals = ""
        glasses_model = ""
        if feral_member in ("y", "yes"):
            health_goals = input("  Health goals: ").strip()
            glasses_model = input("  Glasses model (W300/W610/other/none): ").strip()

        lines = ["# About Me\n"]
        if name:
            lines.append(f"My name is {name}.")
        if location:
            lines.append(f"I live in {location}.")
        if language.lower() != "english":
            lines.append(f"I prefer to communicate in {language}.")
        if occupation:
            lines.append(f"I work as {occupation}.")
        lines.append("\n## Preferences")
        lines.append(f"- Tech level: {tech_level}")
        lines.append(f"- Primary use: {use_case}")
        lines.append(f"- Communication style: {comm_style}")
        if interests:
            lines.append(f"\n## Interests\n{interests}")
        if feral_member in ("y", "yes"):
            lines.append("\n## FERAL Ecosystem")
            if health_goals:
                lines.append(f"- Health goals: {health_goals}")
            if glasses_model and glasses_model.lower() != "none":
                lines.append(f"- Glasses model: {glasses_model}")
        (FERAL_HOME / "USER.md").write_text("\n".join(lines) + "\n")
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

        agent_name = input("  Agent name [FERAL]: ").strip() or "FERAL"
        self.config["agent_name"] = agent_name

        (FERAL_HOME / "SOUL.md").write_text(f"# {agent_name}\n\n{soul}\n")

        identity = {"name": agent_name, "personality": soul}
        try:
            import yaml
            (FERAL_HOME / "IDENTITY.yaml").write_text(
                yaml.dump(identity, default_flow_style=False, sort_keys=False)
            )
        except ImportError:
            (FERAL_HOME / "IDENTITY.yaml").write_text(json.dumps(identity, indent=2))
        multi_agent_choice = input("  Enable Multi-Agent mode? (Y/n): ").strip().lower()
        self.config["multi_agent"] = multi_agent_choice not in ("n", "no")
        print("  Saved.")
        print()

        # Device pairing
        print("Step 5: Device Pairing (optional)")
        print("  Architecture: Glasses/Sensors -> Phone (Bridge) -> Brain (This PC) -> Actions")
        local_ip = _get_local_ip()
        print(f"  Your local IP: {local_ip}")
        print(f"  Daemon WebSocket: ws://{local_ip}:9090/v1/daemon")
        pair = input("  Pair a phone bridge now? (y/N): ").strip().lower()
        if pair in ("y", "yes"):
            url = input("  Phone bridge URL (Enter for auto-discovery): ").strip()
            self.config["phone_bridge_url"] = url or "auto"
        glasses = input("  Register FERAL glasses? (y/N): ").strip().lower()
        if glasses in ("y", "yes"):
            model = input("  Glasses model (W300/W610/other) [W610]: ").strip() or "W610"
            self.config["glasses_model"] = model
        print()

        # Tool keys
        print("Step 6: Extra API Keys (optional, press Enter to skip)")
        for tk in TOOL_KEYS:
            existing = self.creds.get(tk["env"]) or os.getenv(tk["env"], "")
            if existing:
                print(f"  {tk['name']}: configured")
                continue
            key = input(f"  {tk['name']} ({tk['desc']}): ").strip()
            if key:
                self.creds[tk["env"]] = key
                if "extra_keys" in tk:
                    for ek in tk["extra_keys"]:
                        extra_val = input(f"  {ek}: ").strip()
                        if extra_val:
                            self.creds[ek] = extra_val
        print()

        # Save
        creds_path = FERAL_HOME / "credentials.json"
        creds_path.write_text(json.dumps(self.creds, indent=2))
        try:
            creds_path.chmod(0o600)
        except Exception:
            pass
        (FERAL_HOME / "config.json").write_text(json.dumps(self.config, indent=2))

        provider_info = PROVIDERS.get(self.config.get("provider", "openai"), {})
        settings = {
            "llm": {
                "provider": self.config.get("provider", "openai"),
                "model": self.config.get("model", "gpt-4o-mini"),
                "base_url": self.config.get("base_url", provider_info.get("base_url", "")),
            },
            "devices": {
                "phone_bridge_url": self.config.get("phone_bridge_url", ""),
                "glasses_model": self.config.get("glasses_model", ""),
            },
            "features": {
                "multi_agent": bool(self.config.get("multi_agent", True)),
            },
            "meta": {
                "setup_complete": True,
            },
        }
        (FERAL_HOME / "settings.json").write_text(json.dumps(settings, indent=2))

        print("=" * 60)
        print("  Setup complete!")
        print(f"  Agent: {agent_name}")
        print(f"  Config: {FERAL_HOME}")
        print()
        print("  Start your agent:")
        print("    feral start")
        print("=" * 60)
        print()


_DEFAULT_USER_MD = "# About Me\n\nTell your agent about yourself here.\n"
