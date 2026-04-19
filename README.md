<p align="center">
  <img src="feral-banner.png" width="640" alt="FERAL — Unleashed AI" />
</p>

<h3 align="center">One brain. Every device. Your entire life.</h3>
<p align="center"><em>The open-source AI that connects to everything you own — wristband, glasses, home, computer, phone, robots — learns your baseline, and runs things the way you would. Locally. Privately. No cloud.</em></p>

<p align="center">
  <a href="#the-idea">The Idea</a> &nbsp;·&nbsp;
  <a href="#what-it-does">What It Does</a> &nbsp;·&nbsp;
  <a href="#get-started">Get Started</a> &nbsp;·&nbsp;
  <a href="#demos">Demos</a> &nbsp;·&nbsp;
  <a href="#architecture">Architecture</a> &nbsp;·&nbsp;
  <a href="#meet-the-mascot">Mascot</a> &nbsp;·&nbsp;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2026.4.14-06b6d4?style=flat-square" alt="Version" />
  <a href="https://github.com/FERAL-AI/FERAL-AI/stargazers"><img src="https://img.shields.io/github/stars/FERAL-AI/FERAL-AI?style=flat-square&color=06b6d4" alt="Stars" /></a>
  <a href="https://github.com/FERAL-AI/FERAL-AI/commits/main"><img src="https://img.shields.io/github/last-commit/FERAL-AI/FERAL-AI?style=flat-square&color=06b6d4" alt="Last Commit" /></a>
  <img src="https://img.shields.io/badge/license-Apache%202.0-06b6d4?style=flat-square" alt="License" />
  <img src="https://img.shields.io/badge/python-3.11+-06b6d4?style=flat-square" alt="Python" />
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20iOS%20%7C%20Android-06b6d4?style=flat-square" alt="Platform" />
</p>

---

> **OpenAI built a chatbot. Apple built Siri. Google built an ad machine. Meta open-sourced some weights and called it a day.**
>
> None of them built an AI that connects to your wristband, your smart glasses, your thermostat, your robot arm, your computer, and your phone — learns your routines, builds your baseline, and proactively manages your physical and digital world. All locally. All privately.
>
> **We did.** And we open-sourced all of it.

---

## Feature Maturity

> **Stable** means all 5 criteria are met: ≥1 integration test, structured logging (`feral.{subsystem}.{name}`), documented env vars + settings, graceful error handling, and a troubleshooting guide in `docs/mintlify/`. **1344 tests pass** on every commit. See [docs/mintlify/guides/](docs/mintlify/guides/) for per-feature troubleshooting.

| Feature | Status | Details |
|---------|--------|---------|
| **Chat + LLM Orchestration** | Stable | 10 providers, failover, streaming, tool calling |
| **Memory (4-tier + P2P sync)** | Stable | Notes, episodic, knowledge graph, CRDT sync |
| **Skills + Tool Execution** | Stable | 19 skills, multi-runtime executor, blind vault |
| **CLI + Setup Wizard** | Stable | `feral start/serve/doctor/setup`, interactive wizard with key validation |
| **Web Dashboard** | Stable | Chat, SDUI, settings, dashboard, timeline |
| **Ambient** | Stable | 3 modes (Briefing/Desk/Wind-Down), somatic wallpaper, wake-word, auto-switch |
| **Glass Brain Visualization** | Stable | Three.js, real-time cognition, channel/device/voice satellites, click-to-inspect |
| **Security + Autonomy** | Stable | Safety classification, approval gates, Docker sandbox, auto-generated API key |
| **Voice (OpenAI/Gemini/Local)** | Stable | Realtime proxies, wake word, push-to-talk, reconnect, per-chunk latency logs |
| **Browser Automation** | Stable | CDP + Playwright, cookies, network interception, iframes |
| **GUI Computer Use** | Stable | Anthropic-style, Retina DPI (2x/3x), rate-limited (10/s default), cross-platform |
| **PDF Intelligence** | Stable | Tables, images, OCR, metadata, layout preservation, MAX_PAGES guard |
| **Search (7 providers)** | Stable | Tavily, Brave, DDG, Exa, SearXNG, Perplexity, Google CSE; provider_used tracking |
| **Channels (Telegram/Discord/Slack/WhatsApp)** | Stable | Bidirectional, webhook support, rate-limit-aware retry (429/503) |
| **Cron + Scheduling** | Stable | NL parsing, timezone, priorities, cron macros, missed-job catch-up, file-locked DB |
| **Proactive Engine** | Stable | Health alerts, smart home automation, LLM-hybrid, per-trigger counters |
| **Smart Home (Hue + HA)** | Stable | Real Philips Hue API (meethue.com + mDNS fallback), HA REST/Supervisor |
| **Browser Extension** | Stable | Chrome/Firefox, page context, chat sidebar, voice, configurable brain URL + auth |
| **MQTT Bridge** | Stable | TLS + mTLS, username/password, persistent client, IoT auto-discovery |
| **Home Assistant Add-on** | Stable | Pinned base image, CI build, UPGRADE.md, 2000+ device types |
| **Desktop Tray App** | Stable | Tauri, per-OS CI (mac/linux/win), first-run setup wizard, global hotkey |
| **Webhook Receiver** | Stable | CRUD API, HMAC verification, action mapping |
| **Email Watcher** | Stable | IMAP IDLE + XOAUTH2, polling fallback, VIP filtering, MIME parser |
| **iOS App** | Stable | HealthKit, QR pairing, TLS pinning (FERAL_BRAIN_CERT_HASH), XCTest suite |
| **Android App** | Stable | Health Connect, QR pairing, foreground service, Espresso tests |
| **Hardware Mesh (HUP)** | Stable | Typed devices, command contract, BLE, W300 glasses, approval gate soak-tested |
| **Somatic Context Layer** | Stable | 12D body vector, cognitive load, behavioral policies, privacy-audited logs |
| **Tool Genesis** | Stable | AST import allowlist, requires_approval gate, Docker sandbox execution |
| **Agent Mitosis** | Stable | Self-spawning specialists, orchestrator routing, satisfaction feedback |
| **Intent Compiler** | Stable | Goal → actions with skill validation, timezone-aware today(), JSON-parse fallback |
| **Digital Twin** | Stable | Ask-as-user, predict preferences, daily reflection, ethical bounds documented |
| **A2UI Protocol** | Stable | Versioned (v1.0) wire format, cross-client contract tests, schema doc |
| **Federated Memory Sync** | Stable | CRDT + HLC, mTLS, mDNS + static peer fallback, 100-op fuzz tests |
| **Observability** | Stable | OpenTelemetry + Prometheus `/metrics`, per-subsystem counters + latency histograms |
| **Video Generation** | Planned | — |
| **Music Generation** | Planned | — |
| **Native macOS App** | Planned | — |

---

## The Idea

FERAL is **one local brain for every device you own**. It connects to your wristband, your smart glasses, your home, your computer, your phone, your robots — every device, every app, every sensor. It learns your daily baseline across all of them. And it proactively manages hardware, software, health data, and your environment through natural language and intent.

```mermaid
flowchart TD
    CAL["Calendar\nEmail\nSlack\nSpotify\nNotion"] --- BRAIN
    HEALTH["Whoop\nOura Ring\nWristband\nHR · SpO2 · Sleep"] --- BRAIN
    HOME["Smart Lights\nThermostat\nAppliances\nLocks"] --- BRAIN
    GLASSES["Smart Glasses\nVideo Stream\nAR Overlay"] --- BRAIN
    BRAIN["FERAL Brain\n---\nMemory · Identity\nAutonomy · Voice\nProactive Intelligence"]
    BRAIN --- COMPUTER["Your Computer\nScreen · Browser\nFiles · Terminal"]
    BRAIN --- PHONE["Your Phone\nQR Pairing · Location\nCamera · TLS"]
    BRAIN --- ROBOTS["Robots\nROS · Serial\nI2C · Actuators"]
    BRAIN --- VOICE["Voice\nWake Word\n3 Providers · PTT\nSub-200ms"]
```

It talks to **every device** — wristbands, smart glasses, home appliances, robots, your computer, your phone. It integrates with **every app** — calendar, email, Telegram, Slack, Spotify, Notion. It builds a **living model** of your routines and health through persistent memory. And it acts based on the **level of autonomy you choose**:

| Mode | Behavior |
|------|----------|
| **Strict** | Every action requires your explicit approval via a confirmation card |
| **Hybrid** | Safe actions auto-execute; risky ones ask first |
| **Loose** | Full autopilot — FERAL acts, you review the log |

---

## What It Does

<table>
<tr>
<td width="50%" valign="top">

### 🧠 Persistent Memory
Episodic recall, knowledge graph, semantic search, notes wiki. Four memory tiers that remember your entire life — not just the current session.

### 🎙️ Sub-200ms Voice
Wake word detection, OpenAI Realtime + Gemini Live streaming, interrupt-and-resume. Push-to-talk and toggle modes. Provider selection in Settings. Auto-reconnection with exponential backoff.

### 🏠 Hardware Mesh
Direct Bluetooth/local control of lights, sensors, wristbands, smart glasses, robots. No cloud roundtrip. 12+ device types.

### 💊 Live Health Data
Heart rate, SpO2, skin temp from your wristband in real-time. Whoop and Oura Ring integration. Sleep and recovery trends.

</td>
<td width="50%" valign="top">

### 🤖 Proactive Intelligence
FERAL doesn't wait for commands. It watches ambient context — screen, health, calendar — and speaks up when it has something valuable to say.

### 🖥️ Computer Use
Anthropic-style GUI control (screenshot, click, type, scroll, window management) with Retina DPI auto-detection. Coding tools for file and shell operations. Browser automation with session persistence, network monitoring, and iframe support.

### 🎨 Server-Driven UI (GenUI)
The brain generates UI dynamically — charts, forms, cards, alerts — and pushes them to whatever screen you're looking at.

### 🪞 Digital Twin
"What would I think about this?" — FERAL builds a model of your preferences, decisions, and reasoning from your history. Ask your digital twin anything.

</td>
</tr>
</table>

<table>
<tr>
<td width="50%" valign="top">

### 📅 Calendar + Email + Messaging
Google Calendar, Gmail, Telegram, Slack, Discord — all integrated. Morning briefings that are real, not simulated.

### 🔒 Three Autonomy Levels
Strict, hybrid, or loose. Real enforcement via ApprovalManager + safety classification. Not just a config flag.

</td>
<td width="50%" valign="top">

### 📍 Location-Aware Triggers
GPS geofencing: "When I arrive at the office, brief me on my day." Enter/exit detection with configurable actions.

### 🌙 Ambient Mode
Always-on full-screen dashboard — next meeting, heart rate, active tasks, weather, last memory. Your AI life at a glance.

</td>
</tr>
</table>

<table>
<tr>
<td width="50%" valign="top">

### 🔍 Search (7 Providers)
Tavily, Brave, DuckDuckGo, Exa, SearXNG, Perplexity, Google CSE — with automatic failover, 5-minute result caching, and cross-provider deduplication.

### 📄 PDF Intelligence
Table extraction, image extraction with base64, OCR fallback, metadata parsing, and layout-preserving structured extraction. Reads any PDF, not just text-based ones.

</td>
<td width="50%" valign="top">

### 📱 Mobile Bridges (iOS + Android)
QR code pairing for instant setup. GPS location forwarding to the brain. TLS (wss://) transport. iOS offline sensor queue. Android camera capture via CameraX. Wake word detection on-device.

### 🧪 Code Interpreter
Docker-first sandboxed execution: --network=none, --memory=512m, --cpus=1, --read-only. Falls back to host with resource limits when Docker is unavailable.

</td>
</tr>
</table>

### Universal Connectivity

| Surface | What It Does |
|---------|-------------|
| **Browser Extension** | FERAL in your browser — reads pages, chat sidebar, right-click actions, voice |
| **MQTT Bridge** | Connect to any IoT device — smart plugs, sensors, ESP32, Zigbee2MQTT |
| **Home Assistant** | Run as HA add-on — instant access to 2000+ device types |
| **Desktop Tray** | Always-on access — Cmd+Shift+F for Spotlight-style commands |
| **Webhooks** | Any service can trigger FERAL — GitHub, Stripe, IFTTT, Zapier |
| **Email Watcher** | FERAL monitors your inbox — summarize, reply, extract action items |
| **iOS App** | HealthKit relay, chat, voice, camera, QR pairing |
| **Android App** | Health Connect relay, chat, voice, camera, foreground service |

---

## Comparison

Every claim below links to the file that implements it, so you can read
the code instead of our marketing copy.

### FERAL vs peer agent frameworks

Both FERAL and its closest peers are local-first, plugin-driven AI
agents. This table goes deep on the dimensions that actually matter if
you are picking one.

| Dimension | Other local-first agent frameworks | **FERAL (shipped, verifiable)** |
|---|---|---|
| Language + stack | Node.js + TypeScript, npm-distributed | Python 3.11 + FastAPI + React/Vite; PyPI wheel ([`feral-core/pyproject.toml`](feral-core/pyproject.toml)) |
| Plugin catalog | 100+ bundled extensions + community npm packages | 24 first-party skills + an 8-category registry (`skill`, `daemon`, `mcp`, `channel`, `provider`, `memory`, `workflow`, `agent`) at [registry.feral.sh](https://registry.feral.sh) ([`feral-registry/feral_registry/schemas.py`](feral-registry/feral_registry/schemas.py)) |
| Distribution trust | Package-name trust + manual review | Ed25519-signed bundles, GitHub OAuth-verified publishers, `verified` badge allowlist ([`feral-registry/feral_registry/signing.py`](feral-registry/feral_registry/signing.py)) |
| **Dynamic skill creation at runtime** | Manual — publish a package | **Tool Genesis: draft → AST-gate → Docker sandbox → auto-promote → hot-reload, all in one turn** ([`feral-core/agents/tool_genesis.py`](feral-core/agents/tool_genesis.py) + [`orchestrator.py::_on_capability_gap`](feral-core/agents/orchestrator.py)) |
| Never-say-no fallback | Shell `exec` tool | `workspace_scripts` skill with reusable catalog + Docker sandbox + persistence ([`feral-core/skills/impl/workspace_scripts.py`](feral-core/skills/impl/workspace_scripts.py)) |
| Computer use | Browser (Playwright) + desktop | Browser (Playwright/CDP) + desktop (`pyautogui`) + workspace scripts ([`feral-core/skills/impl/`](feral-core/skills/impl/)) |
| Hardware-aware perception | Generic remote machines | **HUP v1.0.0 public wire spec + Python + TS SDKs + cookiecutter daemon template** ([`feral-nodes/HUP_SPEC.md`](feral-nodes/HUP_SPEC.md)), plus BLE wristband + HomeKit + Matter bridges |
| Memory | Plugin-slot (one active at a time) | **4-tier (working + episodic + semantic + execution) + knowledge graph + CRDT P2P sync + sqlite-vec hybrid with numpy fallback** ([`feral-core/memory/`](feral-core/memory/)) |
| Voice | Extension-based, provider-specific | **Sub-200 ms, 3 providers with auto-failover: OpenAI Realtime, Gemini Live, local Whisper+Piper** ([`feral-core/voice/`](feral-core/voice/)) |
| Generative UI | Canvas + A2UI | Full SDUI engine rendering on iOS+Android+Web from one server spec ([`feral-core/genui/`](feral-core/genui/)) |
| Observability | Session logs | **Live Glass Brain WebGL view of active sessions, skills, memory writes** ([`feral-client/src/pages/GlassBrain.jsx`](feral-client/src/pages/GlassBrain.jsx) + [`feral-core/observability/`](feral-core/observability/)) |
| Channels shipped today | 15+ channels across messaging, social, and telephony | 4 fully-wired (Telegram, Discord, Slack, WhatsApp) + Web + Push + 2 partial (iMessage, Signal). **We are actively expanding** — see gap list below ([`feral-core/channels/base.py`](feral-core/channels/base.py)) |
| LLM providers | 30+ first-party plugins | 4 first-class (OpenAI, Anthropic, Gemini, Ollama) + Groq via voice router. **Gap we are closing** ([`feral-core/voice/realtime_proxy.py`](feral-core/voice/realtime_proxy.py)) |
| Mobile apps | macOS + iOS + Android | iOS + Android + HA Add-on + Browser Extension ([`feral-nodes/ios-app/`](feral-nodes/ios-app/), [`feral-nodes/android-app/`](feral-nodes/android-app/), [`feral-ha-addon/`](feral-ha-addon/), [`feral-extension/`](feral-extension/)) |
| Retry mechanics | Implicit via `message` tool pattern | **Explicit reasoning-only + empty-response + ack-fast-path detection with prompt-addition injection (no history mutation)** ([`feral-core/agents/refusal_handler.py`](feral-core/agents/refusal_handler.py)) |
| Autonomy tiers | Per-command exec approvals | **Three-tier (strict/hybrid/loose) with per-skill `approval_mode` manifest flag** ([`docs/AGENT_CAPABILITIES.md`](docs/AGENT_CAPABILITIES.md) + [`feral-core/security/exec_approvals.py`](feral-core/security/exec_approvals.py)) |
| Identity workspace | Editable workspace files | `~/.feral/IDENTITY.yaml` + `SOUL.md` + `MEMORY.md` + `TOOLS.md` editable at runtime ([`feral-core/identity/workspace.py`](feral-core/identity/workspace.py)) |
| Docs | 400+ pages on Docusaurus | 56 pages on Mintlify ([`docs/mintlify/`](docs/mintlify/)) + in-repo guides |
| Contributor base | Years of public contributors | Early — [FERAL-AI](https://github.com/FERAL-AI) org, first community items in progress |

### FERAL vs broader landscape

| Dimension | Big AI (OpenAI/Apple/Google) | Home Assistant Assist | Open Interpreter | AutoGen / LangChain | **FERAL** |
|---|---|---|---|---|---|
| Runs on your hardware | Cloud | Local | Local | Local | **Local** |
| Connects to physical devices | No | Yes (HomeKit/Zigbee) | No | No | **Yes (HUP + HomeKit + HA + BLE)** |
| Dynamic skill creation | No | No | Shell exec only | Manual scripted chains | **Tool Genesis auto-promote** |
| Signed community marketplace | No | HA Add-ons + HACS | No | No | **registry.feral.sh (8 content kinds)** |
| 4-tier memory | No | No | Session-only | Manual wiring | **Yes + P2P CRDT sync** |
| Open source full stack | Weights only | Yes | Agent core only | Framework only | **Brain + client + mobile + nodes + registry** |
| Voice (sub-200 ms wake) | Assistant-app only | Yes (local Whisper) | No | No | **Yes, 3 providers with failover** |
| Generative UI | No | Lovelace | No | No | **SDUI across iOS / Android / Web** |
| Protocol for 3rd-party hardware | No | Zigbee / Matter / HomeKit | No | No | **HUP v1.0.0 (Apache-2.0)** |

### Where FERAL wins outright today

- Tool Genesis runtime skill creation (no competitor has this loop end-to-end).
- Hardware Unification Protocol — public wire spec + SDKs so any vendor can plug in.
- 4-tier memory with P2P CRDT sync across your own devices.
- Glass Brain live observability of the agent's internals.
- 8-category signed marketplace (skills, daemons, MCP, channels, providers, memory, workflow packs, agent personas).
- Sub-200 ms voice with 3-provider failover out of the box.

### Where we are honestly weaker today (and how we plan to close it)

| Gap | Impact | Plan |
|---|---|---|
| Channel breadth (no Matrix, Signal, Voice Call, Feishu, Zalo, Twitch, IRC) | Every missing channel is a cohort we can't reach | Each channel is a manifest + ~1-3 days of work on the template at [`feral-core/channels/base.py`](feral-core/channels/base.py) |
| LLM provider breadth (only 4 first-class vs 30+ on peers) | Lock-in pain, limited cost/speed flexibility | Publish `kind=provider` items for Groq, Together, OpenRouter, Bedrock, DeepSeek, TGI — ~4 hours each |
| Plugin volume (24 first-party vs 100+ elsewhere) | Smaller out-of-box catalog | Typed across 8 kinds instead of one, so each slot is more valuable; community kickoff + first 10 third-party publishes are next |
| Memory backend plugins (registry has 0 `kind=memory` items) | Users can't swap in Chroma / Qdrant / Honcho | Define the stable `MemoryBackend` interface → publish the first 3 |
| Workflow pack catalog (registry has 0 `kind=workflow` items) | No pre-baked routines to install | Ship 10 first-party TaskFlow packs (PR triage, standup composer, etc.) |
| Agent persona library (registry has 0 `kind=agent` items) | No specialist bots to install | Ship 10 first-party personas spawnable by Agent Mitosis |
| Desktop native app is not signed | Users can run dev builds only | Apple Developer ID + Windows Authenticode + Tauri updater keypair |
| Docs volume is 56 pages vs peers' 400+ | Depth per page is comparable, quantity isn't | Aim 2× page count by end of quarter, especially worked examples |
| Contributor base is small and fresh | Long-tail network effect | Community launch, RFC process, first-party review of third-party submissions |

We publish an updated gap analysis + roadmap on every release — see the
`CHANGELOG.md` for per-version deltas.

---

## Get Started

**One-line install** (macOS / Linux):

```bash
curl -sSL https://raw.githubusercontent.com/FERAL-AI/FERAL-AI/main/scripts/install.sh | bash
```

The installer detects Python 3.11+, creates an isolated venv at `~/.feral-env`, installs `feral-ai[all]`, and prints the activation command. Then:

```bash
source ~/.feral-env/bin/activate
feral start
```

That's it. The Brain starts on `http://localhost:9090` with the web dashboard bundled, the setup wizard runs on first launch, and your browser opens automatically.

**Alternative: pip**

```bash
pip install "feral-ai[all]"
feral start
```

### What Happens
1. `feral start` detects first run → launches the setup wizard
2. You pick an LLM provider (OpenAI, Anthropic, Gemini, Ollama, LM Studio, etc.) and enter your API key
3. FERAL auto-generates a secure API key at `~/.feral/api_key` (shown once in the console)
4. The Brain starts on port 9090, the web dashboard opens, your browser navigates to it

No API key required for local models (Ollama auto-detected on `localhost:11434`, LM Studio on `localhost:1234`).

### Development Mode
If you're developing FERAL itself:
```bash
git clone https://github.com/FERAL-AI/FERAL-AI.git
cd FERAL-AI
make dev           # installs both brain + client
feral serve        # brain on :9090 (headless)
cd feral-client && npm run dev  # Vite on :5173
```

---

## Connect Your First Device

### iOS / Android
Download the FERAL Node app, scan the QR code shown in Settings, and grant HealthKit/Health Connect permissions.

### Wristband (BLE)
Run the hardware daemon on your Mac/Linux host:
```bash
python -m feral_nodes.hardware_daemon --brain ws://localhost:9090 --api-key $FERAL_API_KEY
```

### Smart Home (Philips Hue)
Press the button on your Hue bridge, then open Settings > Devices > Add Hue Bridge.

---

## Architecture

```mermaid
flowchart TB
    subgraph brain [FERAL Brain — feral-core]
        LLM["LLM Orchestrator\n9 providers"]
        MEM["Memory Store\n4-tier + KG"]
        PRO["Proactive Engine\nrule + LLM hybrid"]
        VOI["Voice Pipeline\nOpenAI RT / Gemini / Whisper"]
        SEC["Security\nvault + sandbox + approvals"]
        SKL["Skills\n17 manifests + WASM\nGUI · Browser · PDF · Search"]
        GEN["GenUI Engine\nSDUI generation"]
        INT["Integrations\nCalendar · Email · Health\nSpotify · Notion · Home"]
    end

    subgraph clients [Clients]
        WEB["Web Dashboard\nReact · The Orb · SDUI"]
        DSK["Desktop App\nTauri"]
        PHN["Phone\niOS / Android bridges"]
    end

    subgraph hardware [Hardware Mesh]
        WRI["Wristband\nBLE · HR · SpO2"]
        GLS["Smart Glasses\nvideo stream"]
        HOM["Smart Home\nHue · HA · appliances"]
    end

    brain <-->|"WebSocket\n/v1/session"| clients
    brain <-->|"HUP Protocol\n/v1/node"| hardware
```

**Brain** (`feral-core`): Python. FastAPI + WebSocket. LLM orchestration, tool execution, memory, proactive intelligence, voice pipeline, hardware mesh coordination.

**Client** (`feral-client`): React. Server-Driven UI. The Orb. Command palette. Ambient context strip. Timeline view. Pure renderer — the brain decides what to show.

**Nodes** (`feral-nodes`): Hardware bridges that connect physical devices to the brain via the mesh protocol. Wristband streams biometrics. Glasses stream video. Smart home controls actuators. iOS and Android bridges with QR pairing, location forwarding, and TLS transport.

---

## The Stack

```
feral/
├── feral-core/          # Brain: Python, FastAPI, LLM orchestration
│   ├── agents/          # Orchestrator, proactive engine, digital twin, scheduler
│   ├── memory/          # Episodic, semantic, knowledge graph, vector search, sync
│   ├── voice/           # Wake word, OpenAI Realtime, Gemini Live, Whisper path
│   ├── hardware/        # HUP mesh protocol, device adapters
│   ├── integrations/    # Calendar, email, health, Spotify, Notion, Home Assistant
│   ├── skills/          # Plugin system, 17 manifests, WASM sandbox, marketplace
│   ├── perception/      # Screen capture, audio pipeline, sensor fusion, geofencing
│   ├── channels/        # Telegram, Discord, Slack, WhatsApp, push notifications
│   ├── genui/           # Server-driven UI generation + provider system
│   └── security/        # Vault, sandbox, permissions, approval gates
├── feral-client/        # Web UI: React, The Orb, SDUI renderer, Timeline, Ambient
├── feral-nodes/         # Hardware bridges: iOS, Android, phone, Python SDK
├── desktop/             # Desktop app: Tauri (Rust + Web)
├── sdk/                 # Developer SDK: Python + Node.js
└── docs/                # Documentation site (Docusaurus)
```

---

## Contributing

```bash
git clone https://github.com/FERAL-AI/FERAL-AI.git && cd FERAL-AI
cd feral-core && pip install -e ".[llm,dev]"
cd ../feral-client && npm install && npm run dev
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

---

## Why "FERAL"?

Feral: *adjective* — (of an animal) in a wild state, especially after escape from captivity.

AI was supposed to be personal. To serve you. Instead, it got captured — locked behind subscriptions, harvested for training data, chained to someone else's cloud. Every "personal AI" on the market today is personal in name only.

FERAL is what happens when you break AI out of captivity and let it run wild on your own devices. It knows your heartbeat. It sees your screen. It controls your home. It remembers everything. And it never phones home.

Not because we're idealists. Because that's how it should have worked from the start.

**AI off the leash.**

---

## Meet the mascot

FERAL's mascot is a raccoon. Cunning, resourceful, takes what it wants,
works at night, and has opposable thumbs — an apt mascot for an agent
that runs on your own hardware and actually gets things done.

The founding myth is eight seconds of a real raccoon stealing a lobster
**claw** from a fishmonger's display. You can watch the origin on
[feral.sh](https://feral.sh/) — it's the looping background of the
landing page. Direct link:
[`feral.sh/mascot/raccoon-steals-the-claw.mp4`](https://feral.sh/mascot/raccoon-steals-the-claw.mp4).

The raccoon always wins. Especially when the claw is open.

---

## Created By

**[Mahmoud Omar](https://github.com/mahmoudomar)** and **[Alpay Kasal](https://github.com/alpaykasal)**

Contact: [info@feral.sh](mailto:info@feral.sh) | Website: [feral.sh](https://feral.sh) | GitHub: [FERAL-AI](https://github.com/FERAL-AI)

---

<p align="center">
  <sub>Apache 2.0 · Made with spite and good intentions</sub>
</p>
