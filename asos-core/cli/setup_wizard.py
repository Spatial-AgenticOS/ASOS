#!/usr/bin/env python3
"""
THEORA Setup Wizard — Comprehensive guided onboarding
======================================================
Walks the user through every aspect of THEORA configuration:
  1. LLM provider selection (cloud + local options)
  2. Additional API keys (search, etc.)
  3. Agent identity (name, personality, voice, rules)
  4. Memory system explanation + config
  5. Voice configuration (realtime vs classic, wake word)
  6. Vision configuration
  7. Hardware connection guide
  8. Security mode

Writes:
  ~/.theora/config.yaml       — feature flags and settings
  ~/.theora/credentials.json  — API keys (600 perms)
  ~/.theora/identity.yaml     — agent personality

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
IDENTITY_FILE = THEORA_HOME / "identity.yaml"

# ─── Terminal colors ──────────────────────────────────────

def _bold(t: str) -> str: return f"\033[1m{t}\033[0m"
def _green(t: str) -> str: return f"\033[92m{t}\033[0m"
def _yellow(t: str) -> str: return f"\033[93m{t}\033[0m"
def _cyan(t: str) -> str: return f"\033[96m{t}\033[0m"
def _dim(t: str) -> str: return f"\033[2m{t}\033[0m"
def _red(t: str) -> str: return f"\033[91m{t}\033[0m"
def _blue(t: str) -> str: return f"\033[94m{t}\033[0m"
def _magenta(t: str) -> str: return f"\033[95m{t}\033[0m"

def _hr():
    print(f"  {_dim('─' * 52)}")

def _section(num: int, title: str, subtitle: str = ""):
    print(f"\n  {_bold(_cyan(f'Step {num}'))}  {_bold(title)}")
    if subtitle:
        print(f"  {_dim(subtitle)}")
    print()


# ─── Input helpers ────────────────────────────────────────

def _prompt(msg: str, default: str = "") -> str:
    hint = f" [{_dim(default)}]" if default else ""
    try:
        val = input(f"  {msg}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n  {_yellow('Setup cancelled.')}")
        sys.exit(0)
    return val or default


def _prompt_choice(msg: str, options: dict[str, str], default: str = "1") -> str:
    for key, label in options.items():
        marker = _green("▸") if key == default else " "
        print(f"    {marker} [{key}] {label}")
    print()
    return _prompt(msg, default)


def _prompt_yn(msg: str, default: bool = True) -> bool:
    hint = _green("Y") + "/n" if default else "y/" + _green("N")
    val = _prompt(f"{msg} ({hint})", "y" if default else "n")
    return val.lower() in ("y", "yes", "1", "true")


def _prompt_multi(msg: str, options: dict[str, str], defaults: list[str] = None) -> list[str]:
    """Multi-select: user enters comma-separated numbers."""
    defaults = defaults or []
    for key, label in options.items():
        checked = _green("✓") if key in defaults else " "
        print(f"    {checked} [{key}] {label}")
    print()
    val = _prompt(msg, ",".join(defaults))
    return [v.strip() for v in val.split(",") if v.strip() in options]


# ─── File helpers ─────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_json(path: Path, data: dict, perms: int = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    if perms:
        try:
            os.chmod(path, perms)
        except OSError:
            pass


def _save_yaml(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _save_config(config: dict):
    THEORA_HOME.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    except ImportError:
        json_path = THEORA_HOME / "config.json"
        json_path.write_text(json.dumps(config, indent=2))


# ─── Provider detection ──────────────────────────────────

def _detect_ollama() -> list[str]:
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
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


# ─── Provider definitions ────────────────────────────────

PROVIDERS = {
    "1": {
        "name": "OpenAI",
        "key_env": "OPENAI_API_KEY",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
        "desc": "Best overall quality. Supports voice, vision, tool use. ~$0.15/1M input tokens.",
        "voice": True, "vision": True,
    },
    "2": {
        "name": "Anthropic (Claude)",
        "key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
        "desc": "Excellent reasoning and coding. No native voice/vision via this API.",
        "voice": False, "vision": False,
    },
    "3": {
        "name": "Google Gemini",
        "key_env": "GEMINI_API_KEY",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro"],
        "desc": "Free tier available. Good all-round model. Vision support.",
        "voice": False, "vision": True,
    },
    "4": {
        "name": "Groq",
        "key_env": "GROQ_API_KEY",
        "models": ["llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
        "desc": "Extremely fast inference. Free tier. Open-source models.",
        "voice": False, "vision": False,
    },
    "5": {
        "name": "Ollama (local, private, free)",
        "key_env": None,
        "models": ["llama3.1", "mistral", "gemma2", "qwen2"],
        "desc": "Runs entirely on your machine. No API key needed. Requires Ollama installed.",
        "voice": False, "vision": False,
    },
}

VOICE_PROVIDERS = {
    "1": {"name": "OpenAI Realtime API", "desc": "Bi-directional voice with tool use. Natural conversation. Requires OpenAI key.", "key": "OPENAI_API_KEY"},
    "2": {"name": "OpenAI Whisper + TTS", "desc": "Classic STT→brain→TTS pipeline. More control, slight latency.", "key": "OPENAI_API_KEY"},
    "3": {"name": "Disabled", "desc": "Text-only mode.", "key": None},
}


# ══════════════════════════════════════════════════════════
# Main Setup Flow
# ══════════════════════════════════════════════════════════

def run_setup():
    print(f"""
  {_bold('╔══════════════════════════════════════════════════════╗')}
  {_bold('║')}          {_bold(_cyan('T H E O R A'))}   {_bold('Setup Wizard')}              {_bold('║')}
  {_bold('╚══════════════════════════════════════════════════════╝')}

  {_dim('Welcome! This wizard will configure your personal AI agent.')}
  {_dim('It takes about 2 minutes. You can re-run anytime: theora setup')}
""")

    creds = _load_json(CREDENTIALS_FILE)
    config = {"version": "1.0.0", "llm": {}, "features": {}, "security": {}, "voice": {}, "vision": {}}
    identity = {}

    # ═══════════════════════════════════════════════════════
    # STEP 1: LLM Provider
    # ═══════════════════════════════════════════════════════
    _section(1, "AI Provider", "Choose the brain behind your agent")

    print(f"    {_dim('Cloud providers need an API key. Local runs on your machine for free.')}\n")

    provider_opts = {}
    for k, v in PROVIDERS.items():
        tags = []
        if v.get("voice"): tags.append(_green("voice"))
        if v.get("vision"): tags.append(_blue("vision"))
        tag_str = f" ({', '.join(tags)})" if tags else ""
        provider_opts[k] = f"{v['name']}{tag_str}\n      {_dim(v['desc'])}"

    provider_choice = _prompt_choice("Select provider", provider_opts, default="1")
    provider = PROVIDERS.get(provider_choice, PROVIDERS["1"])
    config["llm"]["provider"] = provider["name"].split(" ")[0].lower()

    # API key entry
    if provider["key_env"]:
        existing = creds.get(provider["key_env"], "") or os.environ.get(provider["key_env"], "")
        if existing:
            masked = existing[:8] + "..." + existing[-4:]
            print(f"  {_green('✓')} Found existing key: {_dim(masked)}")
            if _prompt_yn("Use this key?"):
                creds[provider["key_env"]] = existing
            else:
                key = _prompt(f"Paste new {provider['name']} API key")
                if key:
                    creds[provider["key_env"]] = key
        else:
            print(f"  {_dim('You need an API key from')} {provider['name']}")
            key = _prompt(f"Paste {provider['name']} API key (or Enter to skip)")
            if key:
                creds[provider["key_env"]] = key
                print(f"  {_green('✓')} Key saved")
            else:
                print(f"  {_yellow('⚠')} No key — agent will run in limited mode")

    # Ollama detection
    if config["llm"]["provider"] == "ollama":
        models = _detect_ollama()
        if models:
            print(f"\n  {_green('✓')} Ollama running with: {', '.join(models[:5])}")
            config["llm"]["model"] = models[0]
        else:
            print(f"\n  {_yellow('Ollama not detected.')}")
            if _prompt_yn("Pull llama3.1 now? (~4GB)"):
                print(f"  Pulling... (this takes a few minutes)")
                try:
                    subprocess.run(["ollama", "pull", "llama3.1"], check=True)
                    print(f"  {_green('Done!')}")
                except Exception as e:
                    print(f"  {_yellow(f'Failed: {e}. Pull manually: ollama pull llama3.1')}")
            config["llm"]["model"] = "llama3.1"
    elif provider["models"]:
        print(f"\n  Available models: {', '.join(provider['models'])}")
        model = _prompt("Model", provider["models"][0])
        config["llm"]["model"] = model

    print(f"\n  {_green('✓')} Provider: {_bold(config['llm']['provider'])} / {config['llm'].get('model', '?')}")

    # ═══════════════════════════════════════════════════════
    # STEP 2: Agent Identity
    # ═══════════════════════════════════════════════════════
    _section(2, "Agent Identity", "Give your agent a personality")

    print(f"    {_dim('This is what makes YOUR agent unique. Like a soul for your AI.')}")
    quote = "system identity"
    print(f"    {_dim(f'OpenClaw calls this the {quote} — we make it richer.')}\n")

    name = _prompt("Agent name", "THEORA")
    tagline = _prompt("Tagline", "Your personal AI assistant — local, private, always learning")

    print(f"\n  {_bold('Personality presets:')}")
    personality_opts = {
        "1": f"Professional — {_dim('Clear, efficient, business-like')}",
        "2": f"Friendly — {_dim('Warm, casual, encouraging (recommended)')}",
        "3": f"Minimal — {_dim('Ultra-concise, just the facts')}",
        "4": f"Custom — {_dim('Write your own personality description')}",
    }
    p_choice = _prompt_choice("Personality", personality_opts, default="2")

    personalities = {
        "1": "You are professional and efficient. You give clear, concise answers without unnecessary pleasantries. You focus on accuracy and getting things done.",
        "2": "You are warm, direct, and efficient. You don't waste words but you're never cold. You proactively notice things and remember past conversations. You speak like a capable personal assistant who knows the user well.",
        "3": "You are minimal. Answer in as few words as possible. No greetings, no filler. Just facts and actions.",
    }

    if p_choice == "4":
        personality = _prompt("Describe the personality", personalities["2"])
    else:
        personality = personalities.get(p_choice, personalities["2"])

    print(f"\n  {_bold('Communication style:')}")
    tone_opts = {
        "1": f"Conversational — {_dim('natural, like talking to a friend')}",
        "2": f"Formal — {_dim('structured, professional')}",
        "3": f"Casual — {_dim('relaxed, uses contractions')}",
    }
    tone = _prompt_choice("Tone", tone_opts, default="1")
    tone_map = {"1": "conversational", "2": "formal", "3": "casual"}

    verbosity_opts = {
        "1": f"Concise — {_dim('1-3 sentences (recommended for voice)')}",
        "2": f"Normal — {_dim('balanced detail')}",
        "3": f"Detailed — {_dim('thorough explanations')}",
    }
    verbosity = _prompt_choice("Verbosity", verbosity_opts, default="1")
    verbosity_map = {"1": "concise", "2": "normal", "3": "detailed"}

    custom_rules = []
    print(f"\n  {_dim('Add custom rules (one per line, empty line to finish):')}")
    while True:
        rule = _prompt("Rule (or Enter to finish)")
        if not rule:
            break
        custom_rules.append(rule)

    identity = {
        "name": name,
        "tagline": tagline,
        "personality": personality,
        "communication_style": {
            "tone": tone_map.get(tone, "conversational"),
            "verbosity": verbosity_map.get(verbosity, "concise"),
        },
        "rules": [
            "Never fabricate data. Only report what tools actually return.",
            "If a tool fails, explain clearly in plain language.",
            "Respect privacy. Everything runs locally unless explicitly shared.",
        ] + custom_rules,
        "greeting_style": "Brief and contextual. Mention relevant context if available.",
    }

    config["identity"] = {"name": name, "tagline": tagline}
    print(f"\n  {_green('✓')} Identity: {_bold(name)} — {_dim(tagline)}")

    # ═══════════════════════════════════════════════════════
    # STEP 3: Memory
    # ═══════════════════════════════════════════════════════
    _section(3, "Memory System", "How your agent remembers and learns")

    print(f"""    THEORA uses a {_bold('4-tier memory system')} — richer than most AI agents:

    {_cyan('Tier 1: Working Memory')}   {_dim('— Current conversation context (RAM, per-session)')}
    {_cyan('Tier 2: Notes')}            {_dim('— Things you tell it to remember (SQLite + full-text search)')}
    {_cyan('Tier 3: Episodes')}         {_dim('— Past conversations summaries (auto-generated)')}
    {_cyan('Tier 4: Knowledge Graph')}  {_dim('— Facts and relationships it learns over time (subject-predicate-object)')}

    {_dim('Plus: Execution log tracks every tool call for routing optimization.')}
    {_dim('All stored locally in ~/.theora/memory.db — no cloud, you own your data.')}

    {_bold('Compared to other agents:')}
    {_dim('• ChatGPT: cloud-only memory, limited control')}
    {_dim('• OpenClaw: basic conversation history')}
    {_dim('• THEORA: 4-tier local + knowledge graph + federated sync')}
""")

    config["features"]["memory"] = True
    print(f"  {_green('✓')} Memory enabled (always on)")

    if _prompt_yn("Enable federated sync (share memory across devices via P2P)?", default=False):
        config["features"]["federated_sync"] = True
        print(f"  {_green('✓')} Federated sync enabled — devices will discover each other on your network")
    else:
        config["features"]["federated_sync"] = False

    # ═══════════════════════════════════════════════════════
    # STEP 4: Voice
    # ═══════════════════════════════════════════════════════
    _section(4, "Voice Agent", "Talk to your AI naturally")

    has_openai_key = bool(creds.get("OPENAI_API_KEY"))

    print(f"""    THEORA supports {_bold('two voice modes')}:

    {_cyan('Realtime Voice')} (recommended)
      {_dim('Bi-directional conversation via OpenAI Realtime API.')}
      {_dim('Natural speech with interruption support. Tools work mid-conversation.')}
      {_dim('Your agent can search the web, control devices, check memory — all by voice.')}
      {_dim('Requires: OpenAI API key')}

    {_cyan('Classic Voice')} (Whisper + TTS)
      {_dim('Speech-to-text → brain processes → text-to-speech.')}
      {_dim('Slightly higher latency but works with any LLM provider.')}
      {_dim('Requires: OpenAI API key (for Whisper/TTS)')}

    {_cyan('Text Only')}
      {_dim('No voice. Chat via terminal or web UI.')}
""")

    if has_openai_key:
        voice_opts = {
            "1": f"Realtime Voice — {_dim('natural bi-directional conversation')}",
            "2": f"Classic Voice — {_dim('Whisper STT + TTS')}",
            "3": f"Text only",
        }
        vc = _prompt_choice("Voice mode", voice_opts, default="1")
    else:
        print(f"  {_yellow('No OpenAI key found. Voice requires an OpenAI API key.')}")
        add_key = _prompt_yn("Add OpenAI key for voice?", default=True)
        if add_key:
            key = _prompt("Paste OpenAI API key")
            if key:
                creds["OPENAI_API_KEY"] = key
                has_openai_key = True
                voice_opts = {
                    "1": f"Realtime Voice — {_dim('natural bi-directional conversation')}",
                    "2": f"Classic Voice — {_dim('Whisper STT + TTS')}",
                    "3": f"Text only",
                }
                vc = _prompt_choice("Voice mode", voice_opts, default="1")
            else:
                vc = "3"
        else:
            vc = "3"

    voice_mode_map = {"1": "realtime", "2": "whisper", "3": "disabled"}
    config["voice"]["mode"] = voice_mode_map.get(vc, "disabled")
    config["features"]["voice"] = vc != "3"

    if vc in ("1", "2"):
        print(f"\n  {_bold('Voice settings:')}")
        voice_opts_style = {
            "1": f"Nova — {_dim('warm, balanced female voice')}",
            "2": f"Sage — {_dim('calm, thoughtful')}",
            "3": f"Alloy — {_dim('neutral, clear')}",
            "4": f"Echo — {_dim('deep, resonant')}",
            "5": f"Shimmer — {_dim('bright, energetic')}",
        }
        v_style = _prompt_choice("TTS voice", voice_opts_style, default="1")
        voice_name_map = {"1": "nova", "2": "sage", "3": "alloy", "4": "echo", "5": "shimmer"}
        config["voice"]["tts_voice"] = voice_name_map.get(v_style, "nova")
        identity["voice"] = {"style": "conversational", "tts_voice": config["voice"]["tts_voice"], "speed": 1.0}

        if _prompt_yn("Enable wake word (\"Hey THEORA\")?", default=False):
            config["voice"]["wake_word"] = True
            print(f"  {_green('✓')} Wake word enabled — say \"Hey THEORA\" to activate")
        else:
            config["voice"]["wake_word"] = False

        print(f"\n  {_green('✓')} Voice: {_bold(voice_mode_map[vc])} / {config['voice']['tts_voice']}")
    else:
        print(f"\n  {_dim('Voice disabled. Enable anytime: theora setup')}")

    # ═══════════════════════════════════════════════════════
    # STEP 5: Tools & Capabilities
    # ═══════════════════════════════════════════════════════
    _section(5, "Tools & Capabilities", "What your agent can do")

    config["features"]["computer_use"] = True
    print(f"  {_green('✓')} Computer use (bash, files, search) — {_dim('always on')}")

    # Web search
    tavily_key = creds.get("TAVILY_API_KEY", "") or os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        print(f"\n  {_bold('Web Search')} — lets your agent search the internet")
        print(f"  {_dim('Requires a free Tavily API key from tavily.com')}")
        key = _prompt("Paste Tavily API key (or Enter to skip)")
        if key:
            creds["TAVILY_API_KEY"] = key
            creds["web_search"] = key
            config["features"]["web_search"] = True
            print(f"  {_green('✓')} Web search enabled")
        else:
            config["features"]["web_search"] = False
            print(f"  {_dim('Web search disabled. Add key later: theora setup')}")
    else:
        creds["web_search"] = tavily_key
        config["features"]["web_search"] = True
        print(f"  {_green('✓')} Web search — Tavily key found")

    # Vision
    print(f"\n  {_bold('Vision')} — camera/screen analysis via VLM")
    print(f"  {_dim('Lets the agent see through your camera or analyze screenshots.')}")
    print(f"  {_dim('Works with: GPT-4o (OpenAI), Gemini (Google), LLaVA/Moondream (local)')}")
    config["features"]["vision"] = _prompt_yn("Enable vision?", default=has_openai_key)
    if config["features"]["vision"]:
        print(f"  {_green('✓')} Vision enabled")

    # Hardware
    print(f"\n  {_bold('Hardware Connections')} — control physical devices")
    print(f"  {_dim('Connect smart glasses, wristbands, IoT devices, robots via Bluetooth/WiFi.')}")
    daemon_note = _dim('Devices connect as daemons over WebSocket to the Brain.')
    print(f"  {daemon_note}")
    print(f"  {_dim('Your phone can act as a bridge (Bluetooth → Brain via WebSocket).')}\n")
    print(f"  {_dim('Supported devices:')}")
    print(f"    {_dim('• Smart glasses (THEORA W300, any BLE glasses)')}")
    print(f"    {_dim('• Wristbands (heart rate, SpO2, temperature)')}")
    print(f"    {_dim('• IoT devices via Home Assistant')}")
    print(f"    {_dim('• Custom hardware via the daemon SDK')}")
    config["features"]["hardware"] = _prompt_yn("Enable hardware daemon connections?", default=True)
    if config["features"]["hardware"]:
        print(f"  {_green('✓')} Hardware enabled — daemons connect to ws://localhost:9090/v1/node")

    # ═══════════════════════════════════════════════════════
    # STEP 6: Security
    # ═══════════════════════════════════════════════════════
    _section(6, "Security", "How cautious should your agent be?")

    print(f"""    {_cyan('Cautious')} (recommended)
      {_dim('Asks before running destructive commands, deleting files, etc.')}

    {_cyan('Permissive')}
      {_dim('Auto-approves most actions. Faster but less safe.')}

    {_cyan('Locked')}
      {_dim('Denies all destructive actions. Read-only mode.')}
""")

    sec_opts = {
        "1": "Cautious (recommended)",
        "2": "Permissive",
        "3": "Locked (read-only)",
    }
    sec = _prompt_choice("Security mode", sec_opts, default="1")
    mode_map = {"1": "cautious", "2": "permissive", "3": "locked"}
    config["security"]["mode"] = mode_map.get(sec, "cautious")
    print(f"  {_green('✓')} Security: {_bold(config['security']['mode'])}")

    # ═══════════════════════════════════════════════════════
    # STEP 7: Additional Providers (optional)
    # ═══════════════════════════════════════════════════════
    _section(7, "Additional Providers", "Optional: add backup LLM providers")

    print(f"  {_dim('You can add multiple providers. THEORA can switch between them at runtime.')}")
    print(f"  {_dim('Useful for: cost optimization, speed, privacy, or specific capabilities.')}\n")

    if _prompt_yn("Add additional LLM providers?", default=False):
        for pk, pv in PROVIDERS.items():
            if pv["name"].split(" ")[0].lower() == config["llm"]["provider"]:
                continue
            if pv["key_env"] and not creds.get(pv["key_env"]):
                if _prompt_yn(f"Add {pv['name']}?", default=False):
                    key = _prompt(f"  {pv['name']} API key")
                    if key:
                        creds[pv["key_env"]] = key
                        print(f"  {_green('✓')} {pv['name']} key stored")
    else:
        print(f"  {_dim('Skipped. Add more providers anytime: theora setup')}")

    # ═══════════════════════════════════════════════════════
    # Save everything
    # ═══════════════════════════════════════════════════════
    _save_json(CREDENTIALS_FILE, creds, perms=0o600)
    _save_config(config)

    # Write identity.yaml
    identity_yaml = f"""# THEORA Agent Identity
# Generated by: theora setup
# Edit anytime to change your agent's personality.

name: "{identity.get('name', name)}"

tagline: "{identity.get('tagline', tagline)}"

personality: |
  {personality}

rules:
"""
    for rule in identity.get("rules", []):
        identity_yaml += f'  - "{rule}"\n'

    style = identity.get("communication_style", {})
    identity_yaml += f"""
communication_style:
  tone: "{style.get('tone', 'conversational')}"
  verbosity: "{style.get('verbosity', 'concise')}"

greeting_style: "{identity.get('greeting_style', 'Brief and contextual.')}"
"""

    if "voice" in identity:
        v = identity["voice"]
        identity_yaml += f"""
voice:
  style: "{v.get('style', 'conversational')}"
  tts_voice: "{v.get('tts_voice', 'nova')}"
  speed: {v.get('speed', 1.0)}
"""

    _save_yaml(IDENTITY_FILE, identity_yaml)

    # ═══════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════
    print(f"""
  {_bold('╔══════════════════════════════════════════════════════╗')}
  {_bold('║')}                 {_green('Setup Complete!')}                       {_bold('║')}
  {_bold('╚══════════════════════════════════════════════════════╝')}

  {_bold('Your agent: ' + name)}
  {_dim(tagline)}

  {_bold('Configuration saved:')}
    {_dim(f'Config:      {CONFIG_FILE}')}
    {_dim(f'Credentials: {CREDENTIALS_FILE}')}
    {_dim(f'Identity:    {IDENTITY_FILE}')}

  {_bold('What was configured:')}""")

    features = [
        ("LLM Provider", f"{config['llm']['provider']} / {config['llm'].get('model', '?')}"),
        ("Voice", f"{config['voice'].get('mode', 'disabled')} / {config['voice'].get('tts_voice', 'n/a')}" if config.get('voice', {}).get('mode') != 'disabled' else "disabled"),
        ("Memory", "4-tier (working, notes, episodes, knowledge graph)"),
        ("Computer Use", "bash, files, grep, glob, web_fetch"),
        ("Web Search", "Tavily" if config["features"].get("web_search") else "disabled"),
        ("Vision", "enabled" if config["features"].get("vision") else "disabled"),
        ("Hardware", "enabled" if config["features"].get("hardware") else "disabled"),
        ("Security", config["security"]["mode"]),
    ]

    for label, val in features:
        check = _green("✓") if "disabled" not in val.lower() else _dim("○")
        print(f"    {check} {label:16s} {val}")

    providers_found = []
    for pv in PROVIDERS.values():
        if pv["key_env"] and creds.get(pv["key_env"]):
            providers_found.append(pv["name"].split(" ")[0])
    if providers_found:
        print(f"    {_green('✓')} {'API Keys':16s} {', '.join(providers_found)}")

    print(f"""
  {_bold('Next steps:')}
    {_cyan('theora serve')}     Start the Brain server (port 9090)
    {_cyan('theora')}           Interactive chat in terminal
    {_dim('Open http://localhost:9090 for the web UI')}

  {_dim('Re-run setup anytime: theora setup')}
  {_dim('Edit identity:        ~/.theora/identity.yaml')}
  {_dim('Edit config:          ~/.theora/config.yaml')}

  {_bold('═══════════════════════════════════════════════════════')}
""")


if __name__ == "__main__":
    run_setup()
