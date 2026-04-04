# THEORA — The Universal Agentic Operating System

> **Not just computer use. Anything use.**

THEORA is a local-first, self-evolving agentic OS that connects any device — smart glasses, phones, robots, sensors, computers — into a unified intelligence layer. It sees, hears, feels, remembers, learns, creates its own tools, and asks permission before acting.

No cloud dependency. No vendor lock-in. Your data stays on your machine.

## What Makes THEORA Different

| Feature | OpenClaw | NemoClaw (NVIDIA) | **THEORA** |
|---|---|---|---|
| **Scope** | Computer + browser use | Sandboxed computer use | **Any device, any sensor, any actuator** |
| **Skills** | Static tools + SKILL.md | Inherited from OpenClaw | **Self-generating — agent creates its own tools** |
| **Memory** | Session workspace | Session workspace | **4-tier persistent (working → notes → episodes → knowledge graph)** |
| **Security** | Gateway auth | Landlock/seccomp sandbox | **Blind Vault + declarative YAML policies for hardware + software** |
| **Hardware** | None | GPU deployment targets | **Smart glasses, phones, robots, IoT — all first-class HUP nodes** |
| **MCP** | Client only (mcporter) | None | **Server AND Client — THEORA IS an MCP server** |
| **Perception** | Screen/browser only | Screen only | **Fused: vision + audio + biometrics + location + gestures** |
| **UI** | WebChat / channels | CLI | **SDUI — agent generates interfaces + Setup Wizard + Dashboard** |
| **Learning** | None | None | **Self-learning agent improves from every interaction** |
| **Permissions** | Gateway token | YAML network policies | **4-tier graduated model + hardware-aware sandbox policies** |
| **Channels** | Telegram, Discord, Slack | Telegram, Discord, Slack | **All of those + hardware channels (glasses, robot, sensors)** |
| **Architecture** | Gateway monolith | Container sandbox | **Distributed Brain + N edge nodes via authenticated WebSocket** |

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
 ┌──────────────────┐           │   ┌─────────────────────────┐   │    ┌──────────────────┐
 │ App Integrations │           │   │  Security Layer         │   │    │ Marketplace      │
 │ Spotify OAuth2   │  ←HTTP→   │   │  ├── Blind Vault        │   │    │ Community Skills │
 │ Home Assistant   │──────────►│   │  ├── WASM Sandbox       │   │◄──►│ WASM Plugins     │
 │ Notion OAuth2    │           │   │  ├── Permission Tiers   │   │    │ Install/Publish  │
 │ MCP Servers      │           │   │  └── Audit Trail        │   │    └──────────────────┘
 └──────────────────┘           │   └─────────────────────────┘   │
                                │                                 │
                                │   Config: Layered + XDG         │
                                │   System: systemd / launchd     │
                                │   CLI:    theora start|stop|... │
                                └─────────────────────────────────┘
```

## Core Capabilities

### Intelligence
- **Multi-Agent Collaboration** — Router-worker architecture dispatches to specialist agents (Health, Home, Research, Creative) with parallel fan-out for complex queries
- **On-Device LLM** — MLX (Apple Silicon) and llama.cpp (Linux/x86) inference, zero cloud dependency. Hybrid mode: local for routing, cloud for reasoning
- **LLM Orchestration** — OpenAI, Ollama, Groq, or any OpenAI-compatible provider
- **Streaming Responses** — Real-time token streaming to all clients
- **Context-Aware Reasoning** — Fuses sensor data + memory + perception into every LLM call
- **Proactive Mode** — Agent acts on context changes without being asked

### Voice & Audio
- **Real-Time Voice** — OpenAI Realtime API proxy with tool interception. Brain intercepts function calls, executes them, returns results — phone never talks to OpenAI directly
- **Wake Word** — "Hey THEORA" detection using openwakeword ML model. States: LISTENING → ACTIVATED → TIMEOUT with 500ms pre-roll capture
- **Dual-Path Audio** — Phone/glasses use Realtime API (low latency), web/channels use Whisper+TTS pipeline

### Self-Evolving Skills
- **Live Skill Generation** — Agent detects unmet needs and proposes new skill manifests
- **Skill Marketplace** — Search, install, update, and uninstall community skills. Security validation prevents malicious code
- **User Approval Flow** — Approve/reject/edit proposed skills before registration
- **Hot Registration** — Skills activate immediately, no restart needed
- **WASM Plugin Sandboxing** — Run untrusted skills in wasmtime with memory/CPU limits and audited host functions
- **Developer SDK** — Write skills in Python, JSON manifests, or Rust/Go/C compiled to WASM

### Memory (4 Tiers + Federated Sync)
| Tier | What | Persistence |
|---|---|---|
| **Working** | Current conversation context | Session |
| **Notes** | Facts, preferences, observations | Permanent |
| **Episodes** | Significant interactions | Permanent |
| **Knowledge** | Subject-predicate-object triples | Graph |

- **Federated Memory** — CRDT-based P2P sync across devices via mDNS. Hybrid Logical Clocks for causal ordering. No cloud — all sync on local network
- **Manual Sync** — Export/import memory bundles for offline transfer (USB, AirDrop)

### Perception Fusion
- **Vision** — Event-driven VLM analysis (GPT-4o, Gemini, Ollama) triggered by change detection, not fixed cooldowns
- **Audio** — Speech-to-text, speaker identification, ambient sound analysis
- **Biometrics** — Heart rate, SpO2, temperature, UV exposure, step count
- **Gestures** — Nod, shake, double-tap, look-up/down from glasses IMU
- **Location** — GPS coordinates, altitude, speed
- **Environment** — Ambient light, noise level

### App Integrations
- **Spotify** — OAuth2 PKCE, playback control, search, playlists
- **Home Assistant** — Entity discovery, service calls, automation triggers
- **Notion** — Page search/create/update, database queries
- **Webhook Receiver** — HMAC-verified incoming events from any app
- **MCP Ecosystem** — Connect GitHub, Slack, filesystem, browser MCP servers

### Security
- **Blind Vault** — Credentials stored with `chmod 600`, LLM never sees raw keys
- **Permission Tiers** — Passive (read-only) → Active (send data) → Privileged (modify system) → Dangerous (destructive)
- **WASM Sandboxing** — Memory/CPU/network limits for untrusted skill code. Host function ABI is the only bridge
- **Execution Sandbox** — Rate limiting, domain blocking, tier enforcement
- **Audit Trail** — Every credential access and privileged action logged to `~/.theora/audit.log`
- **Node Authentication** — `NODE_API_KEY` required for all WebSocket daemon connections

### Hardware Use Protocol (HUP)

Like "computer use" made screens controllable, **HUP makes any hardware controllable**:

```
Agent → HUP Action → Sandbox Policy Check → Permission Tier → Device Adapter → Physical Hardware → Result
```

Devices self-describe via declarative manifests. The agent doesn't need device-specific code — it reads the manifest and figures out how to use the device.

| Node Type | Connection | Capabilities |
|---|---|---|
| **THEORA Glasses** | BLE → iPhone → WS → Brain | HR, SpO2, Temp, UV, Steps, Camera, Display, Speaker |
| **iPhone** | WebSocket | BLE bridge, camera, microphone, GPS, gyro, wake word |
| **Android** | WebSocket | Health Connect, camera, microphone, GPS, wake word |
| **Desktop** | WebSocket | AppleScript, keyboard, shell, filesystem |
| **Robot** | WebSocket | Movement, GPIO, serial, camera |
| **Sensor Hub** | WebSocket | Any I2C/SPI/GPIO sensor |
| **Any Device** | WebSocket/BLE/MQTT/HTTP | Whatever capabilities it declares |

### MCP Integration (Server + Client)

**THEORA is an MCP server** — any MCP client can control your hardware:

```bash
# In Claude Desktop config:
{ "mcpServers": { "theora": { "command": "python", "args": ["-m", "mcp.server"] } } }
```

Now Claude can read your heart rate, control your robot, query your memory.

**THEORA is also an MCP client** — connect external MCP servers:

```json
// ~/.theora/mcp_servers.json
{ "servers": [{ "name": "github", "transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"] }] }
```

### Sandbox Policies (NemoClaw-style, extended for hardware)

Declarative YAML policies govern everything — network, filesystem, sensors, actuators, cameras, movement:

```yaml
hardware:
  sensors:
    allowed: [heart_rate, spo2, temperature]
    max_read_rate_per_second:
      heart_rate: 1
  actuators:
    requires_confirmation: [motor, servo, relay]
  movement:
    max_speed_pct: 50
    emergency_stop_enabled: true
```

### Channels

Messaging bridges (like OpenClaw) — but with hardware data flowing through them:

| Channel | Status | Capabilities |
|---|---|---|
| Telegram | Ready | Text, buttons, skill approval |
| Discord | Ready | Text, embeds |
| Slack | Ready | Text, blocks, buttons |
| WebChat | Built-in | Full SDUI + streaming |
| iOS | Bridge SDK | Full hardware + sensor data |

### Client UI
- **Setup Wizard** — 6-step guided onboarding (LLM provider, API keys, features, skills)
- **Dashboard** — Live system status, memory metrics, security overview, skill proposals
- **Chat HUD** — Streaming LLM responses with SDUI rendering
- **Settings** — Full configuration management
- **14 SDUI Components** — Agent can generate dynamic UI at runtime

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/Spatial-AgenticOS/ASOS.git
cd ASOS
cp .env.example .env
# Edit .env with your API keys
```

### 2. Run with Docker

```bash
docker compose up -d
# Brain: http://localhost:9090
# Client: http://localhost:5173
```

### 3. Or Run Natively

```bash
# Brain
cd asos-core
pip install -r requirements.txt
python -m uvicorn api.server:app --host 0.0.0.0 --port 9090

# Client
cd asos-client
npm install && npm run dev -- --host 0.0.0.0
```

### 4. Install as System Service

```bash
bash scripts/install.sh
theora start
theora status
```

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
import asyncio, json, websockets

async def main():
    uri = "ws://localhost:9090/v1/node?api_key=YOUR_KEY"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "hop": "node", "type": "register",
            "payload": {
                "node_id": "my-sensor",
                "node_type": "sensor",
                "capabilities": ["temperature", "humidity"],
            }
        }))
        while True:
            await ws.send(json.dumps({
                "hop": "node", "type": "sensor_telemetry",
                "payload": {
                    "node_id": "my-sensor",
                    "sensor": "temperature",
                    "data": {"celsius": 22.5}
                }
            }))
            await asyncio.sleep(5)

asyncio.run(main())
```

## iOS Integration (THEORA Glasses → Phone → Brain)

The `asos-nodes/ios-bridge/` contains Swift classes that replace the direct OpenAI connection:

```swift
let client = ASOSBrainClient(host: "192.168.1.100", port: 9090)
client.connect(apiKey: "your-node-api-key")

let bridge = TheoraSensorBridge(brainClient: client)
bridge.startContinuousMonitoring() // HR, SpO2, Temp, UV, Steps → Brain
```

The phone becomes a full edge node: BLE bridge to glasses, camera/mic provider, and GPS source.

## Project Structure

```
ASOS/
├── asos-core/                 # The Brain
│   ├── api/server.py          # FastAPI + WebSocket hub
│   ├── agents/                # Orchestrator, Learner, Skill Generator
│   ├── memory/                # 4-tier memory store
│   ├── perception/            # Multimodal fusion engine
│   ├── security/              # Blind Vault, Tiers, Sandbox Policies
│   ├── hardware/              # HUP — Hardware Use Protocol
│   ├── mcp/                   # MCP Server + Client
│   ├── channels/              # Telegram, Discord, Slack bridges
│   ├── skills/                # Registry, Executor, JSON manifests
│   ├── config/                # Layered configuration system
│   ├── models/                # Protocol definitions
│   └── tests/                 # 174+ tests
├── asos-client/               # React + Vite + Tailwind
│   └── src/
│       ├── pages/             # SetupWizard, Dashboard, Settings
│       └── components/        # AppShell, SDUI renderers
├── asos-nodes/
│   ├── python-node-sdk/       # Desktop + glasses + robot daemons
│   └── ios-bridge/            # Swift: ASOSBrainClient + SensorBridge
├── scripts/                   # install.sh, CLI
├── docker-compose.yml
└── .env.example
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | LLM API key | — |
| `NODE_API_KEY` | Auth for daemon WebSocket connections | `theora-dev-key` |
| `THEORA_LLM_PROVIDER` | `openai` or `ollama` | `openai` |
| `THEORA_MODEL` | Model name | `gpt-4o` |
| `THEORA_STREAMING` | Enable streaming responses | `true` |
| `THEORA_MAX_TIER` | Max permission tier | `active` |
| `THEORA_SCENE_COOLDOWN` | Seconds between VLM analyses | `10` |
| `THEORA_KEY_*` | Skill-specific API keys | — |

## Completed (v0.9)

- [x] Multi-agent collaboration (router-worker architecture with 4 specialist agents)
- [x] Skill marketplace (search, install, validate, uninstall community skills)
- [x] Android bridge SDK (Kotlin — WebSocket, Health Connect, audio, wake word)
- [x] Voice wake word ("Hey THEORA" via openwakeword)
- [x] On-device LLM inference (MLX on Apple Silicon, llama.cpp cross-platform)
- [x] Federated memory (CRDT sync via mDNS, Hybrid Logical Clocks)
- [x] Plugin sandboxing via WebAssembly (wasmtime, host function ABI)

## Roadmap

- [ ] Deploy `registry.theora.io` for community skill publishing
- [ ] Build production Android app using the bridge SDK
- [ ] Train dedicated "Hey THEORA" openwakeword model
- [ ] End-to-end federated sync testing across Mac + iPhone + Android
- [ ] WASM skill starter templates (Rust, Go, AssemblyScript)
- [ ] CI/CD pipeline — GitHub Actions, pytest-cov, coverage badge
- [ ] Desktop GUI app (Tauri/Electron) for non-developer users

## Contact

**Alpay Kasal** — info@theora.io

For commercial licensing, partnerships, enterprise inquiries, or press.

## License

Apache 2.0 with attribution requirement — see [NOTICE](NOTICE).

You are free to use, modify, and distribute THEORA. All derivative works must include:

> Built with THEORA (https://github.com/Spatial-AgenticOS/ASOS)

Copyright 2024-2026 THEORA, Inc. Created by Mahmoud Omar and Alpay Kasal.
