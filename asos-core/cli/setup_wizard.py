#!/usr/bin/env python3
"""
THEORA Setup Wizard — Terminal-based guided configuration
==========================================================
Walks the user through provider selection, API key entry,
feature toggles, and security mode. Writes ~/.theora/config.yaml
and ~/.theora/credentials.json.

Usage: theora setup
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

THEORA_HOME = Path(os.environ.get("THEORA_HOME", Path.home() / ".theora"))
CREDENTIALS_FILE = THEORA_HOME / "credentials.json"
CONFIG_FILE = THEORA_HOME / "config.yaml"

PROVIDERS = {
    "1": {"name": "OpenAI", "key_env": "OPENAI_API_KEY", "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]},
    "2": {"name": "Anthropic (Claude)", "key_env": "ANTHROPIC_API_KEY", "models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"]},
    "3": {"name": "Google Gemini (free tier)", "key_env": "GEMINI_API_KEY", "models": ["gemini-2.0-flash", "gemini-1.5-pro"]},
    "4": {"name": "Groq (fast cloud)", "key_env": "GROQ_API_KEY", "models": ["llama-3.1-70b-versatile", "mixtral-8x7b-32768"]},
    "5": {"name": "Ollama (local, free)", "key_env": None, "models": ["llama3.1", "mistral", "gemma2"]},
    "6": {"name": "Skip (direct-execution only)", "key_env": None, "models": []},
}


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[92m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[93m{text}\033[0m"


def _cyan(text: str) -> str:
    return f"\033[96m{text}\033[0m"


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _prompt(msg: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"  {msg}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Setup cancelled.")
        sys.exit(0)
    return val or default


def _prompt_choice(msg: str, options: dict[str, str], default: str = "1") -> str:
    for key, label in options.items():
        marker = _green("→") if key == default else " "
        print(f"  {marker} [{key}] {label}")
    return _prompt(msg, default)


def _prompt_yn(msg: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = _prompt(f"{msg} ({hint})", "y" if default else "n")
    return val.lower() in ("y", "yes", "1", "true")


def _load_credentials() -> dict:
    if CREDENTIALS_FILE.exists():
        return json.loads(CREDENTIALS_FILE.read_text())
    return {}


def _save_credentials(creds: dict):
    THEORA_HOME.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass


def _save_config(config: dict):
    THEORA_HOME.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    except ImportError:
        json_path = THEORA_HOME / "config.json"
        json_path.write_text(json.dumps(config, indent=2))
        print(f"  {_dim('(pyyaml not installed — saved as config.json)')}")


def _detect_ollama() -> list[str]:
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            models = []
            for line in result.stdout.strip().splitlines()[1:]:
                name = line.split()[0] if line.split() else ""
                if name and ":" in name:
                    name = name.split(":")[0]
                if name:
                    models.append(name)
            return models
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


def _offer_ollama_pull():
    print(f"\n  {_yellow('No Ollama models found.')}")
    if _prompt_yn("Pull llama3.1 now? (~4GB download)"):
        print(f"  Pulling llama3.1 ... (this may take a few minutes)")
        try:
            subprocess.run(["ollama", "pull", "llama3.1"], check=True)
            print(f"  {_green('Done!')}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"  {_yellow(f'Failed: {e}')}")
            print(f"  You can pull manually later: ollama pull llama3.1")


def run_setup():
    print(f"""
  {_bold('╔══════════════════════════════════════╗')}
  {_bold('║          T H E O R A  Setup          ║')}
  {_bold('╚══════════════════════════════════════╝')}
  {_dim('Configure your AI agent in 60 seconds.')}
""")

    creds = _load_credentials()
    config = {
        "version": "1.0.0",
        "llm": {},
        "features": {},
        "security": {},
    }

    # ─── Step 1: LLM Provider ─────────────────────────────────────

    print(f"  {_bold('1. LLM Provider')}")
    print(f"  {_dim('Choose how THEORA thinks:')}\n")

    provider_choice = _prompt_choice(
        "Select provider",
        {k: v["name"] for k, v in PROVIDERS.items()},
        default="1",
    )

    provider = PROVIDERS[provider_choice]
    config["llm"]["provider"] = provider["name"].split(" ")[0].lower()

    if provider["key_env"]:
        existing = os.environ.get(provider["key_env"], "")
        if existing:
            print(f"  {_green('✓')} Found {provider['key_env']} in environment")
            creds[provider["key_env"]] = existing
        else:
            key = _prompt(f"Paste your {provider['name']} API key")
            if key:
                creds[provider["key_env"]] = key
                os.environ[provider["key_env"]] = key
                print(f"  {_green('✓')} Key stored securely")
            else:
                print(f"  {_yellow('⚠')} No key provided — some features may not work")

    if config["llm"]["provider"] == "ollama":
        models = _detect_ollama()
        if models:
            print(f"\n  {_green('✓')} Ollama running with models: {', '.join(models[:5])}")
            config["llm"]["model"] = models[0]
        else:
            _offer_ollama_pull()
            config["llm"]["model"] = "llama3.1"
    elif provider["models"]:
        config["llm"]["model"] = provider["models"][0]

    print(f"\n  {_green('✓')} Provider: {config['llm']['provider']} / {config['llm'].get('model', '?')}")

    # ─── Step 2: Feature Toggles ──────────────────────────────────

    print(f"\n  {_bold('2. Features')}")
    print(f"  {_dim('Toggle what THEORA can do:')}\n")

    config["features"]["computer_use"] = True
    print(f"  {_green('✓')} Computer use (bash, files, search) — always on")

    config["features"]["web_search"] = True
    tavily_key = creds.get("TAVILY_API_KEY", os.environ.get("TAVILY_API_KEY", ""))
    if not tavily_key:
        print(f"  {_yellow('⚠')} Web search needs a Tavily API key (free at tavily.com)")
        key = _prompt("Paste Tavily API key (or Enter to skip)")
        if key:
            creds["TAVILY_API_KEY"] = key
            creds["web_search"] = key
            os.environ["TAVILY_API_KEY"] = key
            print(f"  {_green('✓')} Tavily key stored")
    else:
        creds["web_search"] = tavily_key
        print(f"  {_green('✓')} Web search — Tavily key found")

    config["features"]["voice"] = _prompt_yn("Enable voice (requires OpenAI key)?", default=False)
    if config["features"]["voice"]:
        print(f"  {_green('✓')} Voice enabled")

    config["features"]["vision"] = _prompt_yn("Enable vision (camera/screen analysis)?", default=False)
    if config["features"]["vision"]:
        print(f"  {_green('✓')} Vision enabled")

    config["features"]["hardware"] = _prompt_yn("Enable hardware daemon connections?", default=True)
    config["features"]["memory"] = True
    print(f"  {_green('✓')} Memory — always on (4-tier: working, notes, episodes, knowledge)")

    # ─── Step 3: Security ─────────────────────────────────────────

    print(f"\n  {_bold('3. Security')}")
    print(f"  {_dim('How cautious should THEORA be?')}\n")

    sec_choice = _prompt_choice(
        "Permission mode",
        {
            "1": "Cautious — ask before destructive actions (recommended)",
            "2": "Permissive — auto-approve most actions",
            "3": "Locked — deny all destructive actions",
        },
        default="1",
    )

    mode_map = {"1": "cautious", "2": "permissive", "3": "locked"}
    config["security"]["mode"] = mode_map[sec_choice]

    # ─── Step 4: Agent Identity ───────────────────────────────────

    print(f"\n  {_bold('4. Agent Identity')}")
    name = _prompt("Agent name", "THEORA")
    tagline = _prompt("Tagline", "Your local-first agentic intelligence")
    config["identity"] = {"name": name, "tagline": tagline}

    # ─── Save ─────────────────────────────────────────────────────

    _save_credentials(creds)
    _save_config(config)

    print(f"""
  {_bold('═══════════════════════════════════════')}
  {_green('✓')} Configuration saved to {THEORA_HOME}/
  {_dim(f'  Config:      {CONFIG_FILE}')}
  {_dim(f'  Credentials: {CREDENTIALS_FILE}')}

  {_bold('Next steps:')}
    theora serve     Start the Brain server
    theora           Interactive chat (requires Brain running)

  {_dim('Edit config anytime: theora setup')}
  {_bold('═══════════════════════════════════════')}
""")


if __name__ == "__main__":
    run_setup()
