# Spatial-AgenticOS (ASOS) — Handover Document

Welcome to the **ASOS** ecosystem.

This repository is the core of **THEORA OS** — an enterprise-grade, local-first agentic intelligence system that bridges Large Language Models with physical hardware (Smart Glasses, Robotics, IoT) through a unified multimodal perception engine.

---

## What Has Been Accomplished

### Phase 1: Foundation (Complete)
1. **Monorepo Architecture**: Clean separation into `asos-core` (Brain), `asos-nodes` (Hardware SDK), `asos-client` (React UI).
2. **WebSocket Protocol**: Bidirectional TheoraMessage envelope supporting 16+ payload types.
3. **Agentic Orchestrator**: Semantic tool routing (RoutePrompt), LLM-driven skill execution, SDUI generation.
4. **Safety Hooks**: Pre/Post-tool interception with `_infer_permission_denials`.
5. **Hardware Daemons**: W300 Smart Glasses bridge via Bleak BLE, Robot template.
6. **Docker Orchestration**: Full stack deployable via `docker-compose.yml`.

### Phase 2: Vision Pipeline (Complete)
1. **VisionCapture** class — multi-backend frame grabber (BLE, TCP, local webcam).
2. **VisionBuffer** — ring buffer of recent frames per hardware node.
3. **Vision-aware LLM context** — frames injected as OpenAI image_url content blocks.
4. **Expanded telemetry** — structured sensor channels (vitals, IMU, environment, device).
5. **TelemetryAnalyzer** — inferred user state (resting/walking/running/stressed).

### Phase 3: Memory Layer (Complete)
Full 4-tier cognitive memory system aligned with Vision.md:
1. **Working Memory** — in-RAM per-session context window (deque, 50 entries).
2. **Episodic Memory** — timestamped events with FTS5 search, session filtering, importance ranking.
3. **Semantic Memory** — knowledge graph (subject → predicate → object) with upsert and entity queries.
4. **Execution Log** — every skill invocation recorded with latency, outcome, user feedback.
5. **Unified Context Builder** — `build_context_for_llm()` pulls from all tiers for LLM injection.

### Phase 4: Audio Pipeline + Perception Fusion (Complete)
1. **AudioPipeline** — full STT (Whisper API) + TTS (OpenAI) with per-session audio buffers.
2. **AudioBuffer** — chunk accumulation with simple energy-based VAD for utterance detection.
3. **PerceptionFrame** — single fused multimodal context object (audio + vision + sensors + gesture).
4. **PerceptionEngine** — maintains latest frame per session, feeds into orchestrator.
5. **Client mic capture** — MediaRecorder API streams opus chunks to brain via WebSocket.
6. **TTS playback** — brain returns mp3 chunks, client plays them in sequence.

### Phase 5: Safety, Proactive Loop, Client Parity (Complete)
1. **Graduated Safety** — three-tier permission system (AUTO/CONFIRM/DENY) replacing blanket denial.
2. **Proactive Agent Loop** — context-driven autonomous actions (health alerts, battery warnings).
3. **Client SDUI Parity** — all GenUI components now rendered: Grid, ScrollView, MetricCard, AsyncImage, ProgressBar, AudioPlayer, MapView, Spacer.
4. **Core Test Suite** — pytest for protocol, memory (all 4 tiers), perception fusion, safety classification.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│           THE AGENT (The Shell)              │
│  Voice + Vision + Sensor Perception          │
│  Intent Resolution + Skill Routing           │
│  Generative UI Rendering                     │
├─────────────────────────────────────────────┤
│         SKILL RUNTIME                        │
│  Skill Registry + Executor + Blind Vault     │
│  9 Skill Manifests + Web Search Impl         │
├─────────────────────────────────────────────┤
│         MEMORY LAYER                         │
│  Working Memory (in-RAM session context)     │
│  Episodic Memory (past events w/ FTS5)       │
│  Semantic Memory (knowledge graph triples)   │
│  Execution Log (skill audit trail)           │
├─────────────────────────────────────────────┤
│         PERCEPTION ENGINE                    │
│  Audio Pipeline (VAD + Whisper STT + TTS)    │
│  Vision Pipeline (VLM scene understanding)   │
│  Sensor Fusion (biometrics + IMU + env)      │
│  PerceptionFrame (unified context object)    │
├─────────────────────────────────────────────┤
│         HARDWARE ABSTRACTION LAYER           │
│  W300 Glasses (BLE/TCP/Webcam fallback)      │
│  Robot Template (WS_EXECUTE protocol)        │
│  Desktop Control (AppleScript/Shell)         │
├─────────────────────────────────────────────┤
│         DOCKER / DEPLOYMENT                  │
│  Brain: FastAPI + uvicorn (port 9090)        │
│  Client: React + Vite + Nginx (port 3000)    │
│  Memory: SQLite volume mount                 │
└─────────────────────────────────────────────┘
```

---

## What's Next

1. **On-device VLM** — Run a quantized vision-language model locally for real-time scene understanding without cloud latency.
2. **Skill Marketplace** — Dynamic skill registration via web API, not just JSON files.
3. **Multi-session Context** — Concurrent task management (track a ride AND monitor a recipe).
4. **Android Launcher** — THEORA as default home screen (Phase 2 of Vision.md).
5. **Edge Audio** — On-device Whisper for zero-latency STT on the daemon itself.
6. **Gesture Interpreter** — Map IMU patterns to gestures (nod=confirm, shake=deny).

---

## Quick Start

```bash
# Copy env
cp .env.example .env
# Set your OpenAI key
echo "OPENAI_API_KEY=sk-..." >> .env

# Start everything
docker compose up --build

# Brain: http://localhost:9090
# Client: http://localhost:3000
```

For development without Docker:

```bash
# Brain
cd asos-core && pip install -e . && python api/server.py

# Client
cd asos-client && npm install && npm run dev

# W300 Daemon (with dev webcam)
cd asos-nodes/python-node-sdk && pip install -r requirements.txt
python3 w300_daemon.py --dev-camera --vision-interval 10
```

---

## Tests

```bash
cd asos-core
pip install pytest pytest-asyncio
pytest tests/ -v
```
