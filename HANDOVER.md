# THEORA — Engineering Handover (v1.0.0)

> Open-source AI agent — computer use, voice, GenUI, memory, hardware control

## Status: Beta — Core Working, Advanced Features In Progress

Core systems are implemented and tested. Advanced features have code but vary in completeness:
- **174+ passing tests** across unit and integration suites
- **Multi-agent collaboration** — router-worker architecture with 4 specialist agents
- **Voice wake word** — "Hey THEORA" with openwakeword integration
- **On-device LLM** — MLX (Apple Silicon) + llama.cpp (cross-platform) inference
- **Skill marketplace** — install/uninstall/search community skills
- **Android bridge SDK** — Kotlin mirroring the iOS architecture
- **Federated memory** — CRDT-based P2P sync via mDNS with HLC timestamps
- **WASM plugin sandboxing** — wasmtime-based secure execution of untrusted skills
- **Real-time voice** — OpenAI Realtime API proxy with tool interception
- **Continuous vision** — event-driven VLM with change detection
- **Deep app integrations** — OAuth2/PKCE for Spotify, Home Assistant, Notion
- **Self-generating skills** with user approval flow
- **Blind Vault** security with permission tiers and audit trail
- **iOS Bridge** for THEORA glasses → phone → Brain pipeline
- **4-tier memory** with persistent storage and cross-device sync
- **Multimodal perception** fusion (vision + audio + biometrics + gestures)
- **Layered config** system with XDG compliance
- **System integration** (systemd/launchd/Docker)

## Architecture Overview

```
THEORA is not a chatbot framework. It is a distributed operating system
for autonomous agents that interact with the physical world.

The Brain runs on your machine. Nodes connect via authenticated WebSocket.
The LLM never sees your credentials. Skills are generated at runtime.
Every action above "passive" requires explicit user approval.
```

### Component Map

| Component | Location | Purpose |
|---|---|---|
| Brain API | `asos-core/api/server.py` | FastAPI + WebSocket hub, routes everything |
| Multi-Agent | `asos-core/agents/multi_agent.py` | Router-worker architecture, parallel dispatch |
| Workers | `asos-core/agents/workers/*.py` | Health, Home, Research, Creative specialists |
| Orchestrator | `asos-core/agents/orchestrator.py` | LLM reasoning, skill routing, streaming |
| Local Inference | `asos-core/agents/local_inference.py` | MLX + llama.cpp on-device LLM |
| Skill Generator | `asos-core/agents/skill_generator.py` | Detects unmet needs, proposes new skills |
| Learner | `asos-core/agents/learner.py` | Self-improvement from interaction patterns |
| Memory Store | `asos-core/memory/store.py` | 4-tier: working → notes → episodes → knowledge |
| Federated Sync | `asos-core/memory/sync.py` | CRDT-based P2P memory replication |
| HLC | `asos-core/memory/hlc.py` | Hybrid Logical Clocks for causal ordering |
| Perception | `asos-core/perception/fusion.py` | Multimodal sensor fusion |
| Wake Word | `asos-core/perception/wake_word.py` | "Hey THEORA" detection with openwakeword |
| Scene Analyzer | `asos-core/perception/scene.py` | VLM-powered vision understanding |
| Change Detector | `asos-core/perception/change_detector.py` | Event-driven frame analysis |
| Audio Pipeline | `asos-core/perception/audio_pipeline.py` | STT + TTS + wake word gating |
| Voice Router | `asos-core/voice/router.py` | Dual-path: Realtime API vs Whisper+TTS |
| Realtime Proxy | `asos-core/voice/realtime_proxy.py` | OpenAI Realtime API with tool interception |
| Skill Registry | `asos-core/skills/registry.py` | Load, register, hot-reload + marketplace |
| Skill Executor | `asos-core/skills/executor.py` | HTTP + WS_EXECUTE + WASM skill dispatch |
| Marketplace | `asos-core/skills/marketplace.py` | Search, install, manage community skills |
| Skill Package | `asos-core/skills/package.py` | Package validation and security checks |
| Blind Vault | `asos-core/security/vault.py` | Credential isolation, audit trail |
| WASM Sandbox | `asos-core/security/wasm_sandbox.py` | wasmtime-based sandboxed skill execution |
| WASM Host | `asos-core/security/wasm_host.py` | Host function ABI for WASM skills |
| Sandbox Policy | `asos-core/security/sandbox_policy.py` | Declarative YAML policies for HW + SW + WASM |
| OAuth Manager | `asos-core/integrations/oauth_manager.py` | OAuth2/PKCE for app integrations |
| Integrations | `asos-core/integrations/*.py` | Spotify, Home Assistant, Notion |
| Webhook Receiver | `asos-core/integrations/webhook_receiver.py` | Incoming event handler with HMAC verification |
| Config Loader | `asos-core/config/loader.py` | Layered settings, XDG, credential management |
| Protocol | `asos-core/models/protocol.py` | Wire format — every node speaks this |

### Client

| Page | Location | Purpose |
|---|---|---|
| Setup Wizard | `asos-client/src/pages/SetupWizard.jsx` | 6-step onboarding |
| Dashboard | `asos-client/src/pages/Dashboard.jsx` | System status + security + skill proposals |
| Chat HUD | `asos-client/src/App.jsx` | Streaming chat + SDUI rendering |
| Settings | `asos-client/src/pages/Settings.jsx` | Full configuration management |
| AppShell | `asos-client/src/components/AppShell.jsx` | Sidebar navigation |

### Edge Nodes

| Node | Location | Connection |
|---|---|---|
| Desktop Daemon | `asos-nodes/python-node-sdk/daemon.py` | WS to Brain |
| W300 Glasses | `asos-nodes/python-node-sdk/w300_daemon.py` | BLE + WS |
| Robot Template | `asos-nodes/python-node-sdk/robot_template.py` | WS + WS_EXECUTE |
| iOS Bridge | `asos-nodes/ios-bridge/ASOSBrainClient.swift` | WS to Brain |
| Sensor Bridge | `asos-nodes/ios-bridge/TheoraSensorBridge.swift` | JWBle SDK → WS |
| Android Bridge | `asos-nodes/android-bridge/` | WS to Brain (Kotlin) |

## Key Design Decisions

### 1. Self-Generating Skills (agent creates its own tools)

The agent detects when the user asks for something no existing skill can handle.
It generates a complete skill manifest (JSON) using the LLM, sends it to the client
as a `skill_proposal`, and waits for user approval. Once approved, the skill is
registered live — no restart needed.

**Files**: `agents/skill_generator.py`, API endpoints in `server.py`

### 2. Blind Vault (LLM never sees credentials)

All API keys are stored in `~/.theora/credentials.json` (chmod 600). When a skill
needs a key, the **executor** injects it at HTTP request time. The LLM only knows
"web_search is available" — never the actual key value. Even the client only sees
key names and SHA-256 fingerprints, never values.

**Files**: `security/vault.py`

### 3. Permission Tiers (graduated autonomy)

| Tier | Can Do | Confirmation? |
|---|---|---|
| Passive | Read-only: weather, search, status | No |
| Active | Send data: messages, calendar events | No |
| Privileged | Modify system: file access, shell commands | Yes |
| Dangerous | Destructive: delete, financial, sudo | Yes |

The `ExecutionSandbox` enforces tier limits, rate limits per skill, and domain blocking.

### 4. Phone as Bridge (not another Brain)

THEORA glasses connect via BLE to the iPhone, not the Mac. The iPhone runs the
`ASOSBrainClient` which:
- Registers as a `phone` node type
- Bridges sensor data (HR, SpO2, temp, UV, steps) from glasses to Brain
- Provides camera, microphone, and GPS as additional capabilities
- Handles skill approval UX natively
- Supports permission confirmation dialogs

This is architecturally superior because:
- Glasses have limited BLE range — phone is always nearby
- Phone can preprocess/cache sensor data
- Phone can provide native UI for approvals
- Single WebSocket replaces multiple connections

### 5. Layered Configuration

Priority (highest wins):
1. Environment variables (`THEORA_LLM_PROVIDER=ollama`)
2. Local project settings (`.theora/settings.local.json`)
3. Project settings (`.theora/settings.json`)
4. User settings (`~/.theora/settings.json`)
5. Defaults (hardcoded in `config/loader.py`)

## Protocol Summary

Every message uses the `TheoraMessage` envelope:

```json
{
  "msg_id": "uuid",
  "session_id": "session-uuid",
  "timestamp_ms": 1234567890,
  "hop": "client|brain|daemon|node|skill",
  "type": "message_type",
  "payload": { ... }
}
```

### Message Types

**Client → Brain**: `text_command`, `audio_chunk`, `biometric`, `ui_event`
**Brain → Client**: `text_response`, `stream_delta`, `sdui`, `sdui_patch`, `tts_chunk`, `transcript`, `skill_proposal`, `confirmation_required`
**Node → Brain**: `register`, `execute_result`, `vision_frame`, `gesture`, `telemetry`, `sensor_telemetry`, `sensor_batch`, `glasses_status`, `skill_approval`
**Brain → Node**: `execute`, `vision_request`

## Running Tests

```bash
cd asos-core
pip install pytest pytest-asyncio httpx
python -m pytest tests/ -v
```

## What's Next

1. **iOS app integration** — Drop `ASOSBrainClient.swift` + `TheoraSensorBridge.swift` into the existing JWBleDemo project, replace the direct OpenAI WebSocket with the Brain connection
2. **Real glasses testing** — Connect actual THEORA (W300) hardware, validate sensor data flow
3. **Robot integration** — Wire `robot_template.py` to real hardware (serial/ROS)
4. **CI/CD** — GitHub Actions, pytest-cov, coverage badge
5. **Marketplace registry** — Deploy `registry.theora.io` for community skill publishing
6. **Android app** — Build Android app using the `android-bridge` SDK
7. **Custom wake word model** — Train a dedicated "Hey THEORA" openwakeword model
8. **Production memory sync** — End-to-end testing of federated sync across multiple devices
9. **WASM skill templates** — Starter projects in Rust/Go/AssemblyScript for WASM skill authoring
