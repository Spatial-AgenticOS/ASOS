# THEORA — The Universal Agentic Operating System

> **Not just computer use. Anything use.**

THEORA is a local-first, self-evolving agentic OS that connects any device — smart glasses, phones, robots, sensors, computers — into a unified intelligence layer. It sees, hears, feels, remembers, learns, creates its own tools, and asks permission before acting.

## What Works Today (v1.0.0)

Before diving in, here's an honest status of what you'll get when you clone and run:

| Feature | Status | Notes |
|---|---|---|
| **Chat with LLM** | Working | Requires `OPENAI_API_KEY` or local Ollama |
| **Streaming responses** | Working | Token-by-token to web client and CLI |
| **Skill execution** | Working | Web search (Tavily), weather, notes/memory |
| **Multi-agent routing** | Working | Health, Home, Research, Creative workers |
| **4-tier memory** | Working | SQLite with FTS, tested |
| **Hardware daemon connection** | Working | Python daemon connects, sends telemetry, receives commands |
| **Setup Wizard** | Working | 7-step guided onboarding |
| **Dashboard** | Working | Live device status, health metrics, activity feed, quick actions |
| **CLI (`theora`)** | Working | Interactive REPL and one-shot commands |
| **MCP Server** | Working | Claude Desktop can connect and use THEORA tools |
| **MCP Client** | Working | Auto-connects to external MCP servers, tools available to agent |
| **Blind Vault** | Working | Credentials never exposed to LLM |
| **SDUI rendering** | Working | 16 component types, agent generates dynamic UI |
| **Federated sync** | Code complete | CRDT + HLC + WAL ready; needs `zeroconf` for mDNS |
| **WASM sandbox** | Code complete | Needs `wasmtime` installed |
| **Wake word** | Code complete | Energy-based fallback; ML model needs `openwakeword` |
| **Skill marketplace** | Client ready | Registry server not yet deployed |
| **Android SDK** | Library code | Not a buildable app yet |
| **On-device LLM** | Available | Requires MLX (Apple Silicon) or llama.cpp |

**Requirements for full functionality:**
- `OPENAI_API_KEY` for LLM, STT, TTS, and vision — or run Ollama locally for LLM only
- `TAVILY_API_KEY` (or `THEORA_KEY_web_search`) for web search
- Optional: `THEORA_KEY_weather_current` for OpenWeather

Without an LLM key, the Brain runs in direct-execution mode (keyword-matched skill calls, no conversation).

## Architecture

```
   iPhone / Android                THEORA Brain (Mac/Linux/Server)           Edge Nodes
 ┌──────────────────┐           ┌─────────────────────────────────┐    ┌──────────────────┐
 │ THEORA Glasses ◄─┤  ←BLE→   │                                 │    │ Robot Daemon     │
 │ (W300 Sensors)   │           │   ┌─────────────────────────┐   │    │ GPIO / Serial    │
 │                  │  ←WS→     │   │  Multi-Agent Router     │   │◄──►│ Camera / Sensors │
 │ BrainClient      │──────────►│   │  ├── Health Worker      │   │    └──────────────────┘
 │ SensorBridge     │           │   │  ├── Home Worker        │   │
 │ WakeWordDetector │           │   │  ├── Research Worker    │   │    ┌──────────────────┐
 │ AudioManager     │           │   │  ├── Creative Worker    │   │    │ Desktop Daemon   │
 └──────────────────┘           │   │  ├── Skill Executor     │   │◄──►│ AppleScript      │
                                │   │  ├── Skill Generator    │   │    │ Keyboard / Shell │
 ┌──────────────────┐           │   │  ├── 4-Tier Memory      │   │    └──────────────────┘
 │ React Client     │           │   │  │   └── Federated Sync │   │
 │ /setup  Wizard   │  ←WS→    │   │  ├── Perception Fusion  │   │    ┌──────────────────┐
 │ /       Dashboard│──────────►│   │  ├── Wake Word + Voice  │   │    │ Sensor Hub       │
 │ /chat   HUD      │           │   │  ├── Local LLM (MLX)   │   │◄──►│ Weather Station  │
 │ /settings Config │           │   │  └── Self-Learner       │   │    │ Air Quality      │
 └──────────────────┘           │   └─────────────────────────┘   │    └──────────────────┘
                                │                                 │
 ┌──────────────────┐           │   ┌─────────────────────────┐   │
 │ App Integrations │           │   │  Security Layer         │   │
 │ Spotify OAuth2   │  ←HTTP→   │   │  ├── Blind Vault        │   │
 │ Home Assistant   │──────────►│   │  ├── WASM Sandbox       │   │
 │ Notion OAuth2    │           │   │  ├── Permission Tiers   │   │
 │ MCP Servers      │           │   │  └── Audit Trail        │   │
 └──────────────────┘           │   └─────────────────────────┘   │
                                │                                 │
                                │   CLI:    theora start|status   │
                                └─────────────────────────────────┘
```

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/Spatial-AgenticOS/ASOS.git
cd ASOS
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY
```

### 2. Run with Docker (recommended)

```bash
docker compose up -d
# Brain: http://localhost:9090
# Client: http://localhost:3000
```

### 3. Or Run Natively

```bash
# Brain
cd asos-core
pip install -e ".[all]"
PYTHONPATH=. python api/server.py

# Client (in a separate terminal)
cd asos-client
npm install && npm run dev -- --host 0.0.0.0
# Client: http://localhost:5173 (dev mode)
```

### 4. CLI

```bash
cd asos-core
pip install -e .
theora                          # interactive REPL
theora "search the web for AI"  # one-shot
theora status                   # system health
theora devices                  # connected hardware
theora skills                   # loaded skills
```

## Core Capabilities

### Intelligence
- **Multi-Agent Collaboration** — Router-worker architecture dispatches to specialist agents (Health, Home, Research, Creative) with parallel fan-out
- **On-Device LLM** — MLX (Apple Silicon) and llama.cpp (Linux/x86) inference
- **LLM Orchestration** — OpenAI, Ollama, Groq, or any OpenAI-compatible provider
- **Streaming Responses** — Real-time token streaming to all clients
- **Context-Aware Reasoning** — Fuses sensor data + memory + perception into every LLM call
- **Proactive Mode** — Agent acts on context changes without being asked

### Voice & Audio
- **Real-Time Voice** — OpenAI Realtime API proxy with tool interception
- **Wake Word** — "Hey THEORA" detection using openwakeword (with energy-based fallback)
- **Dual-Path Audio** — Phone/glasses use Realtime API, web/channels use Whisper+TTS

### Self-Evolving Skills
- **Live Skill Generation** — Agent detects unmet needs and proposes new skill manifests
- **Skill Marketplace** — Search, install, update community skills
- **User Approval Flow** — Approve/reject proposed skills before registration
- **WASM Plugin Sandboxing** — Run untrusted skills in wasmtime with memory/CPU limits

### Memory (4 Tiers + Federated Sync)

| Tier | What | Persistence |
|---|---|---|
| **Working** | Current conversation context | Session |
| **Notes** | Facts, preferences, observations | Permanent |
| **Episodes** | Significant interactions | Permanent |
| **Knowledge** | Subject-predicate-object triples | Graph |

- **Federated Memory** — CRDT-based P2P sync across devices via mDNS
- **Manual Sync** — Export/import memory bundles for offline transfer

### Perception Fusion
- **Vision** — Event-driven VLM analysis (GPT-4o, Gemini, Ollama) triggered by change detection
- **Audio** — Speech-to-text, ambient sound analysis
- **Biometrics** — Heart rate, SpO2, temperature, UV, steps
- **Gestures** — Nod, shake, double-tap from glasses IMU
- **Location** — GPS coordinates

### App Integrations
- **Spotify** — OAuth2 PKCE, playback control, search, playlists
- **Home Assistant** — Entity discovery, service calls, automation triggers
- **Notion** — Page search/create/update, database queries
- **Webhook Receiver** — HMAC-verified incoming events from any app
- **MCP Ecosystem** — Connect any MCP server (GitHub, filesystem, databases)

### Security
- **Blind Vault** — Credentials stored with `chmod 600`, LLM never sees raw keys
- **Permission Tiers** — Passive → Active → Privileged → Dangerous
- **WASM Sandboxing** — Memory/CPU/network limits for untrusted skill code
- **Sandbox Policies** — Declarative YAML policies for hardware + software
- **Node Authentication** — `NODE_API_KEY` required for all daemon WebSocket connections

### Hardware Use Protocol (HUP)

Like "computer use" made screens controllable, **HUP makes any hardware controllable**:

```
Agent → HUP Action → Sandbox Policy Check → Permission Tier → Device Adapter → Physical Hardware → Result
```

Devices self-describe via declarative manifests. The agent reads the manifest and figures out how to use the device.

### MCP Integration (Server + Client)

**THEORA is an MCP server** — any MCP client can control your hardware:

```bash
# In Claude Desktop config (run from asos-core, or pip install -e . first):
{ "mcpServers": { "theora": { "command": "python", "args": ["-m", "mcp.server"], "cwd": "/path/to/ASOS/asos-core" } } }
```

**THEORA is also an MCP client** — connect external MCP servers:

```json
// ~/.theora/mcp_servers.json
{ "servers": [{ "name": "github", "transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"] }] }
```

MCP tools are automatically discovered and merged into the agent's tool list.

### Channels

| Channel | Status | Capabilities |
|---|---|---|
| Telegram | Ready | Text, buttons, skill approval |
| Discord | Ready | Text, embeds |
| Slack | Ready | Text, blocks, buttons |
| WebChat | Built-in | Full SDUI + streaming |
| iOS | Bridge SDK | Full hardware + sensor data |

## Creating Custom Skills

Drop a JSON manifest in `~/.theora/skills/` or `asos-core/skills/manifests/`:

```json
{
  "skill_id": "my_custom_api",
  "brand": { "name": "My API", "primary_color": "#6c5ce7" },
  "description": "What this skill does — the LLM reads this to decide when to use it",
  "trigger_phrases": ["check my api", "get data from my service"],
  "auth": { "type": "api_key", "api_key_header": "X-API-Key" },
  "endpoints": [
    {
      "id": "get_data",
      "method": "GET",
      "url": "https://api.example.com/v1/data",
      "description": "Fetches data from the service",
      "params": [
        { "name": "query", "type": "string", "description": "Search query", "required": true }
      ]
    }
  ]
}
```

Or let the agent create them for you — just ask for a capability it doesn't have.

## Creating Hardware Daemons

```python
# my_sensor.py — minimal daemon template
import asyncio, json, websockets, os

async def main():
    api_key = os.environ.get("NODE_API_KEY", "dev-secret-key")
    uri = f"ws://localhost:9090/v1/node?api_key={api_key}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "hop": "daemon", "type": "node_register",
            "payload": {
                "node_id": "my-sensor",
                "node_type": "sensor",
                "capabilities": ["temperature", "humidity"],
            }
        }))
        while True:
            await ws.send(json.dumps({
                "hop": "daemon", "type": "telemetry",
                "payload": {
                    "node_id": "my-sensor",
                    "sensors": {"temperature_c": 22.5, "humidity_pct": 45},
                }
            }))
            await asyncio.sleep(5)

asyncio.run(main())
```

## Project Structure

```
ASOS/
├── asos-core/                 # The Brain
│   ├── api/server.py          # FastAPI + WebSocket hub
│   ├── agents/                # Orchestrator, Multi-Agent, Learner, Skill Generator
│   ├── memory/                # 4-tier memory store + federated sync
│   ├── perception/            # Multimodal fusion engine
│   ├── security/              # Blind Vault, Tiers, WASM Sandbox, Policies
│   ├── hardware/              # HUP — Hardware Use Protocol
│   ├── mcp/                   # MCP Server + Client
│   ├── channels/              # Telegram, Discord, Slack bridges
│   ├── skills/                # Registry, Executor, Marketplace, Manifests
│   ├── voice/                 # VoiceRouter, RealtimeProxy, WakeWord
│   ├── integrations/          # OAuth, Spotify, Home Assistant, Notion
│   ├── cli/                   # Terminal REPL + commands
│   ├── config/                # Layered configuration system
│   ├── models/                # Protocol definitions
│   └── tests/                 # 174+ tests
├── asos-client/               # React + Vite + Tailwind
│   └── src/
│       ├── pages/             # SetupWizard, Dashboard, Settings
│       └── components/        # AppShell, SDUI renderer
├── asos-nodes/
│   ├── python-node-sdk/       # Desktop + glasses + robot daemons
│   ├── ios-bridge/            # Swift: ASOSBrainClient + SensorBridge
│   └── android-bridge/        # Kotlin: WebSocket, Health Connect, audio
├── scripts/                   # install.sh, demo.sh
├── docker-compose.yml
└── .env.example
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | LLM API key (required for full agent mode) | — |
| `NODE_API_KEY` | Auth for daemon WebSocket connections | `dev-secret-key` |
| `THEORA_LLM_PROVIDER` | `openai`, `ollama`, or `groq` | `openai` |
| `THEORA_LLM_MODEL` | Model name | `gpt-4o-mini` |
| `THEORA_STREAMING` | Enable streaming responses | `true` |
| `THEORA_WAKE_WORD` | Enable wake word detection | `true` |
| `THEORA_MAX_TIER` | Max permission tier | `active` |
| `THEORA_SCENE_COOLDOWN` | Seconds between VLM analyses | `10` |
| `THEORA_KEY_*` | Skill-specific API keys (blind vault) | — |

## Roadmap

- [ ] Deploy `registry.theora.io` for community skill publishing
- [ ] Build production Android app using the bridge SDK
- [ ] Train dedicated "Hey THEORA" openwakeword model
- [ ] End-to-end federated sync testing across Mac + iPhone + Android
- [ ] WASM skill starter templates (Rust, Go, AssemblyScript)
- [ ] Desktop GUI app (Tauri/Electron) for non-developer users

## Contact

**Alpay Kasal** — info@theora.io

For commercial licensing, partnerships, enterprise inquiries, or press.

## License

Apache 2.0 with attribution requirement — see [NOTICE](NOTICE).

You are free to use, modify, and distribute THEORA. All derivative works must include:

> Built with THEORA (https://github.com/Spatial-AgenticOS/ASOS)

Copyright 2024-2026 THEORA, Inc. Created by Mahmoud Omar and Alpay Kasal.
