<p align="center">
  <img src="https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/Theora-logo.png" alt="THEORA" width="120" />
</p>

<h1 align="center">THEORA</h1>

<p align="center">
  <strong>Open-source AI agent with computer use, voice, GenUI, memory, and hardware control.</strong>
</p>

<p align="center">
  <a href="#install">Install</a> •
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#voice">Voice</a> •
  <a href="#memory">Memory</a> •
  <a href="#custom-tools">Custom Tools</a> •
  <a href="#hardware">Hardware</a> •
  <a href="#mcp">MCP</a> •
  <a href="#docker">Docker</a> •
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License" />
  <img src="https://img.shields.io/badge/LLM-OpenAI%20%7C%20Anthropic%20%7C%20Gemini%20%7C%20Groq%20%7C%20Ollama-purple" alt="Providers" />
  <img src="https://img.shields.io/badge/voice-OpenAI%20Realtime-orange" alt="Voice" />
</p>

---

## What is THEORA?

THEORA is a **local-first AI agent** that connects to your tools, devices, and data. Unlike cloud-only assistants, THEORA runs on your machine — your conversations, memory, and API keys never leave your control.

It can:
- **Use your computer** — run shell commands, read/write files, search codebases
- **Search the web** — real-time web search with AI summaries
- **Talk to you** — bi-directional voice conversation via OpenAI Realtime API, with tool use mid-conversation
- **Remember everything** — 4-tier persistent memory (notes, episodes, knowledge graph)
- **Render rich UI** — tool results display as cards, metrics, and interactive components (GenUI)
- **Control hardware** — smart glasses, wristbands, IoT devices connect via WebSocket
- **Work with any LLM** — OpenAI, Anthropic Claude, Google Gemini, Groq, Ollama (local/free)

---

## Install

**One command:**

```bash
curl -sSL https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/scripts/install.sh | bash
```

This checks Python 3.11+, installs THEORA via pip, and launches a **guided setup wizard** that walks you through:

1. Choosing an LLM provider (with explanations and pricing)
2. Creating your agent's identity (name, personality, voice)
3. Understanding the memory system
4. Configuring voice mode (realtime / classic / off)
5. Enabling tools (computer use, web search, vision, hardware)
6. Setting security preferences

**Manual install:**

```bash
git clone https://github.com/Spatial-AgenticOS/ASOS.git
cd ASOS
pip install -e "asos-core[llm]"
theora setup      # guided configuration
theora serve      # start the server
theora            # interactive chat
```

---

## Features

### Working & Tested

| Feature | Description |
|:--------|:------------|
| **Computer Use** | `bash`, `read_file`, `write_file`, `edit_file`, `grep_search`, `glob_search`, `web_fetch` |
| **Web Search** | Tavily-powered search with AI summaries |
| **Multi-Provider LLM** | OpenAI, Anthropic, Gemini, Groq, Ollama — switch at runtime |
| **Realtime Voice** | Bi-directional conversation via OpenAI Realtime API with tool use |
| **4-Tier Memory** | Working memory, notes, episodes, knowledge graph — all in local SQLite |
| **GenUI** | Tool results render as cards, metrics, lists, maps — not just raw text |
| **Multi-Agent** | Router dispatches to specialist workers (health, home, research, creative) |
| **CLI Agent** | REPL mode, one-shot commands, status dashboard |
| **Setup Wizard** | `theora setup` — 7-step guided onboarding with identity, voice, memory config |
| **MCP Server** | Expose THEORA's tools to Claude Desktop, Cursor, or any MCP client |
| **MCP Client** | Connect external MCP servers — their tools merge into your agent |
| **Hardware Daemons** | WebSocket devices send telemetry and receive commands |
| **Skill Manifests** | Drop a JSON file to add any REST API as an agent tool |
| **Blind Vault** | API keys stored securely, never exposed to the LLM |
| **Hot Provider Switch** | `POST /api/llm/switch` — change LLM provider without restarting |
| **Self-Learning** | Agent learns routing preferences and extracts knowledge over time |
| **Web Dashboard** | React UI at `localhost:9090` — bundled with the server |

### API Keys Required

| Key | What For | Free Tier |
|:----|:---------|:----------|
| `OPENAI_API_KEY` | LLM + Voice + Vision | Pay-as-you-go |
| `TAVILY_API_KEY` | Web search | Free at [tavily.com](https://tavily.com) |
| None | Use Ollama for free local LLM | `ollama serve` + `ollama pull llama3.1` |

---

## Quick Start

```bash
# Start the server
theora serve

# In another terminal — try these:
theora "what files are in my home directory?"
theora "search the web for latest AI news"
theora "remember that my favorite color is blue"
theora "what's my favorite color?"
theora status
theora skills
```

**Web UI:** Open [http://localhost:9090](http://localhost:9090) — chat, voice, and GenUI in your browser.

---

<a id="architecture"></a>
## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        THEORA Brain                          │
│                    (FastAPI / Python)                         │
│                                                              │
│  ┌─────────────┐  ┌──────────┐  ┌────────────────────────┐  │
│  │ Orchestrator │──│ LLM      │  │ Tools                  │  │
│  │ (agentic    │  │ Provider │  │  • Computer use (7)    │  │
│  │  loop)      │  │ ┌──────┐ │  │  • Web search          │  │
│  │             │  │ │OpenAI│ │  │  • Notes/memory         │  │
│  │ Multi-agent │  │ │Claude│ │  │  • Hardware commands    │  │
│  │ router →    │  │ │Gemini│ │  │  • Custom skills (JSON) │  │
│  │ workers     │  │ │Groq  │ │  │  • MCP tools            │  │
│  │             │  │ │Ollama│ │  └────────────────────────┘  │
│  └──────┬──────┘  └──────┘ │                                │
│         │                   │  ┌────────────────────────┐   │
│         │    ┌──────────┐   │  │ Memory                 │   │
│         ├────│ GenUI    │   │  │  Tier 1: Working (RAM) │   │
│         │    │ Engine   │   │  │  Tier 2: Notes (SQLite)│   │
│         │    └──────────┘   │  │  Tier 3: Episodes      │   │
│         │                   │  │  Tier 4: Knowledge     │   │
│         │    ┌──────────┐   │  │         Graph          │   │
│         └────│ Voice    │   │  └────────────────────────┘   │
│              │ Router   │   │                                │
│              │ ┌──────┐ │   │  ┌────────────────────────┐   │
│              │ │RT API│ │   │  │ Security               │   │
│              │ │Whspr │ │   │  │  Blind vault, sandbox  │   │
│              │ │TTS   │ │   │  │  Permission tiers      │   │
│              │ └──────┘ │   │  └────────────────────────┘   │
│              └──────────┘   │                                │
└──────────┬──────────────┬───┘────────────┬──────────────────┘
           │              │                │
    ┌──────┴──────┐ ┌─────┴─────┐  ┌──────┴──────┐
    │  Web UI     │ │   CLI     │  │  Hardware   │
    │ React/Vite  │ │  theora   │  │  Daemons    │
    │ :9090       │ │  command  │  │  (WebSocket) │
    └─────────────┘ └───────────┘  └─────────────┘
```

---

<a id="voice"></a>
## Voice

THEORA supports **two voice modes**, configured during `theora setup`:

### Realtime Voice (recommended)

Bi-directional conversation through the **OpenAI Realtime API**. The agent hears you, responds with natural speech, and can **use tools mid-conversation** — search the web, check your notes, run commands, all while talking to you.

- Server-side VAD (voice activity detection)
- Interruption support — talk over the agent to stop it
- PCM16 24kHz audio streaming
- Works from the **web UI** (click the mic button) or **hardware daemons**

### Classic Voice (Whisper + TTS)

Speech-to-text via Whisper → brain processes → text-to-speech. Higher latency but works with any LLM provider.

### Configuration

```yaml
# ~/.theora/config.yaml
voice:
  mode: realtime    # realtime | whisper | disabled
  tts_voice: nova   # nova | sage | alloy | echo | shimmer
  wake_word: false   # "Hey THEORA" detection
```

---

<a id="memory"></a>
## Memory

THEORA uses a **4-tier local memory system** — richer than most AI agents:

| Tier | What | Persisted | Example |
|:-----|:-----|:----------|:--------|
| **Working** | Current conversation context | RAM (per-session) | Recent messages, tool results |
| **Notes** | Things you tell it to remember | SQLite + FTS | "Remember my WiFi password is..." |
| **Episodes** | Past conversation summaries | SQLite + FTS | Auto-generated after each session |
| **Knowledge Graph** | Facts and relationships | SQLite (S-P-O triples) | "User prefers dark mode" |

Plus an **execution log** that tracks every tool call for routing optimization.

```bash
# Everything stored locally
~/.theora/memory.db      # SQLite database
~/.theora/sync_wal.db    # Federated sync WAL (optional)
```

**No cloud.** You own your data.

---

<a id="custom-tools"></a>
## Custom Tools

### JSON Manifest (any REST API)

Drop a file in `~/.theora/skills/`:

```json
{
  "skill_id": "my_api",
  "brand": { "name": "My API", "icon": "🔧", "primary_color": "#6c5ce7" },
  "description": "The LLM reads this to decide when to use your tool",
  "auth": { "type": "api_key", "api_key_header": "X-API-Key" },
  "endpoints": [{
    "id": "get_data",
    "method": "GET",
    "url": "https://api.example.com/data",
    "description": "Fetches data by query",
    "params": [{ "name": "query", "type": "string", "required": true }]
  }]
}
```

Set the key: `THEORA_KEY_my_api=your-key-here`

### Python-Backed Skill (complex logic)

For tools that need custom logic (not just HTTP calls), create a Python class. See `asos-core/skills/impl/computer_use.py` for a full example.

---

<a id="hardware"></a>
## Hardware

Any device can connect as a **hardware daemon** over WebSocket:

```python
import asyncio, json, websockets

async def main():
    uri = "ws://localhost:9090/v1/node?api_key=dev-secret-key"
    async with websockets.connect(uri) as ws:
        # Register
        await ws.send(json.dumps({
            "hop": "daemon", "type": "node_register",
            "payload": {
                "node_id": "my-sensor",
                "node_type": "sensor",
                "capabilities": ["temperature", "humidity"]
            }
        }))

        # Send telemetry
        while True:
            await ws.send(json.dumps({
                "hop": "daemon", "type": "telemetry",
                "payload": {
                    "node_id": "my-sensor",
                    "sensors": {"temperature_c": 22.5, "humidity": 45}
                }
            }))
            await asyncio.sleep(5)

asyncio.run(main())
```

**Supported devices:**
- Smart glasses (THEORA W300, any BLE-capable glasses)
- Wristbands (heart rate, SpO2, temperature)
- IoT devices (via Home Assistant bridge)
- Robots (custom daemon)
- Phone as Bluetooth bridge (iOS SDK included)

---

<a id="mcp"></a>
## MCP Integration

### THEORA as MCP Server

Expose THEORA's tools to Claude Desktop, Cursor, or any MCP-compatible client:

```json
{
  "mcpServers": {
    "theora": {
      "url": "http://localhost:9090/mcp"
    }
  }
}
```

Available MCP tools: `theora_chat`, `theora_bash`, `theora_web_search`, `theora_memory_query`, `theora_skill_list`

### THEORA as MCP Client

Connect external MCP servers — their tools automatically merge into your agent:

```json
// ~/.theora/mcp_servers.json
{
  "servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  ]
}
```

---

<a id="docker"></a>
## Docker

```bash
cp .env.example .env    # edit with your API keys
docker compose up -d

# Brain:  http://localhost:9090
# Client: http://localhost:3000
```

---

## Project Structure

```
ASOS/
├── asos-core/                  # Agent brain (Python, FastAPI)
│   ├── api/server.py           # WebSocket + REST server
│   ├── agents/                 # Orchestrator, multi-agent router, learner
│   │   ├── orchestrator.py     # Main agentic loop
│   │   ├── llm_provider.py     # Multi-provider LLM interface
│   │   └── multi_agent.py      # Specialist worker routing
│   ├── skills/                 # Tool registry, executor, manifests
│   │   ├── manifests/          # JSON skill definitions
│   │   └── impl/               # Python-backed skill implementations
│   ├── memory/                 # 4-tier store + federated sync
│   ├── voice/                  # Realtime proxy, router, audio pipeline
│   ├── cli/                    # CLI (theora command) + setup wizard
│   ├── security/               # Blind vault, permissions, WASM sandbox
│   ├── hardware/               # Hardware Use Protocol (HUP)
│   ├── mcp/                    # MCP server + client
│   └── config/                 # Identity, loader
├── asos-client/                # React web UI (Vite + Tailwind)
├── asos-nodes/                 # Hardware daemon SDKs
│   ├── python-node-sdk/        # Python daemon reference
│   ├── ios-bridge/             # iOS bridge (Swift)
│   └── android-bridge/         # Android bridge (Kotlin)
├── scripts/
│   ├── install.sh              # curl installer
│   └── demo.py                 # Feature demo script
└── docker-compose.yml
```

---

## Configuration

All config lives in `~/.theora/`:

| File | What |
|:-----|:-----|
| `config.yaml` | Feature flags, LLM provider, voice mode, security |
| `credentials.json` | API keys (chmod 600, auto-loaded at startup) |
| `identity.yaml` | Agent name, personality, voice, rules |
| `memory.db` | Persistent memory (SQLite) |
| `skills/` | Custom skill manifests |
| `mcp_servers.json` | External MCP server connections |

### Environment Variables

| Variable | What | Default |
|:---------|:-----|:--------|
| `OPENAI_API_KEY` | LLM + voice | — |
| `ANTHROPIC_API_KEY` | Claude models | — |
| `GEMINI_API_KEY` | Google Gemini | — |
| `GROQ_API_KEY` | Groq (fast inference) | — |
| `TAVILY_API_KEY` | Web search | — |
| `THEORA_LLM_PROVIDER` | Provider override | `openai` |
| `THEORA_LLM_MODEL` | Model override | `gpt-4o-mini` |
| `NODE_API_KEY` | Daemon authentication | `dev-secret-key` |

---

## REST API

| Endpoint | Method | Description |
|:---------|:-------|:------------|
| `/health` | GET | Server health check |
| `/api/info` | GET | System info and capabilities |
| `/api/llm/status` | GET | Current LLM provider and availability |
| `/api/llm/switch` | POST | Hot-swap LLM provider |
| `/api/voice/status` | GET | Voice subsystem status |
| `/api/dashboard` | GET | Full dashboard data |
| `/api/identity` | GET | Agent identity config |
| `/skills` | GET | List all loaded skills |
| `/api/devices` | GET | Connected hardware devices |
| `/v1/session` | WS | Client WebSocket (chat, voice, UI events) |
| `/v1/node` | WS | Hardware daemon WebSocket |
| `/mcp` | POST | MCP JSON-RPC endpoint |
| `/docs` | GET | Interactive API documentation (Swagger) |

---

## What's Not Done Yet

Transparency matters:

- **PyPI publishing** — install from GitHub for now
- **Vision** — VLM integration code exists, needs camera/screen capture wired end-to-end
- **Wake word** — "Hey THEORA" code works with energy fallback; full model needs `openwakeword`
- **Android app** — SDK code exists, not yet a standalone buildable app
- **Desktop GUI** — Tauri scaffold exists, not built
- **Skill marketplace** — registry code exists, server not deployed
- **Federated sync** — CRDT code exists, not tested across real devices

---

<a id="contributing"></a>
## Contributing

```bash
git clone https://github.com/Spatial-AgenticOS/ASOS.git
cd ASOS/asos-core
pip install -e ".[llm,dev]"
pytest                    # run tests (187 passing)
theora setup              # configure locally
theora serve              # start developing
```

---

## Contact

**Alpay Kasal** — [info@theora.io](mailto:info@theora.io)

## License

Apache 2.0 with attribution — see [NOTICE](NOTICE).

> Built with [THEORA](https://github.com/Spatial-AgenticOS/ASOS)

Copyright 2024–2026 THEORA, Inc. Created by Mahmoud Omar and Alpay Kasal.
