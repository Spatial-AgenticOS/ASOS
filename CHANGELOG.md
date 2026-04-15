# Changelog

All notable changes to FERAL are documented here.

## [2026.4.16] - 2026-04-15

### Added
- Anthropic-style GUI Computer Use: 11 endpoints (screenshot, mouse_click, type_text, key_press, scroll, cursor_position, window_list, window_focus) with Retina DPI auto-detection
- Coding Tools: renamed from computer_use to clarify it's file/shell tools, not GUI control
- Browser session persistence: cookie save/restore across restarts via CDP
- Browser network interception: CDP-based request monitoring with filter
- Browser iframe support: list iframes, execute JS in iframe context
- Browser file download management: configurable download path via CDP
- Docker-first code interpreter sandbox: --network=none, --memory=512m, --cpus=1, --read-only
- PDF table extraction via PyMuPDF find_tables()
- PDF image extraction with base64 encoding
- PDF layout-preserving structured extraction (heading detection, block structure)
- PDF metadata extraction (title, author, dates, keywords)
- PDF OCR fallback (pytesseract + PyMuPDF built-in)
- 4 new search providers: Exa (semantic), SearXNG (self-hosted), Perplexity (AI-powered), Google CSE
- Search result caching (5-minute TTL, 200 entry max)
- Search result deduplication across providers
- Cron timezone support via zoneinfo
- Cron missed-job catch-up on boot
- Cron concurrent job execution limits
- Cron job priority levels (low/normal/high)
- Voice WebSocket reconnection with exponential backoff
- Push-to-talk mode (hold Space)
- Voice provider selection in Settings (OpenAI/Gemini/Local)
- Voice input mode selection (Toggle/Push-to-Talk)
- iOS location forwarding via CLLocationManager
- iOS QR code pairing with CIQRCodeGenerator
- iOS TLS (wss://) support
- iOS offline sensor queue (buffer when disconnected)
- Android camera capture via CameraX
- Android location forwarding via FusedLocationProvider
- Android QR code pairing via ZXing
- Android wake word detection improvement (RMS energy + duration gating)

### Fixed
- Retina DPI coordinate bug in agentic computer use (coordinates no longer 2x off on HiDPI displays)
- Linux support for agentic computer use (gnome-screenshot/scrot/import fallback)
- pyautogui typewrite/write logic for Unicode text (was backwards)
- Code interpreter Docker fallback when daemon is installed but not running
- Browser navigate now supports configurable wait strategies (load, domcontentloaded, networkidle)
- Agentic computer use now uses structured action parsing instead of fragile JSON extraction

### Changed
- Code interpreter always attempts Docker sandbox first, falls back to host with resource limits
- Search engine now supports 7 providers (up from 3): Tavily, Brave, DuckDuckGo, Exa, SearXNG, Perplexity, Google CSE
- PDF reader upgraded to v2.0 with tables, images, OCR, metadata, layout preservation
- Cron scheduler now sorts due jobs by priority DESC

## [1.2.1] - 2026-04-09

### Security
- Path traversal guard on catch-all WebUI route (`resolve()` + `is_relative_to()`)
- SQL injection whitelist on P2P sync table names (only `notes`, `episodes`, `conversations`, `knowledge`, `wiki_pages`)
- CORS restricted from wildcard `*` to `localhost:5173,localhost:9090`
- XSS prevention via DOMPurify sanitization on server-driven UI renderer
- Docker sandbox refuses host execution when Docker is unavailable
- Direct shell command injection disabled in daemon direct execution
- Default bind address hardened from `0.0.0.0` to `127.0.0.1`
- `NODE_API_KEY` no longer ships with a default value
- Gemini API key moved from URL query strings to request headers
- Shell command safety filter blocks dangerous patterns in skill executor
- Tool safety classification reordered: CONFIRM checked before AUTO

### Fixed
- Digital twin LLM response parsing (uses `extract_response()`)
- `register_instance` import order in `api/state.py`
- Handoff router mounted in `api/server.py`
- Proactive automation executor uses `get_implementation()` directly
- Sensor value chain: `is not None` checks replace falsy-zero `or` chains
- Knowledge triple overwrite: unique `note_{id}` subjects per note
- WebSocket node auth: accepts connection before closing with code 4003
- SQLite connection leaks: `try/finally` across 32 methods in 3 files
- FTS UPDATE triggers added for `notes`, `knowledge`, `entities` tables
- HLC string comparison replaced with parsed `(wall_ms, counter, node_id)` tuples
- DevicePairingStore consolidated to single instance in BrainState
- WebSocket reconnect leak: `unmountedRef` guard prevents post-unmount reconnection
- CommandPalette empty-state crash: guard against empty results
- Dashboard: `fetch()` replaces per-click WebSocket creation
- Ambient page keyboard hijack: skips input/textarea/contenteditable elements
- Settings Export/Clear Memory buttons wired with handlers
- WebSocket message format normalized to `{ hop, type, payload }`

### Added
- React Error Boundary wrapping the app root
- ESLint with `react-hooks/exhaustive-deps` rule for frontend
- 85 ToolRunner tests covering safety classification, enforcement, anti-loop, approval lifecycle
- `test_safety.py` rewritten to test production code instead of duplicated logic
- DOMPurify dependency for XSS sanitization

### Changed
- Test suite: 1080 tests passing (up from 992)
- Backend coverage threshold: 48%
- Frontend coverage thresholds: 20% statements, 15% branches/functions

## [1.2.0] - 2026-04-08

### Added
- Federated memory sync via CRDT and Hybrid Logical Clocks
- Session authentication and device pairing
- Web actions skill (browser automation with human confirmation)
- Workspace integrations (Google Drive, Google Contacts, Microsoft 365, expanded Slack)
- Cross-device context handoff between desktop and messaging channels
- Digital twin as first-class callable skill
- Health-triggered smart home automations via proactive engine
- Baseline learning engine for biometric anomaly detection
- Gemini Live v2 WebSocket API for voice
- Local STT (faster-whisper) and TTS (piper) pipeline
- Ollama vision model wiring (LLaVA/Moondream)
- Remote access with session auth and tunnel command
- Channel wiring: Telegram, Discord, Slack, WhatsApp bidirectional messaging
