# THEORA — Spatial Agentic Operating System

**A local-first, self-learning agentic OS that sees, hears, feels, learns, and acts.**

THEORA connects smart glasses, sensors, and robots to a central intelligence that understands your world through fused multimodal perception and learns who you are from every interaction. It ships with a guided setup wizard, full settings dashboard, and native system integration for Linux and macOS.

## Architecture

```
     Client (React + Router)         Brain (FastAPI)               Nodes (Python SDK)
  ┌─────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────┐
  │  /setup  Setup Wizard   │  │  Layered Config System   │  │  W300 Smart Glasses  │
  │  /       Dashboard      │  │  Setup + Config REST API │  │  BLE + Vision + IMU  │
  │  /chat   Streaming HUD  │◄►│  Orchestrator (LLM)      │◄►│  Gesture Detection   │
  │  /settings  Full Config │  │  Self-Learning Agent     │  │  Telemetry Stream    │
  │  Sidebar Navigation     │  │  4-Tier Memory           │  └──────────────────────┘
  │  14 SDUI Components     │  │  Perception + Scene      │
  └─────────────────────────┘  │  Safety + Proactive      │
                               │  112 Tests Passing       │
           ┌───────────────────┴──────────────────────────┘
           │   System Layer
           │  systemd / launchd / Docker
           │  `theora` CLI  ·  XDG paths
           └──────────────────────────────
```

## Capabilities

| Capability | Description |
|---|---|
| **Setup Wizard** | 6-step guided onboarding: provider, keys, skills, features, launch |
| **Settings Dashboard** | Full config management: LLM, audio, vision, skills, security, memory |
| **Layered Config** | User → Project → Local → Env variable merge (inspired by claw-code) |
| **System Service** | systemd (Linux), launchd (macOS), `theora` CLI, install script |
| **Self-Learning** | Extracts knowledge from conversations, summarizes sessions |
| **Streaming LLM** | Token-by-token output with real-time cursor animation |
| **Scene Understanding** | VLM analyzes camera frames → structured scene descriptions |
| **Gesture Recognition** | IMU-based: nod, shake, look up/down, tilt, double-tap |
| **4-Tier Memory** | Working + Episodic + Semantic + Execution Log |
| **Audio Pipeline** | Full-duplex voice: Whisper STT → LLM → TTS streaming |
| **Graduated Safety** | AUTO / CONFIRM / DENY permission tiers for tool execution |
| **Proactive Agent** | Autonomous alerts on health anomalies and device status |
| **Server-Driven UI** | 14 component types generated dynamically from data |
| **Credential Vault** | Separate `credentials.json` with chmod 600, never exposed to client |

## Quick Start

### One-Line Install (Linux/macOS)

```bash
curl -sSL https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/scripts/install.sh | bash
```

### Manual

```bash
git clone https://github.com/Spatial-AgenticOS/ASOS.git && cd ASOS

# Backend
cd asos-core && pip install -e ".[dev]"
uvicorn api.server:app --host 0.0.0.0 --port 9090

# Frontend
cd ../asos-client && npm install && npm run dev
```

### Docker

```bash
cp .env.example .env   # Add your OPENAI_API_KEY
docker compose up --build
```

### CLI

```bash
theora start      # Start the brain
theora setup      # Open setup wizard in browser
theora status     # Check health
theora stop       # Stop the brain
theora daemon     # Start hardware daemon
theora config     # Show config paths
theora logs       # View systemd journal
```

**Client**: http://localhost:3000
**Brain API**: http://localhost:9090
**Setup Wizard**: http://localhost:3000/setup

## Configuration

Settings are loaded from multiple sources (highest priority wins):

| Priority | Source | Path |
|----------|--------|------|
| 1 | Defaults | Built-in |
| 2 | User | `~/.theora/settings.json` |
| 3 | Project | `.theora/settings.json` |
| 4 | Local | `.theora/settings.local.json` |
| 5 | Environment | `THEORA_*` variables |

Credentials stored separately at `~/.theora/credentials.json` (never in settings).

See [`.env.example`](.env.example) for all environment variables.

## Run Tests

```bash
cd asos-core
pip install -e ".[dev]"
pytest tests/ -v
```

**112 tests** across 8 files: protocol, memory, perception, safety, learner, gesture, streaming, config.

## Version History

- **v0.5.0** — Setup wizard, settings dashboard, layered config, Linux system integration, CLI tool
- **v0.4.0** — Self-learning agent, streaming LLM, gesture recognition, VLM scene understanding
- **v0.3.0** — 4-tier memory, audio pipeline, perception fusion, graduated safety, proactive agent
- **v0.2.0** — Vision pipeline, structured telemetry, expanded SDUI
- **v0.1.0** — Foundation: protocol, skills, GenUI, client, daemon

## License

Proprietary — Spatial AgenticOS
