<div align="center">
  <img src="https://img.icons8.com/color/128/artificial-intelligence.png" alt="ASOS Logo" width="128">
  <h1>Spatial-Agentic OS (ASOS)</h1>
  <p><strong>The local-first operating system that replaces apps with intelligence.</strong></p>

  [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
  [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
  [![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()
</div>

---

## What is ASOS?

**Spatial-AgenticOS** is not a chatbot framework. It is the nervous system for the post-app era.

ASOS runs an agentic Brain that simultaneously processes what you **see** (camera), **hear** (microphone), **feel** (biometric sensors), and **do** (gestures) — fusing all inputs into a single multimodal perception frame that drives every decision. The visual interface doesn't exist until you need it, generated in real-time from pure data, and it disappears when you don't.

```
You → speak/look/gesture → Perception Engine → Fused Context → LLM Brain → Skill Execution → Generated UI → You
```

### Core Capabilities

| Capability | Description |
|---|---|
| **Multimodal Perception** | Camera + Microphone + BLE sensors + IMU fused into a single `PerceptionFrame` per tick |
| **4-Tier Memory** | Working (session), Episodic (events), Semantic (knowledge graph), Execution Log (learns from actions) |
| **Voice Pipeline** | Full-duplex: Mic → VAD → Whisper STT → Brain → TTS → Speaker |
| **Vision Pipeline** | Camera frames from smart glasses injected directly into LLM context as image_url blocks |
| **Generative SDUI** | LLM produces native UI (Cards, Grids, MetricCards, Charts) — zero frontend rebuilds |
| **9 Skill Manifests** | Web Search, Spotify, GitHub, Calendar, SMS, Smart Home, Desktop Control, Robot, Notes |
| **Graduated Safety** | AUTO (reads) → CONFIRM (writes) → DENY (dangerous) — not blanket blocking |
| **Proactive Agent** | Acts without being asked: health alerts, battery warnings, contextual notifications |
| **Hardware SDK** | Any BLE/WiFi/ROS device connects to the Brain via one WebSocket daemon |

## Architecture

```
┌─────────────────────────────────────────────┐
│           THE AGENT (The Shell)              │
│  PerceptionFrame → Intent → Skills → SDUI   │
├─────────────────────────────────────────────┤
│         SKILL RUNTIME                        │
│  Registry + Executor + Blind Vault           │
├─────────────────────────────────────────────┤
│         MEMORY LAYER                         │
│  Working │ Episodic │ Semantic │ Exec Log    │
├─────────────────────────────────────────────┤
│         PERCEPTION ENGINE                    │
│  Audio (VAD+STT+TTS) │ Vision │ Sensors     │
├─────────────────────────────────────────────┤
│         HARDWARE ABSTRACTION                 │
│  W300 Glasses │ Robot │ Desktop │ Any BLE    │
└─────────────────────────────────────────────┘
```

## Repository Structure

```
ASOS/
├── asos-core/                 # The Brain (Python/FastAPI)
│   ├── agents/                # Orchestrator, LLM Provider, GenUI Generator
│   ├── api/                   # WebSocket server (port 9090)
│   ├── memory/                # 4-tier memory system (SQLite)
│   ├── perception/            # Audio pipeline + Fusion engine
│   ├── skills/                # Registry, Executor, Manifests, Implementations
│   ├── models/                # Protocol definitions (16+ message types)
│   └── tests/                 # pytest suite
├── asos-nodes/                # Hardware SDK
│   └── python-node-sdk/       # W300 daemon, Robot template
├── asos-client/               # React/Vite SDUI client
│   └── src/components/        # SduiRenderer (12 component types)
├── docs/                      # Architecture docs
├── docker-compose.yml         # One-command deployment
└── .env.example               # Configuration reference
```

## Quick Start

### Docker (Recommended)

```bash
cp .env.example .env
# Edit .env — set OPENAI_API_KEY at minimum

docker compose up --build
# Brain: http://localhost:9090
# Client: http://localhost:3000
```

### Development

```bash
# Terminal 1: Brain
cd asos-core
pip install -e ".[dev]"
export OPENAI_API_KEY="sk-..."
python api/server.py

# Terminal 2: Client
cd asos-client
npm install && npm run dev

# Terminal 3: W300 Glasses Daemon (with dev webcam)
cd asos-nodes/python-node-sdk
pip install -r requirements.txt
python3 w300_daemon.py --dev-camera --vision-interval 10
```

### Run Tests

```bash
cd asos-core
pytest tests/ -v
```

## The Protocol

Every component speaks the **TheoraMessage** envelope:

```json
{
  "msg_id": "uuid",
  "session_id": "uuid",
  "timestamp_ms": 1743000000,
  "hop": "client|brain|daemon|skill",
  "type": "text_command|audio_chunk|vision_frame|sdui|...",
  "payload": { ... }
}
```

16 registered message types covering text, audio, vision, biometrics, SDUI, commands, and device registration.

## How the Perception Engine Works

Every LLM call is informed by a **fused multimodal context**, not just the words the user spoke:

```python
PerceptionFrame(
    heart_rate=85, spo2_pct=98, activity_state="walking",
    head_pose=[5.0, -3.0, 0.0], ambient_light_lux=300,
    has_vision=True, scene_description="Office with whiteboard",
    transcript="what's on the whiteboard?",
    connected_nodes=["daemon_w300-abc"],
)
```

This frame feeds into `to_system_context()` for the LLM system prompt and `to_llm_user_content()` for multimodal messages with attached vision frames.

## Documentation

- [Architecture & Protocol](./docs/ARCHITECTURE.md)
- [Adding Skills](./docs/ADDING_SKILLS.md)
- [Handover & Status](./HANDOVER.md)

## Contributing

We welcome contributions. Run `pytest tests/ -v` before submitting PRs. See `docs/ADDING_SKILLS.md` for the skill manifest format.

---

*THEORA: The intelligence adapts to you. The interface materializes and dissolves as needed. Developers don't build apps — they describe capabilities. Users don't learn an interface — the interface learns them.*
