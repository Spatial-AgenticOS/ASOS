# FERAL-AI — Feature Stability Roadmap

**Document purpose.** Single source of truth for what exists in the FERAL-AI codebase, how mature each feature really is, and the concrete work required before we can claim **production-grade for 24/7 personal use**.

**Scope.** The FERAL product under `ASOS/` (this repository). Third-party trees outside `ASOS/` are excluded.

**Last updated.** 2026-04-24

**Audience.** FERAL core team. Internal. Not marketing copy.

**Method.** Repository scan (Glob/Grep/Read) + live `pytest` and `vitest` runs on this date + cross-reference of `.github/workflows/*` and `docs/mintlify/`. Every claim below is anchored to a `path:line` citation or a verifiable test/CI artifact.

---

## 0. Verification evidence (this run, 2026-04-24)

| Check | Result | Command / source |
|------|--------|--------------------|
| `feral-core` pytest | **1943 passed, 1 FAILED, 11 skipped** in 72.12s | `cd ASOS/feral-core && python -m pytest tests/ -q --no-cov` |
| Failing backend test | `test_mcp_full.py::TestFeralMCPServerCore::test_get_http_routes_exposes_mcp_endpoints` | terminal output, this run |
| `feral-client-v2` Vitest | **127 passed, 3 FAILED** in `Settings.test.jsx` (Twin section) | `npm run -s test` in `feral-client-v2/` |
| Failing v2 tests | `Settings.test.jsx:232` — `findByTestId('twin-disconnected')` did not appear; two adjacent assertions also failed | terminal output, this run |
| `feral-client-v2` test count | **138** `it(`/`test(` matches across `src/__tests__/**` (sum of file matches) | `rg --count "^\s*it\(|^\s*test\("` |
| `feral-client` (v1) test count | **51** | same query |
| `feral-extension` test count | **19** (background:6, content:8, options:5) | same query |
| `desktop` test count | **0** | same query |
| `feral-core` test files | **137** files under `tests/` | `find tests -maxdepth 1 -name '*.py' \| wc -l` |
| PyPI metadata | `Development Status :: 4 - Beta` | `feral-core/pyproject.toml:17–18` |
| Vitest coverage thresholds (v2) | `statements: 33`, `branches: 26`, `functions: 27`, `lines: 35` | `feral-client-v2/vitest.config.js:28–37` |

**Brutal honesty bar.** The README and the prior version of this document recorded `1926 passed / 0 failed` and `115 passed`. The actual current numbers are **1943 / 1 failed** and **127 passed / 3 failed** — i.e. main has regressions that block a “production-ready” claim. This document treats that as ground truth.

> **2026-04-25 reconciliation note.** When this roadmap was generated on 2026-04-24 the local `main` checkout was already 4 commits behind `origin/main`. After `git fetch`, the 3 vitest failures attributed to `Settings.test.jsx` Twin section were found to have been silently fixed on `origin/main` by commit `b4c3aec` (release `v2026.4.29`). W2 (PR #19) therefore did **not** re-introduce-then-fix the failures; instead it added 3 new regression tests for the corrected behaviour. The 1 backend `pytest` failure (`test_get_http_routes_exposes_mcp_endpoints`) is genuine and is closed by W3 (PR #20). After Wave-1 merges, the §0 table will read **1946 passed / 0 failed** (backend) and **130 passed / 0 failed** (v2 client). The reconciliation will be applied to this section in W3's merge commit.

**Caveats.**
- Mobile (`ios-app`, `android-app`), desktop (`desktop/`), `feral-registry`, `sdk/python`, `sdk/node`, `ts-node-sdk`, all node daemons, `phone-bridge`, and the `wasm-skill-*` templates were **not** re-executed for this document and are **not** in default CI. See §4.3.
- WS / live realtime / Playwright e2e numbers are point-in-time only and should be re-verified before any release claim.

---

## Phase 1 — Complete Feature Discovery

The list below is **repository-derived**, not README-derived. It enumerates every distinct user-facing surface, runtime capability, operational component, and packaging artifact discovered by exhaustive directory walk. Wherever something looks duplicated or contradictory, it is called out explicitly so it can be cleaned up.

### 1.1 HTTP API surface (`feral-core/api/`)

`api/server.py` is the FastAPI app shell. It defines: CORS, `RateLimitMiddleware` (per-IP RPM, loopback exempt), `APIKeyMiddleware` (Bearer `FERAL_API_KEY`, `_OPEN_PATHS` and `_OPEN_PATH_PREFIXES`), startup/shutdown hooks (`@app.on_event`), `/install-phone-bridge.sh`, `/metrics` (gated by `FERAL_METRICS_ENDPOINT`), `WebSocket /v1/session`, `WebSocket /v1/node`, `WebSocket /sync`, and a catch-all GET `/{full_path:path}` for static UI fallback.

Routers registered under `feral-core/api/routes/` (35 modules):

| Module | Responsibility | Sample endpoints |
|--------|----------------|------------------|
| `dashboard.py` | Identity, health, boot, dashboard, activity | `GET /api/identity/greeting`, `/health`, `/api/dashboard` |
| `auth.py` | Local key | `GET /api/auth/local-key` |
| `config.py` | Setup, config, identity, credentials | `GET /api/setup/status`, `POST /api/config/credentials` |
| `skills.py` | Skill registry CRUD + execution | `GET /skills`, `POST /api/skills/generate` |
| `memory.py` | Notes, episodes, search, KG, wiki ingest | `GET /api/memory/context`, `/internal/memory/*`, `/api/wiki/*` |
| `routines.py` | Cron-style routines | `POST /api/routines`, `/api/routines/{id}/pause` |
| `taskflows.py` | Long-running task flows | `POST /api/taskflows`, `/api/taskflows/{id}/resume` |
| `llm.py` | Provider catalog, switch, presets, probe, configure | `GET /api/llm/status`, `/api/llm/providers/{id}/models` |
| `audio.py` | STT/TTS provider discovery + config | `GET /api/audio/providers`, `POST /api/audio/config` |
| `genui.py` | A2UI provider registry + theme + render | `POST /api/genui/providers/{id}/surfaces/render` |
| `mcp.py` | MCP JSON-RPC over HTTP | `POST /mcp`, `/api/mcp/connect` |
| `channels.py` | Channel start + WhatsApp webhook | `POST /api/channels/start` |
| `conversations.py` | Multi-turn convo state, snapshots, branch/restore | `POST /api/session/snapshot`, `/api/session/restore` |
| `devices.py` | Connected/paired devices, pairing tokens, command ledger | `POST /api/devices/pair`, `/api/devices/pair/url`, `/api/devices/pair/complete` |
| `timeline.py` | Activity, automations, geofences, push, autonomy | `GET /api/timeline`, `POST /api/geofences` |
| `brain_rest.py` | **Aggregator only** — includes the four routers below | (no endpoints of its own) |
| `security_and_hardware.py` | Vault, permissions, audit, hardware execute/invoke/mesh | `POST /api/hardware/execute`, `/api/security/vault/store` |
| `integrations_webhooks.py` | OAuth start/callback, integration tokens, app webhook ingress | `POST /api/webhooks/{app_id}` |
| `marketplace_browser.py` | Skill marketplace + browser automation HTTP API | `POST /api/browser/snapshot` |
| `identity_nodes_sync.py` | Soul, memory.md, nodes, sync export/import | `GET /api/identity/soul`, `/api/sync/export` |
| `baseline.py` | Baseline metrics + alerts | `GET /api/baseline/summary` |
| `handoff.py` | Cross-device handoff | `POST /api/handoff` |
| `tool_genesis.py` | LLM-generated tool proposals | `POST /api/tool-genesis/generate` |
| `agent_mitosis.py` | Persona spawn / proposals / feedback | `POST /api/agents/spawn` |
| `intents.py` | Intent compile / list / today / complete | `POST /api/intents/compile` |
| `webhooks.py` | **Second** webhook system (in-memory) | `POST /api/webhooks/create`, `/api/webhooks/{id}/receive` |
| `ambient.py` | Ambient briefing / next event / wake-word | `GET /api/ambient/briefing` |
| `auth.py`, `personas.py`, `jobs.py` | Auth, personas, workflow packs, jobs | `GET /api/agents/personas`, `/api/jobs` |
| `consciousness.py` | Snapshot / restore / pause / heartbeat | `POST /api/consciousness/snapshot` |
| `about_me.py` | Identity / “soul” facts | `POST /api/about-me/{id}/confirm` |
| `ideas.py` | Ideation queue | `POST /api/ideas/{id}/accept` |
| `apps.py` | GenUI app install/manifest/open/dispatch | `POST /api/apps/install`, `/api/apps/{id}/dispatch` |
| `supervisor.py` | Audit log + global pause + record | `GET /api/supervisor/events`, `POST /api/supervisor/pause` |
| `twin.py` | Twin policies + approvals | `POST /api/twin/policies`, `/api/twin/approvals/{id}/approve` |

**Known duplications / overlaps** (carry into Phase 3 cleanup): two webhook subsystems (`webhooks.py` vs `integrations_webhooks.py`); `/api/devices` exists both in `devices.py` and `identity_nodes_sync.py`; `/api/info` and `/api/system/info` co-exist on `dashboard.py`.

### 1.2 Agent + cognition (`feral-core/agents/`)

35 files. Core loop and policy: `orchestrator.py`, `supervisor.py`, `tool_runner.py`, `refusal_handler.py`. LLM and providers: `llm_provider.py`, `local_inference.py`. Twin/persona: `digital_twin.py`, `twin_policy.py`, `agent_mitosis.py`, `persona_loader.py`, `identity_loader.py`. Multi-agent: `multi_agent.py`, `workers/{home,health,creative,research}.py`. Background: `proactive_engine.py`, `taskflow.py`, `intent_compiler.py`, `scheduler.py`, `learner.py`, `ideas_engine.py`, `tool_genesis.py`, `skill_generator.py`. Apps + UI: `app_registry.py`, `hybrid_genui.py`, `genui_generator.py`, `ui_handlers.py`, `response_delivery.py`. Other: `baseline_engine.py`, `context_engine.py`, `context_manager.py`, `self_model.py`, `session_handoff.py`, `direct_execution.py`, `about_me.py`.

### 1.3 Skills (`feral-core/skills/`)

`registry.py` (loaders + hot reload), `executor.py` (HTTP / in-process / WebSocket-to-daemon / WASM dispatch with vault). 21 implementations under `skills/impl/`: `perception_query`, `messaging_channels`, `workspace_scripts`, `self_introspection`, `gui_computer_use`, `web_search`, `pdf_reader`, `browser_use`, `code_interpreter`, `agentic_computer_use`, `coding_tools`, `robot_action`, `digital_twin_skill`, `web_actions`, `desktop_automation`, `system_settings`, `screen_capture`, `image_gen`, `computer_use`, `weather`, `subagent`. 25 JSON manifests under `skills/manifests/`, plus `WEATHER_SKILL` programmatic manifest in `feral-core/models/skill_manifest.py`.

### 1.4 Memory + sync (`feral-core/memory/`)

`store.py` (notes / episodes / about / vector backends), `knowledge_graph.py`, `consciousness.py` (re-entry/thoughts), `context_builder.py`, `embeddings.py`, `enhanced_search.py`, `wiki.py`, `ingest.py`, `notes_legacy.py`, `hlc.py` (hybrid logical clocks), `sync.py` (P2P WebSocket + WAL + optional mTLS + zeroconf). Vector backends in `memory/backends/{sqlite_vec,qdrant,chroma}.py`.

### 1.5 Voice + perception (`feral-core/voice/`, `feral-core/perception/`)

`voice/realtime_proxy.py` (OpenAI Realtime), `voice/gemini_realtime.py` (Gemini Live), `voice/router.py` (provider selection), `voice/personality.py`. Perception: `screen_loop.py`, `somatic.py`, `location.py`, `scene.py`, `fusion.py`, `change_detector.py`, `gesture.py`, `audio_pipeline.py`, `wake_word.py`.

### 1.6 Hardware + HUP (`feral-core/hardware/` + `feral-nodes/`)

Brain-side: `hardware/protocol.py` (HUP types), `hardware/mesh.py`, `hardware/command_contract.py`, `hardware/adapters/{wristband.py,smart_home.py,robot_arm.py}`. Spec: `feral-nodes/HUP_SPEC.md` (v1.1.0). Edge nodes are listed in §1.13.

### 1.7 Channels (`feral-core/channels/`)

`base.py` (Telegram, Discord, Slack, WhatsApp + `_http_with_retry` for 429/503), `matrix.py`, `signal.py`, `feishu.py`, `zalo.py`, `voice_call.py`, `push.py`. Matrix/Signal/Feishu/Zalo/voice_call are **stubs** (per their docstrings); push is a thin dispatcher.

### 1.8 Integrations (`feral-core/integrations/`)

`calendar.py`, `email.py`, `email_watcher.py`, `google_drive.py`, `google_contacts.py`, `microsoft365.py`, `home_assistant.py`, `mqtt_bridge.py`, `notion.py`, `oauth_manager.py`, `spotify.py`, `webhook_receiver.py`, `health_platforms.py`, `messaging.py`.

### 1.9 GenUI / A2UI / Apps (`feral-core/genui/`, `feral-core/agents/app_registry.py`, `feral-core/api/routes/apps.py`)

`genui/a2ui_protocol.py` (enum-based wire types — **TODO at line 121**: signed marketplace trust). `genui/generator.py` (provider/theme/component registry). `agents/app_registry.py` (install/uninstall, signature verification, persistence). `models/app_manifest.py` (Pydantic). v2 client renderer: `feral-client-v2/src/ui/SduiRenderer.jsx` + `applySduiPatches`.

### 1.10 Security + sandboxing (`feral-core/security/`)

`vault.py` (BlindVault — JSON in `~/.feral/credentials.json`, chmod 600, **not encrypted at rest**), `device_pairing.py` (SQLite token registry), `session_auth.py` (WS session token), `content_defense.py` (untrusted content boundaries), `dangerous_tools.py` (allow/deny), `fetch_guard.py` (SSRF), `sandbox_policy.py`, `exec_approvals.py` (SQLite approvals), `docker_sandbox.py`, `wasm_sandbox.py`, `wasm_host.py`.

### 1.11 CLI (`feral-core/cli/`)

`main.py` (`feral` entry), `setup_wizard.py` + `cli/setup/*` (interactive setup), `app_commands.py` (`feral app init/validate/install/uninstall`).

### 1.12 Observability + MCP (`feral-core/observability/`, `feral-core/mcp/`)

`observability/metrics.py` (OTel if installed, else in-memory; `init_metrics("feral")` in `server.py:96–97`; `/metrics` returns 404 unless `FERAL_METRICS_ENDPOINT=1` per `server.py:353–367`). MCP: `mcp/server.py`, `mcp/client.py` (subprocess `npx`), `mcp/registry.py`.

### 1.13 Edge nodes, daemons, bridges (`feral-nodes/`)

| Component | Path |
|----------|------|
| iOS app (HealthKit, QR, BLE, optional TLS pin) | `feral-nodes/ios-app/` |
| Android app (Health Connect, QR, foreground service) | `feral-nodes/android-app/` |
| iOS Node SDK (`FeralNodeSDK`, vendor adapter scaffolds) | `feral-nodes/ios-node-sdk/` |
| TS Node SDK (`@feral-ai/node-sdk` 1.1.0, Zod, CLI) | `feral-nodes/ts-node-sdk/` |
| Python Node SDK (`feral-node-sdk`, pairing CLI) | `feral-nodes/python-node-sdk/` |
| Wristband daemon (BLE GATT HR/SpO2 → HUP) | `feral-nodes/wristband_daemon/` |
| W300 daemon (UVC/OpenCV JPEG → HUP `video_frame`) | `feral-nodes/w300_daemon/` |
| Theora glasses daemon | `feral-nodes/theora_glasses_daemon/` (**empty in tree** — only `.pytest_cache`) |
| iOS bridge (legacy duplicate of `ios-app/Sources/FeralBridge`) | `feral-nodes/ios-bridge/` |
| Android bridge (AAR `bridge` + `sample`) | `feral-nodes/android-bridge/` |
| Phone bridge (Python ref daemon → `/v1/node`) | `feral-nodes/phone-bridge/` |
| Cookiecutter for vendor HUP daemons | `feral-nodes/templates/hardware-daemon/` |

### 1.14 Web clients

**`feral-client-v2/`** (primary) routes from `src/App.jsx:32–69`: `/setup`, `/setup/legacy`, `/pair`, `/`, `/chat`, `/forge`, `/skills`, `/memory`, `/memory/context`, `/wiki`, `/identity`, `/agents`, `/health`, `/webhooks`, `/geofences`, `/devices`, `/canvas` (GenUI), `/glass-brain`, `/oversight`, `/timeline`, `/flows`, `/intents`, `/marketplace`, `/apps`, `/apps/publish`, `/apps/:app_id`, `/settings`, `/ambient` (alias of `Home`), `*` → `/`. Shell components: `Shell.jsx`, `Dock.jsx`, `Menubar.jsx`, `VoiceOverlay.jsx`, `LiveOpsStream.jsx`. UI primitives: `BackButton.jsx`, `Pane.jsx`, `Glass.jsx`, `Modal.jsx`, `Tabs.jsx`, `EmptyState.jsx`, `StatusDot.jsx`, `DeviceQRCode.jsx`, `SduiRenderer.jsx`, `CodeEditor.jsx`, `Orb.jsx`. Components: `PairDeviceModal.jsx`, `ConsciousnessMindMap.jsx`, `PerceptionShare.jsx`, `ProactiveToast.jsx`, `ForYouToday.jsx`, `ResumeCockpit.jsx`, `SkillsLauncher.jsx`, `HubLauncher.jsx`, `StepBuilder.jsx`, `SelfEditors/index.jsx`. Browser-side HUP node: `src/node/BrowserNode.js`.

**`feral-client/`** (legacy v1) routes from `src/main.jsx:53–93`: `/setup`, `/`, `/chat`, `/settings`, `/taskflows`, `/timeline`, `/glass-brain`, `/glass`→redirect, `/brain`→redirect, `/intents`, `/ambient`, `*`. Pages include `SetupWizard.jsx`, `Dashboard.jsx`, `GlassBrain.jsx`, `TaskFlows.jsx`, `Timeline.jsx`, `Intents.jsx`, `Ambient.jsx`, `Settings.jsx`. Playwright spec at `feral-client/e2e/glass-brain.spec.js`.

**`feral-extension/`** Manifest V3 with `activeTab`, `storage`, `sidePanel`, `contextMenus`, `notifications`, host `*://*/*`. Entry scripts: `background.js`, `content.js`, `popup.{html,js}`, `sidepanel.{html,js}`, `options.html`.

### 1.15 Desktop (`desktop/`)

Tauri shell: `desktop/src-tauri/tauri.conf.json` identifier `ai.feral.desktop` version `2026.4.30`. `src-tauri/src/main.rs` (160–315) spawns `python -m api.server`, runs health probe on `FERAL_PUBLIC_BASE_URL`/`FERAL_BRAIN_URL`, defaults `http://localhost:9090`, registers tray, global shortcuts, autostart, and shuts the brain down on quit. Web entry: `desktop/index.html`, `src/main.js`, `floating-window.html`. **No Vitest tests** under `desktop/`.

### 1.16 Registry, SDKs, add-on, scripts, examples

- `feral-registry/` — FastAPI signed marketplace; routers `health/publish/catalog/item/flag/auth_github/blobs` under `/api/v1`. SQLite/PG via SQLAlchemy async. Alembic `0001_initial` + `0002_extended_kinds`. `Dockerfile`, `Procfile`, `fly.toml`. Tests: `tests/test_publish_flow.py`, `test_app_publish.py`, `test_seed_daemons.py`, `test_seed_personas_workflows.py` (~21 cases). **Not in CI.**
- `sdk/python/` (`feral-sdk` 0.1.0) and `sdk/node/` (`@feral/sdk` 0.1.0). **Zero tests in either.**
- `feral-ha-addon/` Home Assistant add-on, pinned to PyPI `feral-ai[llm]`; smoke imports inside the built image.
- `scripts/` — installer (`install.sh`), `bump_version.py`, `audit_routes.py`, `research_providers.py`, `build_webui.sh`, `demo_cli.sh`, `test_sync.sh`, `install-phone-bridge.sh`.
- `templates/wasm-skill-rust/`, `templates/wasm-skill-assemblyscript/` — WASM skill scaffolds.
- `examples/apps/{feral-messages,feral-rides}` — canonical GenUI sample apps used as fixtures.
- `benchmarks/run.py` — comparative bench harness; default `FERAL_BRAIN_URL=127.0.0.1:8000` (mismatches typical 9090 — operability footgun).

### 1.17 Demos (private, with public smoke contracts)

Private under `private/demos/`: `demo_mobile_ambient.sh`, `mobile_ambient.md`, `demo_genui_publisher.sh`, `genui_publisher.md`. Public smokes guarding the same HTTP contracts: `feral-core/tests/test_demo_mobile_ambient_smoke.py` (5 tests), `feral-core/tests/test_demo_genui_publisher_smoke.py` (5 tests).

### 1.18 CI/CD (`.github/workflows/`)

| File | Triggers | What it covers |
|------|----------|----------------|
| `ci.yml` | `push`/`PR` → `main` | feral-core ruff + pytest matrix Ubuntu/macOS × Py 3.11/3.12 with `--cov-fail-under=50`; feral-client + feral-client-v2 build + vitest coverage; syntax + skill-import boundary checks. `pip-audit`/`npm audit` are `continue-on-error: true`. |
| `publish.yml` | tag `v*`; `workflow_dispatch` (inputs: `skip_stage`, `dry_run`) | Staged release pipeline: **build** (wheel/sdist + in-tree pre-publish smoke) → **stage** (publish to TestPyPI, install from TestPyPI, runtime smoke against the uploaded artifact; gated by `testpypi-stage` environment) → **publish** (PyPI push + GitHub Release; gated by `pypi` environment). Canary smoke is driven by `scripts/release_wheel_smoke.py`. |
| `install-smoke.yml` | `workflow_run` after Release; `workflow_dispatch` | Post-prod `pip install feral-ai` on a matrix (Ubuntu/macOS × Py 3.11/3.12), verify CLI, assert webui_v2 in site-packages, uvicorn `/` smoke. Runs *after* the staged `publish.yml` has pushed to real PyPI. |
| `ha-addon.yml` | path-changed PR + `workflow_run` after Release + dispatch | Docker build for HA add-on + `import feral_ai` smoke. |
| `desktop.yml` | **`workflow_dispatch` only** | Tauri debug build matrix (PR trigger removed in 2026.4.18-dev). |
| `provider-research.yml` | **`workflow_dispatch` only** | Refresh `feral-core/providers/model_catalog.json` (cron removed). |

**Not on per-commit CI**: mobile (`ios-app`, `android-app`, all SDKs and node daemons), `feral-registry`, `sdk/python`, `sdk/node`, `desktop`, `benchmarks/`, `templates/wasm-skill-*`. The boundaries of what is and is not gated by `main` CI are summarized in §4.3.

### 1.19 Documentation (`docs/mintlify/`)

Sections in `docs.json`: Overview, Getting Started, Guides, Marketplace, Hardware, Channels, Connectivity, Native Apps, Operations, SDKs, Reference, Help, Community. Key reference pages: `reference/{api,websocket,environment,cli,a2ui-schema}.mdx`. **Drift risk found:** `hardware/hup-spec.mdx` reads “HUP v1.0.0” while the canonical `feral-nodes/HUP_SPEC.md` is v1.1.0; `reference/websocket.mdx` lists `/v1/node on port 9091` while typical Brain runs on 9090.

---

## Phase 2 — Deep-Dive Analysis

Features are grouped by **domain** to keep this readable; every Phase 1 inventory item maps into one of the domains below. Each domain block follows the same 10-field shape.

> **Stability legend.** *Research Prototype* — only works in a controlled demo. *Alpha* — many bugs, limited testing, no production hardening. *Beta* — common cases solid, edges fail. *Production-Ready (single-user local)* — well-tested, monitored, secure, documented enough to run on your own machine 24/7. *Battle-Hardened* — proven at scale over time. We do not claim *Battle-Hardened* anywhere in this document.

### 2.1 API gateway, auth, abuse controls

**Implementation.** `APIKeyMiddleware` enforces Bearer `FERAL_API_KEY` for HTTP except a hard-coded set of open paths (`/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`, `/api/auth/local-key`, `/api/boot-report`, `/api/devices/pair/url`, `/api/devices/pair/qr`, `/api/devices/pair/complete`, etc.) and accepts localhost when `local_bypass_enabled()`. Webhook receive paths and **all WebSockets** skip the middleware. Source: `feral-core/api/server.py:221–278`.

```115:115:feral-core/api/server.py
RATE_LIMIT_RPM = int(os.getenv("FERAL_RATE_LIMIT_RPM", "1200"))
```

Rate limit (`server.py:112–187`) is **in-process**, per-IP, with a hard cap `_RATE_LIMIT_MAX_KEYS = 10_000` and a long exempt-prefix list (heavy-poll paths, supervisor, twin, pair, etc.). Exceed → 429 JSON.

**Tests.** `test_api_*`, `test_server_websocket.py`, `test_api_parity.py`, `test_pair_flows.py` (14 cases). Live count via fresh run: 1943 backend tests overall.

**Error handling.** 401 JSON for bad/missing key. WebSocket `/v1/node` accepts the socket *then* closes 4003 if the API key is unknown (`server.py:772–794`).

**Operability.** `FERAL_API_KEY`, `FERAL_RATE_LIMIT_RPM`, `FERAL_CORS_ORIGINS`, `FERAL_METRICS_ENDPOINT`, `NODE_API_KEY`, `FERAL_LOCAL_BYPASS`, `FERAL_SESSION_AUTH`. Documented at `docs/mintlify/reference/environment.mdx`. No `feral_api_auth_failures_total` metric today.

**External deps.** None beyond FastAPI/Starlette/uvicorn.

**Limitations.**
- Rate limit store is in-memory: not safe for multi-instance behind LB.
- WebSocket auth happens after `accept()`; close 4003 follows. Functionally correct, but a smaller target should use early close.
- Two webhook subsystems coexist (`webhooks.py` and `integrations_webhooks.py`).
- `@app.on_event` lifecycle is FastAPI-deprecated.

**Minimal/Partial/Full.** **Full** for single-node local brain; **Partial** for HA / multi-tenant.

**Stability.** **Beta**.

**P0/P1/P2.**
- **P0** Test that fails when a new route is accidentally left out of API-key enforcement (snapshot `_OPEN_PATHS` and prefixes against the live route table).
- **P0** Move to FastAPI `lifespan` (`@app.on_event` deprecated); regression test for startup/shutdown.
- **P0** Document and ship `feral key rotate` CLI for `~/.feral/api_key` rotation without bricking clients.
- **P1** Optional Redis-backed rate-limit store behind a flag; emit `feral_rate_limit_drops_total{ip}` and `feral_api_auth_failures_total{reason}`.
- **P1** Migrate WebSocket auth to early-reject (no `accept` before key verify).
- **P2** Per-route SLOs in Grafana.

### 2.2 LLM, audio, model catalog

**Implementation.** `providers/catalog.py` is the single registry; bundled `providers/model_catalog.json`. `agents/llm_provider.py` provides streaming, retries (`_retry_llm_call`, `llm_provider.py:34–44`), and `chat_with_failover` across providers. Adapters in `providers/{openai,anthropic,gemini,bedrock,deepseek,fireworks,groq,lmstudio,ollama,openrouter,together}_provider.py` (12). Anthropic has **no** public `/v1/models` so its adapter returns a hardcoded list. Disk cache TTL is 6 hours (`DEFAULT_CACHE_TTL_SECONDS` in `providers/catalog.py`).

**Tests.** `test_provider_catalog.py` (24), `test_providers.py` (7), `test_llm_provider.py` (9), `test_llm_failover.py` (11), `test_api_llm_providers.py` (16), `test_provider_lmstudio.py`, `test_llm_provider_catalog_wiring.py`, `test_llm_catalog_live.py` (9, may skip without keys). Metrics emitted: `feral.llm.calls_total`, `feral.llm.errors_total`, `feral.llm.latency` (`llm_provider.py:413–428`, `:1201–1208`).

**Error handling.** Per-provider transient retries; fail-over rotates providers; user-facing strings on cache miss (e.g. `_format_refresh_error` in catalog).

**Operability.** `FERAL_LLM_PROVIDER`, `FERAL_LLM_MODEL`, plus per-provider key envs. `provider-research.yml` exists but is `workflow_dispatch` only — there is **no scheduled refresh of `model_catalog.json`** today.

**External deps.** Provider HTTP APIs; their schema/model names drift constantly.

**Limitations.**
- No live provider model refresh runs on a schedule; `model_catalog.json` lags new model launches (this is the root cause of the user-reported “GPT-5.5 not in dropdown” issue — see Appendix A.1).
- Anthropic catalog is hardcoded.
- No circuit breaker beyond per-call retry/failover; no token/cost accounting metrics.

**Minimal/Partial/Full.** **Full** for the supported adapters.

**Stability.** **Beta** (mechanics are solid; provider drift is the open risk).

**P0/P1/P2.**
- **P0** Re-enable a daily/weekly cron on `provider-research.yml` (or a small in-Brain refresh job) so `/api/llm/providers/{id}/models` returns fresh names without manual repo PRs.
- **P0** Contract tests with recorded fixtures per provider; nightly live probe gated by `live` markers.
- **P0** Token/cost accounting metrics (`feral_llm_tokens_total{provider,model,direction}`, `feral_llm_cost_usd_total`).
- **P1** Simple circuit breaker in `llm_provider.py` (open after error rate > threshold for 60s).
- **P1** Versioned schema for `model_catalog.json` and a JSON-Schema check in CI.
- **P2** Prompt-injection regression suite for tool-use.

### 2.3 Orchestrator, tools, autonomy

**Implementation.** `agents/orchestrator.py` (~1.4k lines): tool routing, mitosis hooks, streaming, `ALWAYS_INCLUDE_SKILLS` set (`:84–101`), feature flags `FERAL_MULTI_AGENT`, `FERAL_VISION_ENABLED`, `FERAL_PROACTIVE`, `FERAL_STREAMING`, `FERAL_MAX_ITERATIONS` (`:167–183`). v2026.4.28 added `asyncio.gather`-based parallel tool dispatch behind `Semaphore(FERAL_MAX_PARALLEL_TOOLS=6)` and per-session `asyncio.Lock`. Supervisor wraps four entry points (`agents/supervisor.py`, see CHANGELOG `[2026.4.28]`).

`agents/tool_runner.py`: `VALID_AUTONOMY_MODES` (`:26–52`), `classify_safety` (`:59–90`), `ApprovalManager` integration (`:18–49`, `:130–145`).

**Tests.** `test_tool_runner.py` (57 `def test_`), `test_safety.py` (16), `test_sandbox_policy.py` (14), `test_orchestrator.py` (8), `test_orchestrator_deep.py` (18), `test_parallel_tool_calls.py` (7), `test_app_action_dispatch.py`, `test_refusal_handler.py` (34), `test_multi_agent.py` (39).

**Error handling.** Refusal handler returns structured denials; mitosis routing wrapped in try/except; per-session lock prevents history corruption.

**Operability.** Logger `feral.orchestrator`. Source-tagged Supervisor records (`source=cron|proactive|web|node`) since v2026.4.28.

**External deps.** Provider HTTP, WebSocket clients (daemons), `httpx`.

**Limitations.**
- Always-include skill list inflates every turn’s tool count.
- `ContextManager` `max_messages=15` is hardcoded at construction.
- Backend currently has **one failing test** (`test_mcp_full.py::TestFeralMCPServerCore::test_get_http_routes_exposes_mcp_endpoints`) — this is in MCP wiring but it sits on the orchestrator-adjacent route table.

**Minimal/Partial/Full.** **Full**.

**Stability.** **Beta**, trending Production-Ready.

**P0/P1/P2.**
- **P0** Fix `test_mcp_full.py::test_get_http_routes_exposes_mcp_endpoints` so main is green.
- **P0** Property-based test on `_session_locks` (concurrent sessions, eviction, disconnect).
- **P0** CI matrix for all `FERAL_*` orchestrator toggles; document the matrix in `docs/orchestration.md`.
- **P1** Fuzz `classify_safety` on tool-name renames; confirm unknown tools default to CONFIRM (`tool_runner.py:89–90`).
- **P2** Split `orchestrator.py` for maintainability (no behavior change).

### 2.4 Memory, sync, consciousness, KG

**Implementation.** `memory/store.py` (notes/episodes/about/vectors), `knowledge_graph.py` (graph layer), `consciousness.py` (snapshot/re-entry, `paused` bridge), `context_builder.py`, `embeddings.py`, `enhanced_search.py`, `wiki.py`, `ingest.py`. `sync.py` is WebSocket P2P with optional mTLS (`FERAL_SYNC_PASSPHRASE`, `FERAL_SYNC_PORT`, `FERAL_SYNC_PEERS`, mDNS), `_MDNS_DISCOVERY_TIMEOUT = 30`. WAL via SQLite. `hlc.py` (hybrid logical clocks).

**Tests.** `test_memory.py` (24), `test_memory_backends.py` (3), `test_memory_filter_enforced.py` (4), `test_about_me_store.py` (27), `test_sync.py` (13), `test_sync_fuzz.py` (7, 100-op random with partial delivery and 3-node flap), `test_knowledge_graph.py` (9), `test_consciousness_reentry.py` (5), `test_consciousness_snapshot_restore.py` (13), `test_embeddings.py` (10), `test_memory_ingest.py` (2 — **thin**), `test_memory_context_per_turn.py` (5).

**Error handling.** Sync handles passphrase/TLS failure paths; WAL persists on disk. Vault corruption is renamed `.corrupt` and starts empty (`security/vault.py:46–63`).

**Operability.** Backups/restore are not yet a documented runbook; sync is documented at `docs/mintlify/guides/federated-sync.mdx`.

**External deps.** Optional `zeroconf`, optional Chroma/Qdrant; SQLite WAL on disk.

**Limitations.**
- `enhanced_search` has **no dedicated test file**.
- `wiki` and `ingest` coverage are thin (2 tests for ingest).
- `memory_backends` has 3 tests for 3 backends — Chroma/Qdrant CI paths are not exercised.
- Sync over the public internet (vs LAN) is not first-class.

**Minimal/Partial/Full.** **Full** on local+LAN with sqlite-vec; **Partial** for alternate vector backends.

**Stability.** **Beta**.

**P0/P1/P2.**
- **P0** Chaos tests: kill peer mid-handshake; corrupt WAL; disk full during append; static peer unreachable.
- **P0** Backup/restore runbook + `feral memory backup`/`restore` CLI; round-trip test in CI.
- **P0** Containerized optional jobs for Chroma/Qdrant under a CI matrix flag.
- **P1** mTLS rotation (short-lived certs) and renewal docs.
- **P1** Property tests at 10k ops with time bounds; ADR documenting CRDT/HLC merge semantics.
- **P1** Add `test_enhanced_search.py`, expand `test_memory_ingest.py` (OCR, huge files, binary).
- **P2** Hash pairing and sync tokens at rest.

### 2.5 Skills + sandboxing

**Implementation.** `skills/registry.py` discovers manifests in repo + `~/.feral/skills`; supports hot reload. `skills/executor.py` dispatches HTTP / Python `impl.py` / WebSocket-to-daemon / WASM, with blind vault for credentials (`executor.py:62–76`, `:111–119`). Metrics: `feral.skill.invocations_total`, `feral.skill.exec_latency_ms`. WASM runtime gated by `WASMSandbox.available`.

**Tests.** Per-skill: `test_perception_query_skill.py` (19), `test_channels_base.py` (~20), `test_workspace_integrations.py` (22), `test_state.py` (18), `test_gui_computer_use.py` (19), `test_web_search.py` (6), `test_pdf_reader.py` (7), `test_browser_use.py` (9), `test_code_interpreter.py` (3), `test_web_actions.py` (12), `test_track0_fixes.py` (3), `test_screen_capture.py` (2 — **thin**), `test_subagent.py` (2 — **thin**), `test_hardware.py` (13). Registry: `test_skill_registry.py` (5 — **thin vs surface area**).

**Error handling.** Python `impl` errors caught and returned as 500 JSON (`executor.py:145–147`). HTTP timeouts via `httpx.AsyncClient(timeout=15.0)`.

**Operability.** Per-skill envs: `FERAL_KEY_*`, `FERAL_GUI_MAX_ACTIONS_PER_S`, `FERAL_CDP_HOST`/`PORT`, `FERAL_ARTIFACTS_DIR`, `FERAL_VLM_*`, `FERAL_SANDBOX_BASH`.

**External deps.** Each skill has its own (Playwright, OpenCV, vendor APIs, Docker, etc.).

**Limitations.**
- WASM has the runtime but **no shipped golden `.wasm` skill** in-repo; the path is essentially unproven end-to-end.
- Docker sandbox depends on local Docker; **no dedicated `test_docker_sandbox.py`**.
- `tool_genesis.py` AST allowlist is not a substitute for real isolation; generated code still risky.
- `screen_capture` and `subagent` have only 2 tests each.

**Minimal/Partial/Full.** **Partial** for the WASM/marketplace path; **Full** for in-process Python skills.

**Stability.** **Beta** for Python skills; **Alpha** for WASM and `tool_genesis`.

**P0/P1/P2.**
- **P0** Ship one golden WASM skill and an end-to-end test that loads, executes, and validates output, **or** mark WASM “experimental” in the UI.
- **P0** CI job that exercises Docker sandbox via dind for `code_interpreter`.
- **P0** Tighten `tool_genesis.py`: deny-network-by-default for generated code unless explicitly approved; E2E reject-on-unsafe-AST test.
- **P0** Raise minimum tests for `screen_capture`, `subagent`, `code_interpreter` to ≥10 each.
- **P1** Resource cgroups / CPU quota validation per OS.
- **P2** Marketplace signing for skills (closes A2UI TODO at `genui/a2ui_protocol.py:121`).

### 2.6 GenUI / A2UI / Apps

**Implementation.** `genui/a2ui_protocol.py` defines wire types. `genui/generator.py` exposes provider/theme/component registry over `/api/genui/*`. `agents/app_registry.py` handles install/uninstall and persistence. `agents/hybrid_genui.py` combines authored templates + LLM generation + cache. v2 client: `feral-client-v2/src/ui/SduiRenderer.jsx`, `applySduiPatches`, `pages/AppSurface.jsx`. Two example apps shipped in `examples/apps/{feral-messages,feral-rides}`.

**Tests.** `test_app_registry.py` (22), `test_genui.py` (8), `test_hybrid_genui.py` (12), `test_a2ui_contract.py` (15), `test_api_apps.py`, `test_demo_genui_publisher_smoke.py` (5). v2: `Apps.test.jsx` (2), `AppSurface.test.jsx` (1), `AppsPublish` covered in `tab_pages.test.jsx`.

**Error handling.** Hybrid generator falls back to authored template if LLM raises. Manifest schema validated by Pydantic before install.

**Operability.** `feral app init/validate/install/uninstall` CLI (`cli/app_commands.py`).

**External deps.** LLM (for generative paths); third-party app code (for marketplace).

**Limitations.**
- `genui/a2ui_protocol.py:121` carries `TODO(v2): signed marketplace trust`. Until that lands, third-party apps are an **uncontrolled trust surface**.
- `AppSurface` tests are minimal (single mount test).

**Minimal/Partial/Full.** **Full** for first-party apps, **Partial** for third-party at scale.

**Stability.** **Beta** (first-party), **Alpha** (third-party marketplace).

**P0/P1/P2.**
- **P0** Implement the signed-trust path the TODO refers to: per-app signing key, signature verification on install, surface-level capability declarations.
- **P0** Sandbox the `AppSurface` rendering pipeline (CSP, no eval, network allowlist per manifest).
- **P1** Negative tests for malicious manifests (oversized fields, deeply nested SDUI, hostile placeholders).
- **P2** Visual regression suite for SDUI rendering (Chromatic-style).

### 2.7 Digital twin, personas, mitosis

**Implementation.** `agents/digital_twin.py` (LLM fallbacks per twin domain, JSON-parse guards `:438–440`), `agents/twin_policy.py` (mode/time-window/daily-cap policies), `api/routes/twin.py`, `agents/agent_mitosis.py` + `api/routes/agent_mitosis.py`. Personas in `agents/personas/*.json`.

**Tests.** `test_digital_twin.py` (16), `test_digital_twin_integration.py` (5), `test_twin_honesty.py` (7), `test_twin_on_behalf.py` (23), `test_persona_loader.py` (4), `test_spawn_from_persona_body.py` (4), `test_agent_mitosis_integration.py` (12), `test_api_personas.py` (7).

**Error handling.** Per-domain user-facing errors instructing the user to add a provider/fallback.

**Operability.** Twin endpoints exempt from rate limiting. Supervisor records all twin-driven actions since v2026.4.28.

**External deps.** Per-domain integrations (calendar, email, etc.).

**Limitations.** Twin Settings UI shows the “Pause all actions” affordance and per-domain rows even when there are no policies and no executors — see Appendix A.5. The 3 v2 test failures this run land in `Settings.test.jsx` Twin section.

**Minimal/Partial/Full.** **Partial**.

**Stability.** **Beta** for backend; **Alpha** for the v2 Settings UX given the failing tests.

**P0/P1/P2.**
- **P0** Fix the 3 failing `Settings.test.jsx` Twin assertions; make the Twin section render the kill-switch only when at least one executor is connected (or label it explicitly as “(no executors yet)” to remove the “theatre” the user reported).
- **P0** Contract tests for every twin domain’s error shape returned to the client.
- **P1** Audit the Twin policy text against acceptable use; ADR explaining what FERAL **will not** do on behalf of the user.
- **P2** Idempotency + rollback tests for mitosis spawn failures.

### 2.8 Proactive, taskflows, intents, ideas, about-me, jobs, supervisor

**Implementation.** `agents/proactive_engine.py` (`increment("feral.proactive.trigger_total", ...)` at `:469`), `agents/taskflow.py` (long flows), `agents/intent_compiler.py` (SQLite `intent_plans` schema at `:49–68`), `agents/ideas_engine.py`, `agents/about_me.py`, `agents/scheduler.py` (`fcntl` file lock at `:34–64`), `agents/supervisor.py` (now wraps `handle_command`, `handle_command_stream`, `handle_daemon_result`, plus one more — see CHANGELOG `[2026.4.28]`).

**Tests.** `test_proactive_engine.py` (24), `test_taskflow.py` (2 — **thin**), `test_intent_compiler_integration.py` (12), `test_ideas_engine.py` (21), `test_api_ideas.py` (8), `test_about_me_store.py` (27), `test_api_about_me.py` (15), `test_consciousness_*` (5+13), `test_supervisor.py` (16), `test_api_jobs_aggregates.py`, `test_scheduler_fuzz.py` (15).

**Error handling.** Scheduler raises `RuntimeError` on unobtainable lock; proactive automations record per-action audit rows with `source="proactive"`.

**Operability.** `FERAL_PROACTIVE`. Supervisor source tags: `cron`, `proactive`, `web`, `node`.

**Limitations.** `taskflow` has two tests; `learner.py` extraction interval `_extract_interval = 5` is hardcoded (`learner.py:65–66`); `self_model.py` swallows subsystem failures silently.

**Stability.** **Beta** for the supervisor + scheduler + proactive paths; **Alpha** for taskflows and the learner.

**P0/P1/P2.**
- **P0** Broaden `test_taskflow.py` to cover failure mid-chain, timeout, partial completion, resume.
- **P0** Surface a metric/alert when supervisor audit insert fails (currently swallowed).
- **P1** Property test scheduler under contention (multiple processes racing for the lock).
- **P1** Convert `self_model.py` silent passes into structured error counts; emit `feral_self_model_subsystem_errors_total{subsystem,reason}`.

### 2.9 Voice (OpenAI Realtime, Gemini Live, router, wake word)

**Implementation.** `voice/realtime_proxy.py` (OpenAI; `_connect_with_retry` referenced `:90–95`), `voice/gemini_realtime.py` (Gemini Live; per-chunk debug latency log).

```135:144:feral-core/voice/gemini_realtime.py
        t0 = time.monotonic()
        await self._send({
            "realtimeInput": {
                "audio": {
                    "data": audio_b64,
                    "mimeType": f"audio/pcm;rate={INPUT_SAMPLE_RATE}",
                },
            },
        })
        logger.debug("audio_chunk sent session=%s latency_ms=%.1f", self.session_id, (time.monotonic() - t0) * 1000)
```

`voice/router.py` selects Gemini vs OpenAI realtime vs whisper-pipeline (`FERAL_VOICE_PROVIDER` at `:17–20`, `:75–98`). Wake-word optional (`perception/wake_word.py`, `openwakeword`).

**Tests.** `test_realtime_proxy.py` (10), `test_voice.py` (12), `test_voice_router.py` (11), `test_voice_integration.py` (6), `test_api_audio.py` (9), `test_voice_deeper.py` (62), `test_audio_pipeline.py` (12).

**Error handling.** Reconnect patterns; wake-word gating.

**Operability.** `FERAL_VOICE_*`, `FERAL_WAKE_WORD`, `FERAL_GEMINI_LIVE_MODEL`, `FERAL_STT_*`, `FERAL_TTS_*` (in `audio_pipeline.py:57–201`).

**Limitations.** Wake-word default is inconsistent: `perception/wake_word.py:56` defaults `FERAL_WAKE_WORD` to `"false"`, but `api/state.py:375–377` constructs it with `"true"`. Behavior depends on instantiation path. Per-chunk latency exists only as `logger.debug`, never aggregated to a metric histogram.

**Stability.** **Beta** (provider SLAs, mic permissions, network flakiness dominate).

**P0/P1/P2.**
- **P0** Unify the `FERAL_WAKE_WORD` default and document it; test both construction paths.
- **P0** 1-hour soak test with forced reconnects; assert no handle leaks.
- **P0** Confirm wake-word path in a hardware lab (not only mocks) on each supported OS.
- **P1** Aggregate p50/p95/p99 audio-chunk latency into `feral_voice_chunk_latency_ms` histogram (not just `logger.debug`).
- **P1** Contract test for `OpenAI-Beta: realtime=v1` header and model query param.
- **P2** Multi-language wake-word validation.

### 2.10 Computer / browser / PDF / search / image skills

**Implementation.** `skills/impl/gui_computer_use.py` (Retina/DPI scaling), `browser_use.py` (Playwright via CDP), `pdf_reader.py`, `web_search.py` (SearchProvider ABC; multi-provider), `image_gen.py`. `coding_tools.py` and `computer_use.py` gate bash via `FERAL_SANDBOX_BASH`.

**Tests.** See §2.5 table. `test_browser_use_integration.py` is gated by `FERAL_BROWSER_TEST=1`.

**Error handling.** Playwright timeouts, CDP reconnect; OS-specific GUI automation is inherently flaky.

**Stability.** **Beta**.

**P0/P1/P2.**
- **P0** Sandbox browser profiles per skill invocation.
- **P1** Direct unit tests for `dangerous_tools.py`, `content_defense.py`, `fetch_guard.py` (these have no dedicated test files today — see §2.16).

### 2.11 Channels (Telegram, Discord, Slack, WhatsApp + long-tail)

**Implementation.** `channels/base.py` is one ~900-line module containing all four first-class messengers + `_http_with_retry`:

```165:174:feral-core/channels/base.py
    async def _http_with_retry(client, method: str, url: str, **kw):
        """Exponential-backoff retry for 429 / 503 responses (up to 3 attempts)."""
        ...
            if hasattr(r, "status_code") and r.status_code in (429, 503):
```

Long-tail channels: `matrix.py`, `signal.py`, `feishu.py`, `zalo.py`, `voice_call.py` are stubs (their docstrings are TODO checklists). `push.py` is a thin FCM/APNs dispatcher.

**Tests.** `test_channels_base.py` (~20), `test_channels_deep.py` (13), `test_channel_matrix_stub.py` (3), `test_channel_stubs.py` (parametrized).

**Stability.** **Beta** for first-class four; **Alpha → Research Prototype** for long-tail channels (Matrix etc.).

**P0/P1/P2.**
- **P0** 24-hour soak test of Telegram/Slack/Discord against live personal bots in a staging brain.
- **P0** OAuth token refresh failure drills for integrations that need it.
- **P1** Webhook signature rotation tests.
- **P2** UI label long-tail channels as “experimental” or remove from settings until implemented.

### 2.12 Integrations (calendar, email, M365, Google, OAuth, etc.)

**Implementation.** One file per integration under `feral-core/integrations/`; `oauth_manager.py` handles authorization grants for the OAuth-using ones.

**Tests.** Mostly mocked HTTP. Direct files are sparse; many integrations only get coverage through `test_webhooks.py` (14) or `test_setup_wizard.py` (24).

**Stability.** **Alpha → Beta** depending on provider.

**P0/P1/P2.**
- **P0** OAuth refresh failure tests with VCR-style fixtures per provider.
- **P1** Per-integration webhook signature verification audit.

### 2.13 Hardware (HUP), devices, mesh

**Implementation.** Brain-side: `hardware/protocol.py`, `hardware/mesh.py`, `hardware/command_contract.py`. HUP spec at `feral-nodes/HUP_SPEC.md` (v1.1.0). `api/routes/devices.py` exposes paired devices, pair URL/QR/complete, and a command ledger. `security/device_pairing.py` is the SQLite token registry. WebSocket `/v1/node` accepts API key from query, header, x-api-key, or `Sec-WebSocket-Protocol: feral-token-...` (`server.py:772–794`).

**Tests.** `test_hardware.py`, `test_hardware_mesh.py`, `test_hardware_adapters.py` (9), `test_hup_v1_1_*.py`, `test_pair_flows.py` (14), `test_no_phone_placeholder.py`.

**Error handling.** Mesh ledger state machine; oversized HUP frames dropped.

**Operability.** `NODE_API_KEY` (legacy fallback), `FERAL_HOME` for DB path. Pair endpoints rate-limit exempt.

**Limitations.** Pairing tokens stored in SQLite **plaintext** (high-entropy random, but a hash-at-rest is cheap). `theora_glasses_daemon` directory is empty in tree.

**Stability.** **Beta** for HUP protocol + Brain side; **Alpha** for any unattended physical hardware path.

**P0/P1/P2.**
- **P0** Hash pairing tokens at rest (compare digest), and add token TTL in schema.
- **P0** Move `/v1/node` auth to before `accept()` — close 401 without `accept`.
- **P0** Remove or implement `feral-nodes/theora_glasses_daemon/`; today it ships only a stale `.pytest_cache`.
- **P1** Fuzz HUP message decoder with malformed frames.

### 2.14 Observability + metrics

**Implementation.** `observability/metrics.py` provides `init_metrics`, `increment`, `measure`, `observe`. Uses OTel if installed, else in-memory. `/metrics` is gated:

```353:367:feral-core/api/server.py
@app.get("/metrics")
async def metrics_endpoint():
    if os.getenv("FERAL_METRICS_ENDPOINT", "").strip() not in ("1", "true"):
        return JSONResponse({"error": "Metrics endpoint disabled. Set FERAL_METRICS_ENDPOINT=1"}, status_code=404)
```

**Tests.** `test_metrics.py` (10).

**Limitations.** Most cognition modules emit no metrics. Today only `agents/llm_provider.py`, `agents/proactive_engine.py`, `channels/base.py`, `skills/executor.py` emit. There are no SLO definitions, no Grafana dashboards in-repo, no alert rules.

**Stability.** Library: **Production-Ready**. Coverage of emissions: **Alpha**.

**P0/P1/P2.**
- **P0** Emit metrics from `memory/sync.py`, `mcp/`, `tool_runner` denials, `refusal_handler` fallbacks, supervisor audit failures, rate-limit drops, auth failures.
- **P0** Ship a default Grafana dashboard JSON in-repo plus example Prometheus alert rules.
- **P1** Define p50/p95/p99 latency histograms for: end-to-end turn (user message → first token), per-tool call, per-skill, per-provider.

### 2.15 Web client v2

**Implementation.** 28 pages, comprehensive shell (`Shell`, `Dock`, `Menubar`, `VoiceOverlay`, `LiveOpsStream`), 11 UI primitives (`Modal`, `BackButton`, `Pane`, `Glass`, `EmptyState`, `StatusDot`, `DeviceQRCode`, `SduiRenderer`, `CodeEditor`, `Orb`, `Tabs`). 138 vitest assertions across `src/__tests__/**`.

```28:37:feral-client-v2/vitest.config.js
      thresholds: {
        // Stage 5.4 (Modal/CodeEditor/DeviceQRCode/LiveOpsStream +
        // tab_pages + chat_devices): measured 34.53 / 27.14 / 28.52 /
        // 36.68. Floor = measured − 1 per axis. Ratchet plan in
        // docs/coverage.md. Target for follow-up: real 50% branches.
        statements: 33,
        branches: 26,
        functions: 27,
        lines: 35,
      },
```

**Tests.** Verified this run: **127 passed, 3 failed**. Failures all in `Settings.test.jsx` Twin section.

**Error handling.** `main.jsx` `ErrorBoundary` logs to `console.error`. Per-page fetch failure handling varies; some pages render empty arrays without error chips.

**Operability.** `?v2=` route gating; `localStorage` API key bootstrap (`bootstrap.js`).

**Limitations.** Branches coverage is 27% — well under any production bar. **3 tests failing on main.** Several pages reported by user as misleading or broken (Appendix A): Settings/Providers stale dropdown, Devices pair modal, GlassBrain blue-dot overlap, Oversight back button visibility, Twin theatre.

**Stability.** **Alpha → Beta** (regressions on main; thin coverage).

**P0/P1/P2.**
- **P0** Fix the 3 failing `Settings.test.jsx` Twin assertions; turn red CI red.
- **P0** Address the user-reported issues A–E (Appendix A) end to end.
- **P0** Playwright e2e covering the critical paths: setup → first chat round-trip → settings save → device pairing → app install. Target ≥20 e2e tests.
- **P0** Accessibility pass on `Settings`, `Chat`, `Pair` (focus order, contrast, headings).
- **P1** Continue ratcheting Vitest coverage toward 50% branches; current target tracked in `docs/coverage.md`.
- **P2** Visual regression for GenUI surfaces (Chromatic or Playwright trace snapshots).

### 2.16 Security primitives

**Implementation.** `vault.py`, `device_pairing.py`, `session_auth.py`, `content_defense.py`, `dangerous_tools.py`, `fetch_guard.py`, `sandbox_policy.py`, `exec_approvals.py`, `docker_sandbox.py`, `wasm_sandbox.py`, `wasm_host.py`.

**Tests.** `test_security_full.py` (~9), `test_session_auth.py`, `test_sandbox_policy.py` (14), `test_permissions_routines.py` (24), `test_key_persistence.py` (8), `test_pair_flows.py` (14). **No dedicated test file** for `content_defense.py`, `fetch_guard.py`, `docker_sandbox.py`.

**Limitations.**
- BlindVault is plaintext JSON at chmod 600 — **not encrypted at rest**.
- `fetch_guard.py` is the only thing standing between skills and SSRF; **no security-focused tests**.
- `dangerous_tools.py` is exercised only indirectly via `test_tool_runner.py`.

**Stability.** **Beta** for mechanics; **Alpha** for the test surface around content_defense / fetch_guard / docker_sandbox.

**P0/P1/P2.**
- **P0** Add `test_fetch_guard.py` covering localhost/private-IP/IPv6/dns-rebind cases.
- **P0** Add `test_content_defense.py` covering marker injection / Unicode homoglyph / oversized payloads.
- **P0** Optional encryption-at-rest for vault (OS keychain on macOS, libsecret on Linux, DPAPI on Windows).
- **P1** Run `bandit` and `ruff S` security rules on `feral-core/api` and `feral-core/security` in CI.
- **P1** Document threat model in an ADR — explicitly state what FERAL is **not** (e.g. not a HIPAA-certified medical device, not a multi-tenant SaaS, not safe to expose to the public internet without a reverse proxy).

### 2.17 Web client v1, extension, Playwright

**Implementation.** `feral-client/` mirrors a subset of v2 routes; legacy. `feral-extension/` MV3 with broad host permissions. Playwright spec at `feral-client/e2e/glass-brain.spec.js` (1 spec).

**Tests.** v1: 51 vitest. Extension: 19 vitest. Playwright: 1 spec.

**Stability.** **Beta** (legacy / narrow E2E).

**P0/P1/P2.**
- **P0** Choose: deprecate v1 with a sunset date and a redirect, or commit to parity. Today the split confuses the UX (the user sees v1 GlassBrain links bleed into v2 navigation).
- **P0** Review extension host permissions; restrict where possible.
- **P1** Expand Playwright to v2 critical paths (mirrors §2.15 P0).

### 2.18 Desktop (Tauri)

**Implementation.** Real Tauri app, spawns brain via `python -m api.server`, registers tray, global shortcuts, autostart. **0 tests** in repo. CI: `desktop.yml` is `workflow_dispatch` only.

**Stability.** **Research Prototype** — no per-PR build, no signing in CI, no auto-updater test.

**P0/P1/P2.**
- **P0** Smoke-build on `main` (no signing required).
- **P0** Vitest smoke test for `desktop/src/main.js` invocation logic.
- **P1** Re-enable `pull_request` trigger when signing secrets exist.
- **P2** Tauri auto-updater wired with signed artifacts.

### 2.19 Mobile apps + node SDKs + daemons

**Implementation.** iOS app (HealthKit/QR/BLE/optional TLS pin), Android app (Health Connect/QR/foreground service). Node SDKs in Swift/TS/Python. Daemons (`wristband_daemon`, `w300_daemon`). Bridges (`ios-bridge` legacy, `android-bridge`, `phone-bridge`).

**Tests in repo.** iOS: `FeralNodeTests` (3 files), `ios-node-sdk` `Tests/FeralNodeSDKTests/` (~12). Android: `src/test` + `androidTest`. Python SDK: `test_hup_v1_1_schemas.py` (8). Wristband/W300: `test_daemon_offline.py`. **None of these run in `.github/workflows/ci.yml`.** TS SDK has zero tests. Phone-bridge has zero tests. `ios-bridge` is a stale duplicate. `theora_glasses_daemon` is empty.

**Stability.** **Alpha** as a fleet (no continuous mobile build). Individual components vary from **Beta** (python-node-sdk schemas) to **Research Prototype** (TS SDK, theora glasses).

**P0/P1/P2.**
- **P0** Add weekly `xcodebuild test` and `gradlew test`/`connectedCheck` jobs in `.github/workflows`.
- **P0** Add `pytest feral-nodes/python-node-sdk/tests` and `pytest feral-nodes/wristband_daemon/tests` to CI.
- **P0** Vitest/Jest smoke for `@feral-ai/node-sdk` (schema round-trip from `test_hup_v1_1_schemas.py` data).
- **P0** Delete or implement `feral-nodes/theora_glasses_daemon/`; collapse `ios-bridge` into `ios-app`.
- **P1** Documented device farm (or honest manual matrix sheet).
- **P2** Tauri-style auto-update for native apps.

### 2.20 feral-registry + marketplace

**Implementation.** FastAPI service with publish/catalog/item/flag/auth_github/blobs routers under `/api/v1`. Alembic migrations. Fly.io deployment files.

**Tests in repo.** `tests/test_publish_flow.py`, `test_app_publish.py`, `test_seed_daemons.py`, `test_seed_personas_workflows.py` — ~21 cases. **Zero CI today**.

**Stability.** **Alpha** until registry CI is green with a realistic DB.

**P0/P1/P2.**
- **P0** Add a `feral-registry` job to `.github/workflows/ci.yml` using docker-compose for Postgres; gate merges on it.
- **P0** Alembic upgrade-from-empty test.
- **P1** Trivy scan on published images.
- **P1** Migrate prod from sqlite-on-volume to managed Postgres.

### 2.21 SDKs (`sdk/python`, `sdk/node`)

**Implementation.** `feral-sdk` 0.1.0 (Python) and `@feral/sdk` 0.1.0 (Node). Both expose plugin/tool/client/genui/device helpers.

**Tests.** **Zero** in either tree.

**Stability.** **Research Prototype** until covered.

**P0/P1/P2.**
- **P0** Add unit tests + mypy/typecheck job in CI.
- **P1** Versioned release pipeline (auto-publish to PyPI/npm on tag, separate from `feral-ai` cadence).

### 2.22 HA add-on, scripts, examples, benchmarks, templates, demos

| Component | State | Action |
|-----------|-------|--------|
| `feral-ha-addon/` | Pinned to PyPI; smoke imports inside the image. PyPI propagation race observed during v2026.4.28 release. | **P1** integration test hitting `/health` inside the container; armv7/aarch64 matrix. |
| `scripts/` | Real, narrow scope. `bump_version.py` referenced by `test_version_consistency.py`. | **P2** add `audit_routes.py` to a quarterly CI check. |
| `examples/apps/*` | Used as fixtures by `feral-core` tests. | **P2** install one example via `feral app install` in install-smoke. |
| `benchmarks/run.py` | Default `FERAL_BRAIN_URL=127.0.0.1:8000` mismatches Brain port 9090. | **P0** align default; **P1** weekly comparative bench in CI. |
| `templates/wasm-skill-*` | Scaffolds only; not built in CI. | **P1** CI build job per template. |
| `private/demos/*` | Public smoke contracts in `feral-core/tests/test_demo_*_smoke.py` (5 each). | **P2** add a third demo for the voice round-trip path. |

### 2.23 Documentation

**Implementation.** Mintlify site under `docs/mintlify/`. Many guides; reference pages for API, WebSocket, environment, CLI, A2UI schema.

**Limitations.**
- `hardware/hup-spec.mdx` says “HUP v1.0.0”; spec is v1.1.0.
- `reference/websocket.mdx` lists `/v1/node` on port **9091**; default Brain runs on **9090**.
- `services/mdns.py` advertises a hardcoded version string `"2026.4.30"` independent of `version.py` (drift risk).
- README still cites old test counts (1344 / 19 skills / etc.) — undermines trust.

**P0/P1/P2.**
- **P0** Single-source the version string for docs site, mDNS advertisement, Tauri config, HA add-on, and Python package — all should derive from `feral-core/version.py`.
- **P0** Update `hardware/hup-spec.mdx` to v1.1.0; correct WebSocket port; update README counts.
- **P1** Per-feature runbook one-pagers (“Symptom → triage → fix → verify”).
- **P1** Threat-model ADR; “what FERAL is not” ADR.
- **P2** Mintlify link checker in CI.

---

## Phase 3 — Roadmap synthesis to true production-grade

The per-domain P0/P1/P2 lists in Phase 2 are the actual work. The synthesis below is the **shortest path** to flipping the grade column to **Production-Ready (single user)** across the platform. P0 is non-negotiable for the corresponding feature to claim that grade.

### 3.1 Cross-cutting — observability + truth-in-status (P0)

| # | Work |
|---|------|
| 1 | Make `main` green: fix the failing `test_mcp_full.py::test_get_http_routes_exposes_mcp_endpoints` and the 3 `Settings.test.jsx` Twin assertions. |
| 2 | Update README/CHANGELOG numbers each release; add a CI step that fails if a published number drifts from `pytest --collect-only` and `vitest list`. |
| 3 | Single-source the version string (`feral-core/version.py` → docs site → mDNS → Tauri → HA add-on). |
| 4 | Default Grafana dashboard + Prometheus alert rules in-repo; emit metrics from sync, MCP, tool denials, supervisor failures, refusal fallbacks, rate-limit drops, auth failures. |
| 5 | Per-feature runbooks (P1) and threat-model ADR (P1). |

### 3.2 Mobile / desktop / registry / SDK CI gating (P0)

| # | Work |
|---|------|
| 1 | Add `xcodebuild test` (iOS app + ios-node-sdk) and `./gradlew test` + `connectedCheck` (Android app + android-bridge) to `.github/workflows/`, weekly minimum, blocking on PRs that touch those paths. |
| 2 | Add `pytest feral-nodes/python-node-sdk/tests`, `pytest feral-nodes/wristband_daemon/tests`, `pytest feral-nodes/w300_daemon/tests` to CI. |
| 3 | Add a `feral-registry` job to `ci.yml` with docker-compose Postgres; gate merges on it. |
| 4 | Add Vitest smoke for `@feral-ai/node-sdk` and unit tests + mypy for `sdk/python`. |
| 5 | Smoke-build `desktop/` on `main`; re-enable PR trigger when signing secrets exist. |

### 3.3 Trust + sandboxing + security (P0)

| # | Work |
|---|------|
| 1 | Implement signed marketplace trust path (`genui/a2ui_protocol.py:121` TODO). |
| 2 | Sandbox `AppSurface` rendering (CSP, no eval, allowlisted network per manifest). |
| 3 | Add `test_fetch_guard.py`, `test_content_defense.py`, `test_dangerous_tools.py`. |
| 4 | Tighten `tool_genesis.py`: deny network in generated code without explicit approval; reject-on-unsafe-AST E2E. |
| 5 | Run `bandit` / `ruff S` in CI on `feral-core/{api,security}`. |
| 6 | Optional vault encryption at rest using OS keychain. |
| 7 | Move `/v1/node` auth to before `accept()`. |
| 8 | Hash pairing tokens at rest; add token TTL. |

### 3.4 Resilience + chaos (P0)

| # | Work |
|---|------|
| 1 | Sync chaos: kill peer mid-handshake, corrupt WAL, disk full, mDNS fail → static peer fallback. |
| 2 | LLM chaos: all providers fail; verify user-visible error and `feral.llm.errors_total` parity. |
| 3 | Voice soak: 1-hour session with forced reconnects; assert no handle leaks. |
| 4 | Channels soak: 24-hour Telegram/Slack/Discord against personal bots in staging. |
| 5 | Backup/restore runbook + CLI; round-trip test in CI. |

### 3.5 Provider catalog freshness (P0)

| # | Work |
|---|------|
| 1 | Re-enable a scheduled cron on `provider-research.yml` (or, better, an in-Brain background refresh) so new model names appear without manual repo PRs. This is the root of the user-reported “GPT-5.5 missing” complaint (Appendix A.1). |
| 2 | Live provider probe gated by `live` markers, run nightly. |
| 3 | Token + cost metrics. |

### 3.6 v2 client UX + e2e (P0)

| # | Work |
|---|------|
| 1 | Address user-reported issues A–E (see Appendix A). Each ships with a Vitest assertion proving the fix. |
| 2 | Playwright e2e for: setup → first chat round-trip → settings save → device pairing → app install. ≥20 specs. |
| 3 | Ratchet Vitest coverage toward 50% branches per `docs/coverage.md`. |
| 4 | Accessibility pass on `Settings`, `Chat`, `Pair`. |

### 3.7 Documentation + governance (P1, becomes P0 if claiming production)

| # | Work |
|---|------|
| 1 | Per-P0-feature runbook one-pagers. |
| 2 | ADR folder: threat model, autonomy modes, “what FERAL is not”. |
| 3 | Performance budget: p95 end-to-end latency from user message to first token. |
| 4 | Mintlify drift fixes (HUP version, WS port, README counts). |

---

## Phase 4 — Global Platform Assessment

### 4.1 Truly production-ready today

**Nothing in this repo is unconditionally production-ready.** The closest are:

- **Brain HTTP API key + rate limiting** for single-node local use (`api/server.py`).
- **LLM provider catalog mechanics + failover** (`agents/llm_provider.py`, `providers/catalog.py`).
- **Memory store + sync (LAN)** under non-adversarial conditions (`memory/store.py`, `memory/sync.py`).
- **Supervisor audit + per-session lock + parallel tools** since v2026.4.28 (`agents/supervisor.py`, `agents/orchestrator.py`).
- **Pairing + HUP protocol** on the Brain side (`security/device_pairing.py`, `hardware/protocol.py`).
- **CLI `feral app *` and the GenUI install/render contract** (`cli/app_commands.py`, `agents/app_registry.py`, demo smoke tests).

These are honestly **strong Beta**. They become **Production-Ready (single user)** once the Phase 3 P0 items in §3.1 (truth-in-status), §3.3 (security), and §3.4 (resilience) are closed for them.

### 4.2 Close to ready (gap list)

| Feature | Gap |
|---------|-----|
| Brain web client v2 | 3 failing tests on main; Settings/Twin theatre; coverage 27% branches; no real e2e. |
| Voice realtime | Wake-word default mismatch; no aggregated latency metric; no soak test; provider-API churn risk. |
| Tool genesis + WASM skills | AST allowlist is not isolation; no shipped golden WASM skill. |
| Channels (long-tail) | Matrix/Signal/Feishu/Zalo/voice_call are stubs documented as TODO checklists. |
| Mobile + desktop | Builds and tests not part of per-PR CI. |
| Registry | Tests not in CI; production storage on a single Fly volume. |
| GenUI marketplace | A2UI signed trust TODO is open. |
| Documentation | Drift in HUP version, WS port, README counts; no threat-model ADR. |

### 4.3 Cross-cutting concerns (affect most features)

1. **Single-user local threat model** vs what the marketing copy and UI sometimes imply. The product is safe to run on **your own laptop behind a firewall**; it is **not** safe to expose to the public internet without a reverse proxy and additional hardening. This needs to be loud.
2. **Optional dependencies** (`zeroconf`, OpenTelemetry, Docker, `bleak`, OpenCV, vendor binary frameworks) — the “graceful degradation” story is real but creates many untested combinations. CI does not exercise the full matrix.
3. **SQLite + file locks everywhere** (memory, scheduler, pairing, exec_approvals, intents) — fine for one machine, bad assumption for HA.
4. **External API drift** (LLM providers, Google, Anthropic, OpenAI Realtime, channels). This is the **largest** ongoing operational risk. Today only the LLM call path has retry + failover; cost accounting is missing.
5. **Observability is opt-in** — `/metrics` returns 404 unless `FERAL_METRICS_ENDPOINT=1`, and most cognition modules emit nothing. There is no default dashboard or alert rules in-repo.
6. **CI gates only the brain + web clients.** Mobile, desktop, registry, SDKs, daemons, examples, benchmarks, WASM templates, and HA add-on cross-arch are all unverified per-PR.
7. **Two web clients (v1 and v2) coexist** and the navigation occasionally bleeds between them; v1 is technically still routed.
8. **Two webhook subsystems coexist** (`webhooks.py` and `integrations_webhooks.py`); the trust model differs.
9. **Source-of-truth sprawl for the version string** (Python `version.py`, Tauri `tauri.conf.json`, mDNS hardcoded literal, HA add-on `FERAL_VERSION` arg, README badges, Mintlify pages). Every release introduces drift.
10. **Brutally honest test math**: README numbers are stale and **main has regressions today** (1 backend + 3 frontend). Until that is fixed, every other claim in this document is suspect by association.

### 4.4 Top priorities for the next 3–6 months

These are the items that, if done in this order, give the most production-readiness per unit of engineering effort.

1. **Make main green and keep it green.** Fix the 1 backend + 3 v2 failing tests this week. Add a release-block check that compares published numbers to live `pytest`/`vitest` output. Single-source the version string.
2. **CI gate the missing pieces.** Mobile, desktop, registry, SDKs, daemons. Weekly is acceptable to start; per-PR for paths under change. Without this, every release is partly hand-rolled.
3. **Truth-in-UX.** Fix the user-reported A–E issues (Appendix A). Stop showing controls (Twin pause, action toggles) unless they correspond to a configured executor. Wire a fresh provider model refresh path so the dropdown is never older than 24 hours.
4. **Security hardening.** Sign A2UI manifests; sandbox `AppSurface`; add `fetch_guard`/`content_defense`/`dangerous_tools` test files; vault encryption-at-rest; pairing token hashing + TTL; `/v1/node` auth before `accept()`; bandit/ruff-S in CI.
5. **Resilience drills.** Sync chaos, LLM all-providers-fail, voice soak, channel soak. Backup/restore runbook + CLI. Default Grafana dashboard + Prometheus alert rules.
6. **WASM and skill marketplace honesty.** Either ship a golden WASM skill end-to-end or label WASM “experimental” in the UI. Mark long-tail channels (Matrix/Signal/Feishu/Zalo/voice_call) “experimental” until implemented.
7. **e2e + accessibility for v2.** ≥20 Playwright specs covering critical paths. a11y pass on Settings/Chat/Pair.
8. **Documentation cleanup.** HUP/WebSocket/README drift. Per-feature runbooks. Threat model and “what FERAL is not” ADRs.

---

## Summary honesty grade table (strict)

| Grade | Components today |
|-------|-------------------|
| **Battle-Hardened** | None. No in-repo evidence of long-running multi-household or enterprise operation. |
| **Production-Ready (single user)** | None unconditionally. Closest after Phase 3 P0: API gateway, LLM provider catalog, memory + LAN sync, supervisor + parallel orchestrator, GenUI app contract on Brain side, pairing/HUP. |
| **Beta** | Web client v2 (with regressions today), voice router, Telegram/Slack/Discord/WhatsApp channels, scheduler, proactive engine, taskflows-supervisor wiring, app registry, hybrid GenUI, learner, intent compiler, hardware mesh + adapters, observability library, security primitives (vault, pairing, session_auth, sandbox_policy, exec_approvals). |
| **Alpha** | Web client v1, browser extension, Twin Settings UX (failing tests + theatre), tool_genesis, code_interpreter, screen_capture, subagent, Docker sandbox, content_defense / fetch_guard / dangerous_tools (no dedicated tests), wristband / w300 / phone-bridge daemons, python-node-sdk, ios-node-sdk vendor adapters, integrations (long-tail), `mcp` (subprocess fragile + 1 failing test today), gateway/services/workflows packages. |
| **Research Prototype** | Desktop release path (Tauri, no PR-CI, no signing in CI), TS Node SDK (0 tests), `sdk/python` (0 tests), `sdk/node` (0 tests), `theora_glasses_daemon` (empty), `ios-bridge` (stale duplicate), WASM skill templates, benchmarks, `examples/apps/*` outside fixtures, Matrix/Signal/Feishu/Zalo/voice_call channels (stubs by docstring), feral-registry (no CI), GenUI third-party marketplace. |

---

## Appendix A — User-reported issues (latest report) traced to source

The complaints raised most recently were: stale provider model dropdown, broken pair-a-device flow, GlassBrain blue-dot overlap, missing Oversight Back button, and Twin “theatre.” Below is the exact code and the honest fix scope.

### A.1 Settings → Providers shows a stale model list (e.g. no GPT-5.5)

**Backend root cause.** `providers/catalog.py` caches model lists for 6 hours on disk; `provider-research.yml` cron is **disabled** (workflow_dispatch only). Anthropic adapter is a hardcoded list. So even if the user clicks **Refresh models** (which forces `live=true`), some providers never advance their bundled `model_catalog.json` in repo until someone runs the workflow manually.

**Frontend.** `feral-client-v2/src/pages/Settings.jsx`:
- `loadModels` defaults `live=true`, `force` only when `loadModels({ force: true })` (lines 426–447).
- Initial mount calls `loadModels()` — **no `force` on first paint** (line 448). The dropdown is a `<input list>` + `<datalist>` (lines 532–566).
- “Refresh models” button calls `loadModels({ force: true })` (lines 553–557).

**Fix shape (P0).**
1. Re-enable a daily/weekly cron on `provider-research.yml` and ship the refreshed `model_catalog.json` automatically; or add an in-Brain `ProviderCatalog.refresh_async()` job that runs nightly and respects the API keys present in the vault.
2. On first paint of Settings/Providers, if the catalog disk-cache age exceeds, say, 24 h, automatically issue a `force=true` refresh.
3. Show the cache age and a “Live ✔ / Cached ⓘ” badge in the dropdown so users can see which list they’re looking at.

### A.2 “Pair a device” adds a row but does not open the modal

**Wiring is correct in source.**
- `feral-client-v2/src/pages/Devices.jsx:86–88` and `:99` set `showPair = true` on click.
- `Devices.jsx:178–182` renders `<PairDeviceModal open={showPair} onClose={...} onPaired={...} />`.
- `PairDeviceModal.jsx:26–79` consumes `open` correctly.
- `Pair.jsx` (the unauthenticated phone landing) at `App.jsx:39` is a separate route.

**Likely runtime causes** (not visible in static source — needs e2e to reproduce):
- The modal is wired but visually obscured by a higher z-index element from `Shell` / `Dock` / `Orb`.
- Or the “add to historical list” code path runs before `setShowPair(true)`, repaints, and a navigation/refresh nukes the modal.
- Or there is a CSS regression in `ui/Modal.jsx` after a recent shell change.

**Fix shape (P0).**
1. Add a Playwright e2e for `/devices` → click “Pair new device” → assert the modal is visible and contains the QR + permission toggles. This will reproduce the bug deterministically.
2. Audit z-index in `Shell.jsx`, `Dock.jsx`, `Orb.jsx`, `Modal.jsx`. Define a stacking-context order and write a Vitest assertion for it.
3. Make “add to historical list” a side effect of *successful pairing*, not a side effect of clicking the button.

### A.3 GlassBrain — blue dot overlapping the empty-state text

- The mind-map intentionally has no center anchor on empty (`ConsciousnessMindMap.jsx:149–163`); the comment block at 149–152 explains why.
- The colored center circle in non-empty graphs uses `var(--v2-accent)` (`ConsciousnessMindMap.jsx:182–188`).
- The empty-state CSS is in `pages.css:587–591` (absolutely centered).
- The legend dots are at `GlassBrain.jsx:141–152`.

**Fix shape (P0).** Either the legend or another stray styled element is overlapping the empty-state text. Add a Vitest assertion that, in the empty-graph state, no element with `border-radius: 50%` (i.e. a “dot”) lies above the empty-state text bounding box. Adjust z-index or layout accordingly.

### A.4 Oversight has no in-app Back button

- `Oversight.jsx:18` imports `BackButton`; `:104–106` renders `<Pane title="Oversight" leading={<BackButton />} actions={...}>`.
- `BackButton.jsx:21–46` calls `navigate(-1)` with `fallback="/glass-brain"`.
- `Pane.jsx:21–26` renders `leading` in `v2-pane-header`.

**Honest assessment.** The control exists in source. If the user sees no Back, the cause is build-time (stale bundle), shell layout (the dock/menubar is covering it), or a missing CSS class.

**Fix shape (P0).** Add a Vitest assertion that the rendered Oversight page contains a button with accessible name “Back” in the document. Add a Playwright assertion that the Back button is visible and click-receptive when the route is `/oversight`. If either fails, fix the layout/build.

### A.5 Settings → Twin shows pause + actions even with no executors

- `Settings.jsx:1443–1454` fetches `/api/twin/policies` and `/api/twin/approvals?status=pending` and `/api/supervisor/stats`.
- `:1508–1510` defines `hasActive = policies.length > 0`.
- `:1521–1534` **always** renders the Pause/Resume kill switch, regardless of `hasActive`.
- `:1538–1554` shows the empty explainer only when `!hasActive && disconnected.length === 0`.
- `:1556–1584` shows per-domain Draft/Auto/Off only when `hasActive`.
- `:1586–1619` shows disconnected rows when present.
- `:1621–1654` shows available-but-unconfigured executors.

**This is the “theatre” the user complained about.** And the 3 failing v2 tests this run all sit in this section (`twin-disconnected` lookup at `Settings.test.jsx:232`).

**Fix shape (P0).**
1. Render the kill-switch only when there is at least one **configured** twin executor; otherwise, show a single line: “No twin executors configured. Connect iMessage / email / calendar in the Channels and Integrations sections to enable.”
2. Stop rendering toggles for actions whose executor is not configured. Move them into a clearly-labeled “Available executors” collapsed section that calls out each executor as **off and not connected** with a one-click “Connect” affordance.
3. Fix the 3 failing assertions in `Settings.test.jsx` so the Twin section is again on the green path.

---

*This roadmap is a living document. Update it on every release that changes scope, test counts, CI coverage, or the user-visible UX. Until §0 shows zero failing tests on `main`, the document’s grade for any feature should be capped at **Beta**.*
