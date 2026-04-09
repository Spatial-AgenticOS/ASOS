# THEORA Runtime Contract

This document defines the deterministic runtime contract for THEORA Brain. Every component (server, CLI, client, desktop wrapper, Docker, Nix) must obey these rules so behaviour is predictable and reproducible.

## Bind and Public URL

| Variable | Default | Purpose |
|:---------|:--------|:--------|
| `THEORA_HOST` | `0.0.0.0` | uvicorn bind address |
| `THEORA_PORT` | `9090` | uvicorn bind port |
| `THEORA_PUBLIC_BASE_URL` | `http://localhost:9090` | URL the browser/API client uses to reach the brain |
| `THEORA_PUBLIC_SCHEME` | `http` | scheme for computed public URL when `THEORA_PUBLIC_BASE_URL` is unset |
| `THEORA_PUBLIC_HOST` | `localhost` | host for computed public URL |
| `THEORA_PUBLIC_PORT` | same as `THEORA_PORT` | port for computed public URL |

Helpers in `asos-core/config/runtime.py` resolve these with fallback chains. Nothing in the codebase should hard-code `localhost:9090` — use the helpers.

## State Directory

| Variable | Default | Contents |
|:---------|:--------|:---------|
| `THEORA_HOME` | `~/.theora` | Root for all persistent state |

Layout inside `THEORA_HOME`:

```
~/.theora/
├── config.yaml          # feature flags, provider, voice mode, security
├── credentials.json     # API keys (chmod 600)
├── identity.yaml        # agent name, personality, voice, rules
├── memory.db            # SQLite: notes, episodes, knowledge graph, wiki, sessions
├── sync_wal.db          # federated sync WAL (optional)
├── genui_surfaces/      # cached GenUI provider surface layouts (JSON per surface)
├── skills/              # custom skill manifests (JSON)
├── mcp_servers.json     # external MCP server connections
├── USER.md              # user profile (from setup wizard)
├── SOUL.md              # agent personality (from setup wizard)
└── TOOLS.md             # auto-synced tool descriptions
```

The server creates `THEORA_HOME` and `memory.db` on first startup if they do not exist.

## LLM Provider

| Variable | Default | Purpose |
|:---------|:--------|:--------|
| `THEORA_LLM_PROVIDER` | `openai` | Active provider: `openai`, `ollama`, `groq`, `anthropic`, `gemini` |
| `THEORA_LLM_MODEL` | `gpt-4o-mini` | Model within the provider |
| `THEORA_LLM_BASE_URL` | provider default | Override API endpoint |
| `THEORA_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OPENAI_API_KEY` | none | OpenAI key (required for openai provider) |
| `GROQ_API_KEY` | none | Groq key (required for groq provider) |
| `ANTHROPIC_API_KEY` | none | Anthropic key |
| `GEMINI_API_KEY` | none | Google Gemini key |

Provider presets are defined in `asos-core/agents/llm_provider.py` (`PROVIDER_PRESETS`). Apply with `POST /api/llm/presets/apply`. The `ollama_vision` preset activates the local VLM path (model `llava`).

## Audio Pipeline

| Variable | Default | Purpose |
|:---------|:--------|:--------|
| `THEORA_STT_PROVIDER` | `openai` | Speech-to-text engine |
| `THEORA_STT_MODEL` | `whisper-1` | STT model |
| `THEORA_TTS_PROVIDER` | `openai` | Text-to-speech engine |
| `THEORA_TTS_MODEL` | `tts-1` | TTS model |
| `THEORA_TTS_VOICE` | `nova` | Voice selection |

Realtime voice uses OpenAI Realtime API directly over WebSocket, not the STT/TTS pipeline.

## Vision

| Variable | Default | Purpose |
|:---------|:--------|:--------|
| `THEORA_VISION_ENABLED` | `false` | Enable camera/vision pipeline |
| `THEORA_VISION_MAX_FRAME_KB` | `512` | Max frame size for VLM analysis |
| `THEORA_SCENE_COOLDOWN` | `10` | Seconds between VLM scene analyses per node |

When vision is requested on a model that does not support it, the provider returns a clear error message directing the user to use a VLM preset.

## Security

| Variable | Default | Purpose |
|:---------|:--------|:--------|
| `NODE_API_KEY` | `dev-secret-key` | Daemon WebSocket auth token |
| `THEORA_MAX_TIER` | `active` | Execution sandbox max tier |
| `THEORA_KEY_*` | none | Blind vault keys (never exposed to the LLM) |

## External Services

| Variable | Default | Purpose |
|:---------|:--------|:--------|
| `THEORA_MARKETPLACE_URL` | `http://localhost:8080/api/v1` | Skill registry server |
| `TAVILY_API_KEY` | none | Web search |

## Startup Sequence

1. FastAPI app created; `BrainState` initialized with `MemoryStore` and `SkillRegistry`.
2. `@app.on_event("startup")` calls `BrainState.init()`:
   - Load builtin skills
   - Create `LLMProvider`, `Learner`, `SceneAnalyzer`
   - Create `BlindVault`, `ExecutionSandbox`, `SandboxPolicy`
   - Create `DeviceRegistry`, `TheoraMCPServer`, `MCPClientManager`
   - Create `ChannelManager`, OAuth integrations, `SyncEngine`
   - Create `WASMSandbox`, `WakeWordDetector`
   - Start `TaskFlowRuntime` (SQLite-backed, recovers in-progress flows)
   - Create `Orchestrator` (receives all subsystem references including live TaskFlowRuntime)
   - Create `RealtimeProxy`, `VoiceRouter`, `GeminiRealtimeProxy`
   - Create `GatewayRegistry`, `HardwareMesh`, `IdentityWorkspace`
   - Create `GenUIEngine` (shared LLM), `ServiceProviderRegistry`, `BrowserController`
   - Optionally initialize `ApprovalManager`, `DockerSandbox`, `CronService`
3. Server begins accepting connections on `THEORA_HOST:THEORA_PORT`.

## Health Check

`GET /health` returns `{"status": "ok", "version": "1.0.0"}` when the server is ready. Docker HEALTHCHECK and load balancers should poll this endpoint.

## Shutdown

`@app.on_event("shutdown")` performs graceful cleanup:
- Close LLM client HTTP sessions
- Disconnect all MCP client connections
- Stop sync engine discovery
- Stop TaskFlow runtime (cancels runner loop)

## Client Discovery

The web client (`asos-client/src/config.js`) resolves the brain URL in this order:
1. `VITE_BRAIN_BASE_URL` build-time variable (explicit override)
2. Constructed from `VITE_BRAIN_HOST` (or `window.location.hostname`) and `VITE_BRAIN_PORT` (or `window.location.port`)
3. Fallback: `http://localhost:9090`

WebSocket URL is derived from the HTTP URL by swapping scheme (`http` to `ws`, `https` to `wss`) and appending `/v1/session`.

Note: the client uses `VITE_BRAIN_*` prefixed variables (Vite build-time env), not the `THEORA_*` server-side variables. When deploying behind a reverse proxy or on a different host, set `VITE_BRAIN_BASE_URL` at build time to match `THEORA_PUBLIC_BASE_URL`.

## Nix

`flake.nix` provides:
- `devShells.default`: Python 3.11, Node 20, git, Rust
- `packages.theora-brain`: shell wrapper for `asos-core`
- `packages.theora-client`: shell wrapper for `asos-client`
- `nixosModules.theora-brain`: systemd service unit (Linux only)

Systems currently defined in `flake.nix`: `x86_64-linux`, `aarch64-linux`. Darwin outputs are not yet in the flake; macOS development uses `pip install` or Docker.

**Lock file:** `flake.lock` must be generated by running `nix flake lock` from a system with Nix installed. This pins input revisions for reproducible builds. Without the lock file, Nix will fetch the latest revision of each input on every build.
