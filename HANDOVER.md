# THEORA — Spatial Agentic OS: Handover Document (v0.5.0)

## Architecture Summary

THEORA is a **local-first, self-learning agentic operating system** that connects hardware daemons (smart glasses, robots, sensors) to a central brain via WebSocket, routes user intent through an LLM with tool calling, executes real API skills, generates dynamic UIs on the fly, and **learns who you are from every interaction**. It ships with a **setup wizard, settings dashboard, and Linux system integration** for production deployment.

```
┌──────────────────┐    ┌──────────────────────────────────┐    ┌──────────────┐
│   asos-client    │◄──►│         asos-core (Brain)         │◄──►│ asos-nodes   │
│  React + Router  │    │  FastAPI WS :9090                │    │ w300_daemon   │
│  Setup Wizard    │    │  Layered Config System           │    │ BLE + Vision  │
│  Dashboard       │    │  Setup + Config REST API         │    │ IMU Gestures  │
│  Settings Page   │    │  Orchestrator → LLM → Skills     │    └──────────────┘
│  Chat HUD + SDUI │    │  Perception → Memory → Learning  │
│  Streaming UI    │    │  Scene Analyzer → Gesture Engine  │
└──────────────────┘    └──────────────────────────────────┘
                                     ▲
                        ┌────────────┴─────────────┐
                        │   Linux System Layer     │
                        │  systemd / launchd       │
                        │  XDG paths / CLI tool    │
                        │  theora start|stop|setup │
                        └──────────────────────────┘
```

## Completed Phases

### Phase 1-2: Foundation + Vision Pipeline
- WebSocket protocol with typed message envelope (`TheoraMessage`)
- Skill manifest system with semantic routing
- GenUI generator (template → structural rules → LLM)
- SDUI renderer (14 component types)
- Vision frame capture from W300 glasses (BLE, TCP, webcam fallback)
- Structured telemetry pipeline with `TelemetryAnalyzer`

### Phase 3: 4-Tier Cognitive Memory
- **Working Memory**: In-RAM per-session context (deque)
- **Episodic Memory**: SQLite + FTS5, timestamped events
- **Semantic Memory**: Knowledge graph (subject-predicate-object) with upsert
- **Execution Log**: Every skill call with outcome, latency, feedback
- **Unified Context Builder**: Aggregates all tiers for LLM injection

### Phase 4: Audio Pipeline + Perception Fusion
- STT via OpenAI Whisper with energy-based VAD
- TTS via OpenAI TTS streaming MP3 chunks
- `PerceptionFrame` — unified multimodal context (audio, vision, sensors, gesture)
- `PerceptionEngine` — maintains per-session frame from all input streams
- Multimodal LLM content (text + image_url) when vision is active

### Phase 5: Safety + Proactive + Client Parity
- **Graduated Safety**: AUTO/CONFIRM/DENY classification for tool execution
- **Proactive Agent Loop**: Autonomous actions on health alerts, low battery
- **SDUI Parity**: Client renders all 14 component types from GenUI
- **Test Suite**: Comprehensive pytest coverage (protocol, memory, perception, safety)

### Phase 6a: Self-Learning Agent
- **Knowledge Extraction**: LLM extracts user facts from conversations → semantic memory
- **Session Summarization**: On disconnect, conversations are summarized → episodic memory
- **Execution-Aware Routing**: Skill success/failure rates influence routing
- New file: `asos-core/agents/learner.py`

### Phase 6b: Streaming + Live UI
- **Streaming LLM**: Token-by-token output via SSE-style streaming
- **Client Streaming**: Real-time text rendering with cursor animation
- **Protocol**: `StreamDeltaPayload` message type

### Phase 6c: Gesture + Scene Understanding
- **Gesture Interpreter** (`perception/gesture.py`): nod, shake, look, tilt, double-tap
- **Scene Analyzer** (`perception/scene.py`): VLM-based frame analysis
- **Protocol**: `GesturePayload` message type

### Phase 7: Setup, Settings & System Integration (NEW)

#### 7a: Layered Configuration System
Inspired by [claw-code-parity](https://github.com) — merges settings from multiple sources:

| Priority | Source | Path | Purpose |
|----------|--------|------|---------|
| 1 (lowest) | Defaults | Built-in | Sane defaults for all settings |
| 2 | User | `~/.theora/settings.json` | User-global preferences |
| 3 | Project | `.theora/settings.json` | Per-project overrides |
| 4 | Local | `.theora/settings.local.json` | Machine-local (gitignored) |
| 5 (highest) | Environment | `THEORA_*` | Runtime overrides |

- **Credentials vault**: `~/.theora/credentials.json` (chmod 600, never merged into settings)
- **Skill keys**: `THEORA_KEY_<skill_id>` env vars or `credentials.json` → `skill_keys` map
- **XDG-compliant**: Respects `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `THEORA_HOME`
- **New file**: `asos-core/config/loader.py`

#### 7b: Setup & Configuration REST API
Brain server exposes full config management at `/api/`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/setup/status` | GET | Check if initial setup is complete |
| `/api/config` | GET | Get settings (safe, no secrets) |
| `/api/config/update` | POST | Update a single setting |
| `/api/config/credentials` | POST | Save API keys to vault |
| `/api/config/validate-key` | POST | Test an API key (OpenAI/Groq/Ollama) |
| `/api/setup/complete` | POST | Finalize setup, save all settings |
| `/api/nodes` | GET | List connected hardware nodes |
| `/api/system/info` | GET | Full system info for dashboard |

#### 7c: Multi-Page Client with Setup Wizard
Complete client rewrite with `react-router-dom`:

- **Setup Wizard** (`/setup`): 6-step guided onboarding
  1. Welcome — branding, feature overview
  2. LLM Provider — choose OpenAI/Groq/Ollama, select model
  3. API Keys — enter key with inline validation, skill API keys
  4. Skills — toggle available skills
  5. Features — streaming, proactive, self-learning, vision toggles
  6. Launch — summary + finish button
- **Dashboard** (`/`): System status, memory stats, connected nodes, active features
- **Chat** (`/chat`): Full HUD with streaming, SDUI, voice
- **Settings** (`/settings`): Full settings management
  - LLM provider/model, features toggles, vision config, audio config
  - Skill API key management with add/remove
  - Security (node API key), memory export/clear
- **AppShell**: Sidebar navigation with responsive layout
- **Auto-redirect**: New users → `/setup`, returning users → `/`
- **SPA Routing**: nginx `try_files` fallback for deep links

#### 7d: Linux System Integration
Production-ready system deployment:

- **`scripts/install.sh`**: One-line installer
  - Creates XDG directories, installs deps, builds client
  - Installs `theora` CLI to `~/.local/bin/`
  - Sets up systemd user service (Linux) or launchd agent (macOS)
- **`theora` CLI**:
  - `theora start` — Launch the brain server
  - `theora stop` — Stop the brain
  - `theora status` — Check health
  - `theora setup` — Open setup wizard in browser
  - `theora daemon` — Start hardware daemon
  - `theora config` — Show config paths and values
  - `theora logs` — View systemd journal
- **systemd service** (`~/.config/systemd/user/theora-brain.service`):
  - Auto-restart on failure, XDG environment, network dependency
  - Enable with: `systemctl --user enable --now theora-brain`
- **launchd agent** (`~/Library/LaunchAgents/com.theora.brain.plist`):
  - macOS-native background service
- **Docker**: Config volume added to `docker-compose.yml`

## File Map

```
asos-core/
├── agents/
│   ├── orchestrator.py     — Core agentic loop (v0.4.0)
│   ├── llm_provider.py     — Pluggable LLM with streaming
│   ├── genui_generator.py  — Data → SDUI conversion
│   └── learner.py          — Self-learning agent
├── api/
│   └── server.py           — FastAPI brain + config API (v0.5.0)
├── config/                  — NEW
│   ├── __init__.py
│   └── loader.py           — Layered config system
├── memory/
│   └── store.py            — 4-tier cognitive memory
├── models/
│   ├── protocol.py         — Wire format (17+ message types)
│   └── skill_manifest.py   — Skill definition schema
├── perception/
│   ├── fusion.py           — PerceptionFrame + PerceptionEngine
│   ├── audio_pipeline.py   — STT/TTS/VAD
│   ├── gesture.py          — IMU gesture interpreter
│   └── scene.py            — VLM scene analyzer
├── skills/
│   ├── registry.py         — Skill loading + search
│   └── executor.py         — API execution with vault
└── tests/
    ├── test_protocol.py
    ├── test_memory.py
    ├── test_perception.py
    ├── test_safety.py
    ├── test_learner.py     — 9 tests
    ├── test_gesture.py     — 10 tests
    ├── test_streaming.py   — 10 tests
    └── test_config.py      — NEW (20 tests)

asos-client/
├── src/
│   ├── main.jsx            — Router + setup detection
│   ├── App.jsx             — Chat HUD
│   ├── components/
│   │   ├── AppShell.jsx    — NEW: Sidebar navigation
│   │   └── SduiRenderer.jsx
│   └── pages/              — NEW
│       ├── SetupWizard.jsx — 6-step onboarding
│       ├── Dashboard.jsx   — System overview
│       └── Settings.jsx    — Full config management
├── nginx.conf              — NEW: SPA fallback
└── Dockerfile

scripts/
└── install.sh              — NEW: One-line system installer
```

## Test Coverage

**112 tests passing** across 8 test files:
- Protocol (9), Memory (17), Perception (14), Safety (13)
- Learner (9), Gesture (10), Streaming (10), Config (20)

## What's Next

1. **Embedding-based skill routing** — replace keyword matching with vector similarity
2. **SDUI Confirmation Flow** — CONFIRM-level safety sends UI dialog, awaits tap
3. **Multi-agent orchestration** — parallel skill execution with result merging
4. **Memory decay** — time-weighted episodic relevance with forgetting curve
5. **On-device inference** — local LLM + Whisper for fully offline mode
6. **Wristband SDK** — extend node SDK for health wristband BLE protocol
7. **Plugin system** — installable plugins with manifest + hooks (à la claw-code-parity)
8. **D-Bus integration** — desktop notifications on Linux
