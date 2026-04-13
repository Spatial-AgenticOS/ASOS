# FERAL Unified Roadmap

## Shipped (v1.2.0)

- Core brain + 9 LLM providers
- 4-tier memory + knowledge graph
- GenUI/SDUI engine + React renderer
- 3 autonomy modes (strict/hybrid/loose) enforced on all paths
- OpenAI Realtime voice
- Gemini Live voice (latest WebSocket API)
- Local STT (faster-whisper) + Local TTS (Piper)
- Local LLM (Ollama) + Local vision (Ollama LLaVA/Moondream)
- HUP hardware mesh protocol + command contract
- Daemon command lifecycle (SUBMITTED→ACKED→RUNNING→SUCCEEDED/FAILED)
- Baseline learning engine (anomaly + trend detection)
- 17 skill manifests + WASM sandbox
- Proactive intelligence (rule + LLM hybrid)
- Digital twin (RAG over memory + identity)
- Desktop app (Tauri)
- Push notifications (FCM + APNs with JWT)
- 33-page Mintlify docs site
- feral.sh landing page
- pip install feral-ai on PyPI
- CI: lint + tests + build (all green)
- 390+ backend tests + 7 frontend tests

## Next Wave (v1.3.0)

- Comprehensive E2E test suite (chat→tool→SDUI, daemon→invoke, memory→recall)
- Frontend component test coverage (every button, every interaction)
- Baseline engine expansion: work rhythm, location patterns, environmental baselines
- GenUI provider marketplace: signing, review, sandboxing, analytics
- Channel hardening: Telegram as first production-quality channel
- Permission plane: scoped approvals, audit dashboard, consent UX
- Managed browser automation (Playwright as a service)
- Edge safety: E-stop for robots, workspace bounds, human-in-the-loop gates

## Future (v2.0+)

- **NixOS native layer** (reference: docs/NIXOS_VISION.md)
  - NixOS module for brain + daemon services
  - Declarative config, systemd hardening, immutable builds
  - Device provisioning via SD card images
- **Warehouse / business scale** (reference: docs/WAREHOUSE_SPEC.md)
  - Fleet registry with per-device identity
  - Command translation: human intent → validated plan → execution
  - Multi-camera ingestion with sampling/routing/alerts
  - Multi-tenant RBAC, audit trails
  - Simulation / dry-run before live execution
- **Learning engine v2**
  - Statistical baseline with explainable drift
  - Work rhythm, sleep, location, environment verticals
  - Digital twin with provenance and reasoning transparency
- **OpenClaw-style patterns** (reference: feral-core/skills/EXTENSION_RULES.md)
  - Plugin boundary discipline
  - Gateway routing abstraction
  - Supervisor-aware restart
- **Edge AI**
  - On-device inference for wearables and embedded systems
  - Federated learning across user devices
- **Multi-language support**
  - i18n for client UI and docs
  - Multilingual voice (STT/TTS)
