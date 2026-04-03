# THEORA — Spatial Agentic OS: Handover Document (v0.4.0)

## Architecture Summary

THEORA is a **local-first, self-learning agentic operating system** that connects hardware daemons (smart glasses, robots, sensors) to a central brain via WebSocket, routes user intent through an LLM with tool calling, executes real API skills, generates dynamic UIs on the fly, and **learns who you are from every interaction**.

```
┌─────────────┐    ┌──────────────────────────────────┐    ┌──────────────┐
│  asos-client │◄──►│         asos-core (Brain)         │◄──►│ asos-nodes   │
│  React + SDUI│    │  FastAPI WS :9090                │    │ w300_daemon   │
│  Streaming UI│    │  Orchestrator → LLM → Skills     │    │ BLE + Vision  │
│  Audio I/O   │    │  Perception → Memory → Learning  │    │ IMU Gestures  │
└─────────────┘    │  Scene Analyzer → Gesture Engine  │    └──────────────┘
                   └──────────────────────────────────┘
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

### Phase 6a: Self-Learning Agent (NEW)
- **Knowledge Extraction**: LLM extracts user facts from conversations → semantic memory
  - Preferences, relationships, routines, medical info, location
  - Triggers every N messages via `Learner.on_message()`
- **Session Summarization**: On disconnect, conversations are summarized → episodic memory
  - `Orchestrator.on_session_disconnect()` → `Learner.summarize_session()`
- **Execution-Aware Routing**: Skill success/failure rates from execution log influence routing
  - `Learner.get_routing_penalties()` → `Orchestrator._apply_routing_penalties()`
  - Failing skills get demoted or skipped entirely
- New file: `asos-core/agents/learner.py`

### Phase 6b: Streaming + Live UI (NEW)
- **Streaming LLM**: Token-by-token output via SSE-style streaming
  - `LLMProvider.chat_stream()` — yields text_delta, tool_call_delta, done
  - `Orchestrator.handle_command_stream()` — sends `stream_delta` messages
- **Client Streaming**: Real-time text rendering with cursor animation
  - `stream_delta` message type with `stream_id` and `is_final`
  - Accumulated text converted to SDUI on completion
- **Protocol**: New `StreamDeltaPayload` message type

### Phase 6c: Gesture + Scene Understanding (NEW)
- **Gesture Interpreter** (`perception/gesture.py`):
  - IMU-based: nod, shake, look_up, look_down, tilt_left, tilt_right, double_tap
  - Sliding window pattern detection with cooldown
  - Priority ordering (tap > look > nod > shake > tilt)
- **Daemon Gesture Detection** (`w300_daemon.py`):
  - `GestureDetector` class integrated into telemetry loop
  - Sends `gesture` messages to brain on detection
- **Scene Analyzer** (`perception/scene.py`):
  - VLM-based frame analysis (GPT-4o vision)
  - Produces structured output: scene_description, detected_objects, text_in_scene
  - Rate-limited with configurable cooldown, cached per node
  - Background analysis triggered on vision frame arrival
- **Protocol**: New `GesturePayload` message type
- **Brain Integration**: Gestures trigger `handle_command` with context

## File Map

```
asos-core/
├── agents/
│   ├── orchestrator.py     — Core agentic loop (v0.4.0)
│   ├── llm_provider.py     — Pluggable LLM with streaming
│   ├── genui_generator.py  — Data → SDUI conversion
│   └── learner.py          — Self-learning agent (NEW)
├── api/
│   └── server.py           — FastAPI brain server (v0.4.0)
├── memory/
│   └── store.py            — 4-tier cognitive memory
├── models/
│   ├── protocol.py         — Wire format (17+ message types)
│   └── skill_manifest.py   — Skill definition schema
├── perception/
│   ├── fusion.py           — PerceptionFrame + PerceptionEngine
│   ├── audio_pipeline.py   — STT/TTS/VAD
│   ├── gesture.py          — IMU gesture interpreter (NEW)
│   └── scene.py            — VLM scene analyzer (NEW)
├── skills/
│   ├── registry.py         — Skill loading + search
│   └── executor.py         — API execution with vault
└── tests/
    ├── test_protocol.py
    ├── test_memory.py
    ├── test_perception.py
    ├── test_safety.py
    ├── test_learner.py     — NEW (9 tests)
    ├── test_gesture.py     — NEW (10 tests)
    └── test_streaming.py   — NEW (10 tests)
```

## Test Coverage

**92 tests passing** across 7 test files:
- Protocol (9), Memory (17), Perception (14), Safety (13)
- Learner (9), Gesture (10), Streaming (10)

## Environment Variables (v0.4.0)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | LLM API key |
| `THEORA_LLM_PROVIDER` | `openai` | openai / ollama / groq |
| `THEORA_LLM_MODEL` | `gpt-4o-mini` | Model name |
| `THEORA_VISION_ENABLED` | `false` | Enable vision pipeline |
| `THEORA_PROACTIVE` | `false` | Enable proactive agent |
| `THEORA_STREAMING` | `false` | Enable streaming LLM |
| `THEORA_SCENE_COOLDOWN` | `10` | Seconds between VLM analyses |
| `THEORA_STT_PROVIDER` | `openai` | Speech-to-text provider |
| `THEORA_TTS_PROVIDER` | `openai` | Text-to-speech provider |
| `NODE_API_KEY` | `dev-secret-key` | Daemon auth key |

## What's Next

1. **Embedding-based skill routing** — replace keyword matching with vector similarity
2. **SDUI Confirmation Flow** — CONFIRM-level safety sends UI dialog, awaits tap
3. **Multi-agent orchestration** — parallel skill execution with result merging
4. **Memory decay** — time-weighted episodic relevance with forgetting curve
5. **On-device inference** — local LLM + Whisper for fully offline mode
6. **Wristband SDK** — extend node SDK for health wristband BLE protocol
