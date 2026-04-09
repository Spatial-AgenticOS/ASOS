# Contributing to THEORA

THEORA is building an agent-native computing platform. Contributions across all system layers are welcome.

## Development Setup

```bash
git clone https://github.com/Spatial-AgenticOS/ASOS.git
cd ASOS/asos-core
pip install -e ".[llm,dev]"
pytest                    # run tests
theora setup              # configure locally
theora serve              # start the brain
```

For the web client:

```bash
cd asos-client
npm install
npm run dev
```

For the Nix dev shell (Linux):

```bash
nix develop
```

## Project Layout

| Directory | What it contains |
|:----------|:-----------------|
| `asos-core/` | Python backend: brain API, orchestrator, memory, voice, security, GenUI, hardware protocol |
| `asos-client/` | React web UI (Vite + Tailwind) |
| `asos-nodes/` | Hardware daemon SDKs (Python, iOS Swift, Android Kotlin) |
| `desktop/` | Tauri desktop app |
| `registry/` | Skill marketplace server |
| `scripts/` | Install, test, and demo scripts |
| `docs/` | Architecture, runtime contract, roadmap, specs |

## Contributor Lanes

Pick the lane that matches your expertise. Each lane has clear entry files and scope.

### Runtime / Orchestrator
Agent loop, LLM routing, multi-agent dispatch, TaskFlows, session management, security enforcement.
- `asos-core/agents/orchestrator.py`
- `asos-core/agents/multi_agent.py`
- `asos-core/api/server.py`
- `asos-core/security/`

### Memory / Knowledge
4-tier memory store, wiki compilation, ingest pipelines, federated sync, knowledge graph.
- `asos-core/memory/store.py`
- `asos-core/memory/sync.py`

### GenUI / Provider Surfaces
SDUI engine, provider contract lifecycle, surface caching, client renderer, component library.
- `asos-core/genui/generator.py`
- `asos-client/src/components/SduiRenderer.jsx`
- See [`docs/GENUI_PROVIDER_SPEC.md`](docs/GENUI_PROVIDER_SPEC.md) for the contract format.

### Hardware / Daemons
Node WebSocket protocol, daemon SDKs, device profiles, edge bridges (BLE, MQTT, serial, ROS).
- `asos-core/hardware/protocol.py`
- `asos-core/hardware/mesh.py`
- `asos-nodes/`
- See [`docs/HARDWARE_ECOSYSTEM.md`](docs/HARDWARE_ECOSYSTEM.md) for the daemon contract.

### Voice / Perception
Realtime voice proxy, wake word detection, vision pipeline, multimodal sensor fusion.
- `asos-core/voice/`
- `asos-core/perception/`

### Nix / Packaging
Flake outputs, NixOS service modules, reproducible builds, dependency closures.
- `flake.nix`
- See [`docs/NIX.md`](docs/NIX.md) for current foundation.

### Frontend / Shell
Web UI pages, dashboard, Tauri desktop wrapper, mobile bridges.
- `asos-client/src/`
- `desktop/`

## Running Tests

```bash
cd asos-core
python -m pytest tests/ -v
```

## Code Style

- Python: follow existing patterns in the codebase. Type hints are encouraged.
- JavaScript/React: follow existing JSX patterns. Tailwind for styling.
- Avoid adding comments that just narrate what the code does.

## Pull Requests

- One focused change per PR.
- Reference the relevant contributor lane or area.
- Include a brief description of what changed and why.
- If you are adding a new extension surface (provider, daemon, skill), include a minimal working example.

## Key Documentation

- [`docs/DEVELOPER_MISSION.md`](docs/DEVELOPER_MISSION.md) — What we are building and why
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — System architecture overview
- [`docs/RUNTIME_CONTRACT.md`](docs/RUNTIME_CONTRACT.md) — Env vars, state paths, startup contract
- [`docs/GENUI_PROVIDER_SPEC.md`](docs/GENUI_PROVIDER_SPEC.md) — GenUI provider surface contract
- [`docs/HARDWARE_ECOSYSTEM.md`](docs/HARDWARE_ECOSYSTEM.md) — Hardware daemon contract
- [`docs/SCORECARD.md`](docs/SCORECARD.md) — Capability status (shipped / partial / planned)
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — Strategic execution order
