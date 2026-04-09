# THEORA Capability Scorecard

This scorecard tracks parity and demo readiness across THEORA capability planes.

Legend:
- **Status**: `Shipped`, `Partial`, `Planned`
- **Works E2E**: `Yes`, `Partial`, `No`
- **Demo-ready**: `Yes`, `Partial`, `No`

| Feature | Status | Works E2E | Demo-ready | Notes |
|:--------|:-------|:----------|:-----------|:------|
| Voice (Realtime) | Shipped | Yes | Yes | Web client + brain realtime routing are integrated; depends on configured provider/key. |
| Voice (Classic) | Shipped | Yes | Partial | Works with standard STT/TTS path; less polished than realtime flow. |
| Wake Word | Shipped | Partial | Partial | Runtime support exists; device/environment-dependent in live demos. |
| Browser Use (CDP) | Shipped | Partial | Partial | Skill is registered and tested; requires CDP/browser runtime available at demo time. |
| Computer Use (shell/file/search/web) | Shipped | Yes | Yes | Core tool set is integrated in orchestrator + chat paths. |
| Memory (notes/episodes/knowledge graph) | Shipped | Yes | Yes | Local SQLite tiers operational and queryable. |
| Memory Wiki (compile/browse/search) | Shipped | Yes | Yes | UI overlay + API endpoints are live. |
| Memory Wiki ingest (repo/pdf/text) | Shipped | Yes | Yes | New ingest pipeline + endpoints + UI controls added. |
| TaskFlows runtime | Shipped | Yes | Yes | Persistent runner + API + client page with resume/cancel and step timelines. |
| Session snapshots/branch/restore | Shipped | Yes | Yes | API + chat toolbar UI added for snapshot, branch, restore. |
| Local Models (Ollama text) | Shipped | Yes | Yes | Preset-backed local text path. |
| Local Vision (Ollama VLM) | Shipped | Yes | Yes | `ollama_vision` preset and model capability guards implemented. |
| Provider presets | Shipped | Yes | Yes | Backend presets API + Settings picker. |
| Channels (Telegram/Discord/Slack/WhatsApp) | Partial | Partial | Partial | Channel manager and APIs exist; live connectivity depends on credentials/config. |
| Hardware node plane | Partial | Partial | Partial | Device registry and node WebSocket path are active; breadth depends on adapters. |
| GenUI renderer (cards/maps/charts/forms/media) | Shipped | Yes | Yes | Client renderer supports broad SDUI set plus provider surface contracts with fixed-layout caching. |
| Provider/channel status cards | Shipped | Yes | Yes | Dashboard now surfaces provider/channel/device status panel. |
| MCP Server | Shipped | Yes | Yes | `/mcp` endpoint and tool exposure are available. |
| MCP Client | Shipped | Partial | Partial | External MCP connectivity exists; demo readiness depends on remote servers. |
| Security (vault/sandbox/policy/approvals) | Shipped | Partial | Partial | Core controls are implemented; Linux permission plane is next-wave work. |
| Setup wizard (CLI + Web) | Shipped | Yes | Yes | Both setup paths are operational and route-gated in client. |
| Managed browser runtime | Planned | No | No | Explicitly sequenced in second-wave execution. |
| Linux permission plane | Planned | No | No | Sequenced in second-wave execution. |
| Installer and first boot productization | Planned | No | No | Sequenced after second-wave foundations stabilize. |

## Immediate Demo Baseline

Current baseline for the 10-beat platform demo:
- Setup and identity: ready
- Voice/text conversation: ready
- Computer/browser actions: ready (browser path is environment-dependent)
- Repo/PDF/text ingest into wiki: ready
- TaskFlow create/wait/resume: ready
- Session snapshot/branch/restore: ready
- Local vision + GenUI output: ready (requires Ollama VLM model installed)
- Hardware daemon telemetry + control: ready (requires a running daemon)
- Provider-defined GenUI surface: ready (no external dependencies)
