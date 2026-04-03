# THEORA — Spatial Agentic Operating System

**A local-first, self-learning agentic OS that sees, hears, feels, learns, and acts.**

THEORA connects smart glasses, sensors, and robots to a central intelligence that understands your world through fused multimodal perception and learns who you are from every interaction.

## Architecture

```
        Client (React)              Brain (FastAPI)              Nodes (Python SDK)
    ┌──────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
    │  Streaming SDUI   │◄───►│  Orchestrator (LLM)  │◄───►│  W300 Smart Glasses  │
    │  Audio Capture     │     │  Self-Learning Agent │     │  BLE + Vision + IMU  │
    │  TTS Playback      │     │  4-Tier Memory       │     │  Gesture Detection   │
    │  Gesture Display   │     │  Perception Fusion   │     │  Telemetry Stream    │
    │  14 UI Components  │     │  Scene Understanding │     │                      │
    └──────────────────┘     │  Graduated Safety    │     └──────────────────────┘
                              │  Proactive Loop      │
                              │  Audio Pipeline      │
                              │  92 Tests Passing    │
                              └──────────────────────┘
```

## Capabilities

| Capability | Description |
|---|---|
| **Self-Learning** | Extracts knowledge from conversations, summarizes sessions, learns preferences |
| **Streaming LLM** | Token-by-token output with real-time cursor animation |
| **Scene Understanding** | VLM analyzes camera frames → structured scene descriptions |
| **Gesture Recognition** | IMU-based: nod, shake, look up/down, tilt, double-tap |
| **4-Tier Memory** | Working + Episodic + Semantic + Execution Log |
| **Audio Pipeline** | Full-duplex voice: Whisper STT → LLM → TTS streaming |
| **Multimodal Perception** | Fused context: audio + vision + sensors + gestures |
| **Graduated Safety** | AUTO / CONFIRM / DENY permission tiers for tool execution |
| **Proactive Agent** | Autonomous alerts on health anomalies and device status |
| **Server-Driven UI** | 14 component types generated dynamically from data |
| **Skill System** | Manifest-based APIs with blind vault credential management |
| **Vision Pipeline** | BLE camera, TCP/WiFi-Direct, webcam fallback |

## Quick Start

```bash
# Clone
git clone https://github.com/Spatial-AgenticOS/ASOS.git
cd ASOS

# Configure
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# Run with Docker
docker compose up --build

# Or run directly
cd asos-core && pip install -e ".[dev]"
uvicorn api.server:app --host 0.0.0.0 --port 9090
```

**Client**: http://localhost:3000  
**Brain API**: http://localhost:9090

## Run Tests

```bash
cd asos-core
pip install -e ".[dev]"
pytest tests/ -v
```

**92 tests** covering: protocol, memory, perception, safety, self-learning, gestures, streaming.

## Environment Variables

See [`.env.example`](.env.example) for all configuration options including:
- LLM provider (OpenAI, Ollama, Groq)
- Audio pipeline (STT/TTS)
- Vision pipeline
- Streaming mode
- Proactive agent
- Scene understanding cooldown

## Version History

- **v0.4.0** — Self-learning agent, streaming LLM, gesture recognition, VLM scene understanding
- **v0.3.0** — 4-tier memory, audio pipeline, perception fusion, graduated safety, proactive agent
- **v0.2.0** — Vision pipeline, structured telemetry, expanded SDUI
- **v0.1.0** — Foundation: protocol, skills, GenUI, client, daemon

## License

Proprietary — Spatial AgenticOS
