"""
THEORA Interactive Setup Wizard
================================
Step-by-step guided onboarding:
1. Provider selection + API key validation
2. Identity creation (name, personality, SOUL.md)
3. Memory initialization
4. Hardware pairing / device scan
5. First conversation test
6. Channel configuration (optional)

Uses rich library for beautiful terminal UI.
"""

from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.markdown import Markdown
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

THEORA_HOME = Path(os.environ.get("THEORA_HOME", str(Path.home() / ".theora")))

PROVIDER_CONFIGS = {
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "validate_url": "https://api.openai.com/v1/models",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "supports_realtime": True,
    },
    "anthropic": {
        "name": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "validate_url": "https://api.anthropic.com/v1/models",
        "models": ["claude-sonnet-4-20250514", "claude-3.5-sonnet-20241022"],
        "supports_realtime": False,
    },
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "validate_url": "https://generativelanguage.googleapis.com/v1/models",
        "models": ["gemini-2.0-flash-exp", "gemini-1.5-pro"],
        "supports_realtime": True,
    },
    "ollama": {
        "name": "Ollama (Local)",
        "env_key": "",
        "validate_url": "http://localhost:11434/api/tags",
        "models": [],
        "supports_realtime": False,
    },
}

PERSONALITY_ARCHETYPES = {
    "professional": "Formal, precise, and efficient. Minimal small talk.",
    "friendly": "Warm, conversational, and encouraging. Uses natural language.",
    "minimal": "Extremely concise. Short answers. No filler.",
    "creative": "Playful, curious, and imaginative. Thinks outside the box.",
    "custom": "Write your own personality description.",
}


def run_setup():
    """Entry point for the setup wizard."""
    if HAS_RICH:
        console = Console()
        wizard = SetupWizard(console)
    else:
        wizard = SetupWizardBasic()
    asyncio.get_event_loop().run_until_complete(wizard.run())


class SetupWizard:
    """Rich terminal UI setup wizard."""

    def __init__(self, console: Console):
        self.c = console
        self.config = {}

    async def run(self):
        self.c.print(Panel.fit(
            "[bold cyan]THEORA Setup Wizard[/]\n"
            "[dim]Let's set up your personal AI operating system.[/]",
            border_style="cyan",
        ))
        self.c.print()

        THEORA_HOME.mkdir(parents=True, exist_ok=True)

        await self._step_provider()
        await self._step_identity()
        await self._step_memory()
        await self._step_hardware()
        await self._step_test()
        await self._step_channels()
        await self._step_finish()

    async def _step_provider(self):
        self.c.print(Panel("[bold]Step 1/6: LLM Provider[/]", style="blue"))

        table = Table(show_header=True)
        table.add_column("Provider", style="cyan")
        table.add_column("Status")
        table.add_column("Features")

        for pid, pinfo in PROVIDER_CONFIGS.items():
            env_key = pinfo["env_key"]
            has_key = bool(os.getenv(env_key)) if env_key else False
            status = "[green]Key found[/]" if has_key else "[yellow]Not configured[/]"
            if pid == "ollama":
                status = "[dim]Local — no key needed[/]"
            features = "Voice" if pinfo["supports_realtime"] else "Text only"
            table.add_row(pinfo["name"], status, features)

        self.c.print(table)

        choice = Prompt.ask(
            "Choose provider",
            choices=list(PROVIDER_CONFIGS.keys()),
            default="openai",
        )

        provider = PROVIDER_CONFIGS[choice]
        self.config["provider"] = choice

        if choice == "ollama":
            valid = await self._validate_ollama()
            if not valid:
                self.c.print("[yellow]Ollama not running. Start it with: ollama serve[/]")
            else:
                self.c.print("[green]Ollama is running![/]")
        elif provider["env_key"]:
            existing = os.getenv(provider["env_key"], "")
            if existing:
                self.c.print(f"[green]Using existing {provider['env_key']}[/]")
                api_key = existing
            else:
                api_key = Prompt.ask(f"Enter your {provider['name']} API key", password=True)
                os.environ[provider["env_key"]] = api_key

            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                task = progress.add_task("Validating API key...", total=None)
                valid = await self._validate_key(choice, api_key)
                progress.remove_task(task)

            if valid:
                self.c.print("[green]API key validated successfully![/]")
                self._save_credential(provider["env_key"], api_key)
            else:
                self.c.print("[red]API key validation failed. You can fix this later.[/]")

        self.c.print()

    async def _step_identity(self):
        self.c.print(Panel("[bold]Step 2/6: Agent Identity[/]", style="blue"))

        name = Prompt.ask("Name your agent", default="THEORA")
        self.config["name"] = name

        self.c.print("\nPersonality archetypes:")
        for key, desc in PERSONALITY_ARCHETYPES.items():
            self.c.print(f"  [cyan]{key}[/]: {desc}")

        archetype = Prompt.ask(
            "Choose personality",
            choices=list(PERSONALITY_ARCHETYPES.keys()),
            default="friendly",
        )

        if archetype == "custom":
            personality = Prompt.ask("Describe the personality")
        else:
            personality = PERSONALITY_ARCHETYPES[archetype]

        self.config["personality"] = personality

        try:
            import yaml
            identity_path = THEORA_HOME / "IDENTITY.yaml"
            identity = {
                "name": name,
                "tagline": f"Your personal AI assistant — {name}",
                "personality": personality,
                "rules": [
                    "Never share user data without explicit consent",
                    "Explain before taking impactful actions",
                    "Be honest about limitations",
                ],
                "greeting_style": "Direct and warm.",
                "voice": {"tts_voice": "nova"},
            }
            identity_path.write_text(yaml.dump(identity, default_flow_style=False, allow_unicode=True))
            self.c.print(f"[green]Identity saved to {identity_path}[/]")
        except Exception as e:
            self.c.print(f"[yellow]Could not save identity: {e}[/]")

        soul_path = THEORA_HOME / "SOUL.md"
        if not soul_path.exists():
            soul_path.write_text(f"# {name}'s Soul\n\n{personality}\n")
            self.c.print(f"[green]Soul file created at {soul_path}[/]")

        self.c.print()

    async def _step_memory(self):
        self.c.print(Panel("[bold]Step 3/6: Memory Initialization[/]", style="blue"))

        memory_path = THEORA_HOME / "memory.db"
        if memory_path.exists():
            size_mb = memory_path.stat().st_size / (1024 * 1024)
            self.c.print(f"Existing memory database found ({size_mb:.1f} MB)")
            if Confirm.ask("Keep existing memories?", default=True):
                self.c.print("[green]Keeping existing memory.[/]")
            else:
                memory_path.unlink()
                self.c.print("[yellow]Memory cleared — starting fresh.[/]")
        else:
            self.c.print("No existing memory found. A fresh database will be created on first run.")

        memory_md = THEORA_HOME / "MEMORY.md"
        if not memory_md.exists():
            memory_md.write_text("# Agent Memory\n\nLong-term curated memory.\n")
        self.c.print("[green]Memory system ready.[/]")
        self.c.print()

    async def _step_hardware(self):
        self.c.print(Panel("[bold]Step 4/6: Hardware Devices[/]", style="blue"))
        self.c.print("THEORA can connect to phones, wristbands, smart glasses, and more via HUP.")
        self.c.print()

        self.c.print("Checking for devices...")
        has_ble = await self._check_ble()

        if has_ble:
            self.c.print("[green]Bluetooth available.[/]")
            if Confirm.ask("Scan for BLE devices?", default=False):
                self.c.print("[dim]BLE scanning would happen here. Connect your phone app for best results.[/]")
        else:
            self.c.print("[dim]No Bluetooth adapter detected (normal on servers).[/]")

        self.c.print("\nTo connect your phone:")
        self.c.print("  1. Install the THEORA app on your iPhone/Android")
        self.c.print("  2. Open the app and enter your Brain's address")
        self.c.print(f"  3. Your Brain will be at: ws://YOUR_IP:9090/v1/node")
        self.c.print()

    async def _step_test(self):
        self.c.print(Panel("[bold]Step 5/6: First Conversation Test[/]", style="blue"))

        if not Confirm.ask("Run a test conversation?", default=True):
            self.c.print("[dim]Skipping test.[/]")
            self.c.print()
            return

        self.c.print("Testing connection to Brain...")

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://localhost:9090/health", timeout=5.0)
                if resp.status_code == 200:
                    self.c.print("[green]Brain is running![/]")
                    info = await client.get(f"http://localhost:9090/api/info", timeout=5.0)
                    data = info.json()
                    self.c.print(f"  Skills: {data.get('skills', 0)}")
                    self.c.print(f"  Memory: {data.get('memory', {})}")
                    self.c.print(f"  Realtime voice: {data.get('realtime_available', False)}")
                else:
                    self.c.print("[yellow]Brain returned non-200. Start it with: theora start[/]")
        except Exception:
            self.c.print("[yellow]Brain not running. Start it first with: theora start[/]")

        self.c.print()

    async def _step_channels(self):
        self.c.print(Panel("[bold]Step 6/6: Channels (Optional)[/]", style="blue"))
        self.c.print("You can connect THEORA to messaging platforms.")

        if Confirm.ask("Configure Telegram bot?", default=False):
            token = Prompt.ask("Enter Telegram bot token", password=True)
            self._save_credential("TELEGRAM_BOT_TOKEN", token)
            self.c.print("[green]Telegram token saved.[/]")

        if Confirm.ask("Configure Discord bot?", default=False):
            token = Prompt.ask("Enter Discord bot token", password=True)
            self._save_credential("DISCORD_BOT_TOKEN", token)
            self.c.print("[green]Discord token saved.[/]")

        self.c.print()

    async def _step_finish(self):
        self.c.print(Panel.fit(
            "[bold green]Setup Complete![/]\n\n"
            "Start your agent:\n"
            "  [cyan]theora start[/]    — Start the Brain server\n"
            "  [cyan]theora[/]          — Interactive chat\n"
            "  [cyan]theora status[/]   — Check system health\n\n"
            f"Config: {THEORA_HOME}\n"
            f"Provider: {self.config.get('provider', 'not set')}\n"
            f"Agent: {self.config.get('name', 'THEORA')}",
            border_style="green",
        ))

    async def _validate_key(self, provider: str, api_key: str) -> bool:
        try:
            import httpx
            if provider == "openai":
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=10.0,
                    )
                    return resp.status_code == 200
            elif provider == "anthropic":
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                        timeout=10.0,
                    )
                    return resp.status_code == 200
            elif provider == "gemini":
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                        timeout=10.0,
                    )
                    return resp.status_code == 200
        except Exception:
            return False
        return False

    async def _validate_ollama(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:11434/api/tags", timeout=3.0)
                return resp.status_code == 200
        except Exception:
            return False

    async def _check_ble(self) -> bool:
        try:
            import subprocess
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["system_profiler", "SPBluetoothDataType"],
                    capture_output=True, text=True, timeout=5,
                )
                return "Bluetooth" in result.stdout
        except Exception:
            pass
        return False

    def _save_credential(self, key: str, value: str):
        creds_path = THEORA_HOME / "credentials.json"
        creds = {}
        if creds_path.exists():
            try:
                creds = json.loads(creds_path.read_text())
            except Exception:
                pass
        creds[key] = value
        creds_path.write_text(json.dumps(creds, indent=2))


class SetupWizardBasic:
    """Fallback setup wizard when rich is not installed."""

    async def run(self):
        print("\n" + "=" * 40)
        print("  THEORA Setup Wizard")
        print("  (Install 'rich' for a better experience)")
        print("=" * 40 + "\n")

        THEORA_HOME.mkdir(parents=True, exist_ok=True)

        print("Step 1: LLM Provider")
        print("  1. OpenAI  2. Anthropic  3. Gemini  4. Ollama (local)")
        choice = input("Choose (1-4) [1]: ").strip() or "1"
        providers = {"1": "openai", "2": "anthropic", "3": "gemini", "4": "ollama"}
        provider = providers.get(choice, "openai")
        pinfo = PROVIDER_CONFIGS[provider]

        if pinfo["env_key"] and not os.getenv(pinfo["env_key"]):
            api_key = input(f"Enter {pinfo['name']} API key: ").strip()
            if api_key:
                os.environ[pinfo["env_key"]] = api_key
                creds_path = THEORA_HOME / "credentials.json"
                creds = {}
                if creds_path.exists():
                    try:
                        creds = json.loads(creds_path.read_text())
                    except Exception:
                        pass
                creds[pinfo["env_key"]] = api_key
                creds_path.write_text(json.dumps(creds, indent=2))
                print("  Key saved.")

        print("\nStep 2: Agent Identity")
        name = input("Agent name [THEORA]: ").strip() or "THEORA"
        print("  Personalities: professional, friendly, minimal, creative")
        archetype = input("Choose [friendly]: ").strip() or "friendly"
        personality = PERSONALITY_ARCHETYPES.get(archetype, PERSONALITY_ARCHETYPES["friendly"])

        try:
            import yaml
            identity = {
                "name": name, "personality": personality,
                "rules": ["Be helpful", "Respect privacy"],
            }
            (THEORA_HOME / "IDENTITY.yaml").write_text(
                yaml.dump(identity, default_flow_style=False)
            )
            print(f"  Identity saved to {THEORA_HOME / 'IDENTITY.yaml'}")
        except Exception:
            pass

        print("\nSetup complete! Run 'theora start' to begin.")
