# FERAL Capability Scorecard

Brutally honest capability matrix. No marketing spin.

**Legend**

| Status | Meaning |
|:-------------|:--------|
| **Working** | Code exists, tested, usable today |
| **Partial** | Code exists but incomplete, untested in prod, or depends on external setup |
| **Scaffolding** | Template/stub only — not functional |
| **Not Yet** | Does not exist |

---

## Core Brain

| Feature | Status | Notes |
|:--------|:-------|:------|
| LLM Orchestration (9 providers) | Working | OpenAI, Anthropic, Gemini, Ollama, Groq, Mistral, Cohere, DeepSeek, OpenRouter |
| Skill Registry + Executor | Working | Dynamic registration, discovery, execution loop |
| Tool Safety / Autonomy Modes | Working | strict/hybrid/loose enforced on all paths |
| MCP Client | Working | Connects to external MCP servers |
| MCP Server | Working | Exposes FERAL tools over `/mcp` endpoint |

## Memory

| Feature | Status | Notes |
|:--------|:-------|:------|
| Working Memory (per-session) | Working | In-process, scoped to session lifetime |
| Episodic Memory (SQLite + FTS) | Working | Full-text search over past interactions |
| Knowledge Graph | Working | Entity/relation store, queryable |
| Execution Log | Working | Persisted skill/tool execution history |
| P2P Sync | Partial | Code exists, not battle-tested across real nodes |
| Wiki Compilation | Working | Ingest repo/PDF/text, browse, search |

## Perception

| Feature | Status | Notes |
|:--------|:-------|:------|
| Screen Capture | Working | macOS only; no Windows/Linux support |
| Audio Pipeline | Partial | Depends on provider; no unified abstraction |
| Scene Analysis | Partial | LLM-based vision; no SLAM, no 3D understanding |
| Sensor Fusion (PerceptionFrame) | Working | Merges multi-modal inputs into unified frame |
| Wake Word | Partial | openwakeword integration; quality varies by environment |
| Location / Geofencing | Partial | Needs GPS feed from phone; no native desktop GPS |

## Voice

| Feature | Status | Notes |
|:--------|:-------|:------|
| OpenAI Realtime | Working | WebSocket streaming, function calling, reconnection with exponential backoff |
| Gemini Live | Working | Bidirectional audio streaming |
| Whisper / Classic STT | Working | Standard transcription path |
| Wake Word Detection | Partial | See Perception — same openwakeword dependency |
| TTS | Working | Via provider backends (OpenAI, Gemini, etc.) |
| Push-to-Talk | Working | Hold Space to talk; toggle/PTT mode selection in Settings |
| Provider Selection | Working | Switch between OpenAI, Gemini, and Local providers in Settings |
| WebSocket Reconnection | Working | Exponential backoff on connection loss |

## Hardware / HUP

| Feature | Status | Notes |
|:--------|:-------|:------|
| Device Registration | Working | Registry API, persistent device records |
| WebSocket Daemon Protocol | Working | Bidirectional command/telemetry channel |
| Hardware Mesh | Working | Request/response correlation across nodes |
| Wristband Adapter | Partial | Reference implementation; not production-hardened |
| Smart Home Adapter | Partial | Home Assistant bridge; basic control only |
| Robot Adapter | Scaffolding | Template only — no real actuator integration |
| Smart Glasses Adapter | Scaffolding | Template only — no hardware tested |
| Daemon Reliability (idempotency, retries, heartbeats) | Not Yet | No retry logic, no heartbeat monitoring |
| Safety Interlocks (E-stop, workspace bounds) | Not Yet | No emergency stop, no physical safety checks |

## Skills

| Feature | Status | Notes |
|:--------|:-------|:------|
| Computer Use | Working | Anthropic-style GUI primitives + coding tools |
| Browser Use | Working | CDP + Playwright, cookie persistence, network interception, iframe support |
| PDF | Working | Tables, images, OCR, metadata, layout preservation |
| Code Interpreter | Working | Docker sandbox with network/memory/CPU isolation |
| Search | Working | 7 providers with failover, caching, deduplication |
| Cron | Working | Timezone, priorities, missed-job catch-up, concurrent limits |

## GenUI / SDUI

| Feature | Status | Notes |
|:--------|:-------|:------|
| GenUI Generator | Working | LLM-driven UI component generation |
| Provider Registration | Working | Dynamic provider surface contracts |
| SDUI React Renderer | Working | Cards, maps, charts, forms, media |
| Provider Signing / Review | Not Yet | No code signing or review workflow |
| Third-Party Provider Marketplace | Not Yet | No discovery, distribution, or trust layer |

## Integrations

| Feature | Status | Notes |
|:--------|:-------|:------|
| Calendar (Google) | Working | Needs OAuth credentials configured |
| Email (Gmail / IMAP) | Working | Needs OAuth credentials configured |
| Telegram | Working | Needs bot token |
| Slack | Working | Needs app token |
| Discord | Working | Needs bot token |
| Spotify | Partial | Basic playback; limited API surface |
| Notion | Partial | Read/write pages; incomplete block support |
| Home Assistant | Partial | See Hardware — basic bridge only |
| Whoop | Working | Needs OAuth credentials configured |
| Oura | Working | Needs OAuth credentials configured |
| Push Notifications (FCM) | Working | Firebase Cloud Messaging |
| Push Notifications (APNs) | Working | JWT signing implemented |

## Autonomy & Security

| Feature | Status | Notes |
|:--------|:-------|:------|
| Strict / Hybrid / Loose Modes | Working | Enforced across all execution paths |
| ApprovalManager | Working | Blocks dangerous ops until user confirms |
| BlindVault | Working | Encrypted secret storage |
| SandboxPolicy | Partial | YAML loads but not enforced everywhere |
| dangerous_tools Surface Deny | Working | Hard deny list for high-risk tools |
| Docker Sandbox | Working | Container isolation; refuses host fallback when Docker unavailable |
| WASM Sandbox | Partial | Experimental; limited tool coverage |

## Frontend Quality

| Feature | Status | Notes |
|:--------|:-------|:------|
| ESLint (`react-hooks/exhaustive-deps`) | Working | Enforced in CI |
| React Error Boundary | Working | Wraps app root, catches render errors |
| DOMPurify (XSS sanitization) | Working | Applied to SDUI renderer |

## Clients

| Feature | Status | Notes |
|:--------|:-------|:------|
| Web Dashboard (React) | Working | Primary client; full feature coverage |
| Desktop App (Tauri) | Partial | Builds and runs; missing feature parity with web |
| iOS Bridge | Working | Location forwarding (CLLocationManager), QR code pairing (CIQRCodeGenerator), TLS (wss://), offline sensor queue |
| Android Bridge | Working | Camera capture (CameraX), location forwarding (FusedLocationProvider), QR code pairing (ZXing), wake word (RMS energy + duration gating) |

## Install & Ops

| Feature | Status | Notes |
|:--------|:-------|:------|
| `pip install feral-ai` | Working | PyPI live |
| `curl` one-liner | Working | Requires public repo access |
| Docker Compose | Working | Full stack in one command |
| CI (lint + tests + build) | Working | 1080 tests passing |
| `feral doctor` | Working | Environment diagnostics |
| Docs (Mintlify, 33 pages) | Working | Guides, SDK refs, API docs |

## Not Yet Built (Future)

| Feature | Status | Notes |
|:--------|:-------|:------|
| Baseline Learning Engine | Working | Biometric anomaly detection via statistical drift |
| Warehouse / Fleet Control | Not Yet | 100-camera, multi-robot orchestration |
| Native NixOS Module | Not Yet | Declarative system-level install |
| GenUI Provider Marketplace (with signing) | Not Yet | Trust + distribution layer for third-party UI providers |
| Formal Command State Machine for HUP | Not Yet | Deterministic state transitions for hardware commands |
| Multi-Tenant / RBAC | Not Yet | Role-based access, org-level isolation |
