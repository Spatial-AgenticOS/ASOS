# FERAL Unified Roadmap

> Single source of truth. Updated 2026-04-13.

## Shipped (v1.2.x)

### Core Brain
- Multi-provider LLM orchestration — 9 providers wired (OpenAI, Anthropic, Google, Groq, Together, Mistral, Ollama, LM Studio, DeepSeek)
- 3 autonomy modes (strict / hybrid / loose) enforced on all code paths
- Proactive intelligence engine (rule + LLM hybrid triggers)
- Digital twin: RAG over memory + identity persona

### Memory
- 4-tier memory system (working → short-term → long-term → knowledge graph)
- Conversation persistence and recall across sessions

### GenUI / SDUI
- Server-driven UI engine with React renderer in the client
- Component library (cards, charts, forms, lists, media)
- Theme and layout system

### Voice
- OpenAI Realtime voice (WebSocket streaming)
- Gemini Live voice (latest WebSocket API)
- Local STT via faster-whisper (base / small models)
- Local TTS via Piper (en_US-lessac-medium)
- Wake-word detection

### Local / Offline
- Ollama LLM integration (llama3, qwen2, etc.)
- Ollama vision (LLaVA, Moondream)
- Fully offline operation with local STT + TTS + LLM

### Hardware
- HUP hardware mesh protocol + command contract
- Daemon command lifecycle (SUBMITTED → ACKED → RUNNING → SUCCEEDED / FAILED)
- Wristband, smart-home, glasses, and robot device types

### Skills
- 14 built-in skill implementations + manifest-driven discovery
- WASM sandbox for untrusted skill execution
- Extension boundary rules (EXTENSION_RULES.md) with CI enforcement

### Infrastructure
- Desktop app (Tauri)
- Push notifications (FCM + APNs with JWT)
- Mintlify docs site (33+ pages)
- feral.sh landing page
- `pip install feral-ai` on PyPI with optional extras (`[stt]`, `[tts]`, `[vision]`, `[all]`)
- CI pipeline: ruff lint + pytest + Vite build + syntax check + boundary check — all green
- 390+ backend tests, 7 frontend tests

### Baseline Learning
- Anomaly detection on health/sensor data
- Trend detection with rolling statistics

---

## Next (v1.3.0)

- **Coverage push to 50%+** — expand unit + integration tests across brain, memory, skills, and gateway
- **E2E Playwright tests** — chat → tool → SDUI flow, daemon → invoke flow, memory → recall flow
- **`feral tunnel` command** — zero-config remote access via Cloudflare Tunnel or Tailscale
- **GenUI provider marketplace MVP** — package signing, review pipeline, sandboxed loading, basic analytics
- **Permission plane v2** — scoped approvals per skill/device, audit dashboard, consent UX
- **Managed browser automation** — Playwright-as-a-service skill with session management and screenshot capture

---

## Future (v2.0+)

- **Learning engine v2**
  - Work rhythm, location patterns, environmental baselines
  - Explainable drift detection (why did a baseline shift?)
  - Digital twin with provenance and reasoning transparency

- **Warehouse / business scale**
  - Fleet registry with per-device identity
  - Command translation: human intent → validated plan → execution
  - Multi-camera ingestion with sampling, routing, alerts
  - Multi-tenant RBAC, audit trails
  - Simulation / dry-run before live execution

- **NixOS native layer**
  - NixOS module for brain + daemon services
  - Declarative config, systemd hardening, immutable builds
  - Device provisioning via SD card images

- **Plugin-boundary discipline** — ref `feral-core/skills/EXTENSION_RULES.md`
  - Kernel stays extension-agnostic
  - Gateway routing abstraction
  - Supervisor-aware restart

- **Edge AI / federated learning**
  - On-device inference for wearables and embedded systems
  - Federated learning across user devices (privacy-preserving model updates)

- **Multi-language / i18n**
  - Client UI and docs localization
  - Multilingual voice (STT/TTS) support
