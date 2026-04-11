# FERAL Second-Wave Execution Sequence

This document sequences the second major wave after first-wave gates pass.

## Scope

Second-wave tracks, in strict order:

1. Linux desktop node and telemetry plane
2. Linux permission plane
3. Managed browser runtime
4. GenUI shell host elevation
5. Installer and first-boot productization

This is a sequencing and implementation plan, not a parallel "build everything at once" list.

## Entry Gate (Required Before Wave 2 Starts)

Wave 2 starts only when all first-wave validation gates are green:

- Runtime contract is deterministic and documented.
- Memory wiki is durable and browsable.
- TaskFlow resume survives restart.
- Session branch and restore are stable.
- Local vision path is explicit and fails clearly when unsupported.

## Delivery Model

- One lead branch for `wave2-sequencing`.
- One integration checkpoint per phase.
- No phase overlap unless explicitly marked as safe overlap.
- Every phase has an entry checklist, exit checklist, and rollback plan.

## Master Sequence

### Phase A - Linux Node Core (foundation for all later phases)

Goal: make Linux host a first-class FERAL node with stable telemetry and command lanes.

Implementation:

- Add `linux-node` service in `feral-core` with adapters for:
  - network state
  - battery/power
  - active app/window
  - notifications
  - audio devices
- Standardize node payload schema:
  - `node_id`, `capabilities`, `telemetry`, `event_ts`, `session_hint`
- Add heartbeat and reconnect strategy with exponential backoff.
- Add persisted node state cache under `feral_data_home()/nodes`.

Exit criteria:

- Node can register, stream telemetry, receive commands, and recover from restart.
- Dashboard shows Linux node health and last-seen telemetry.
- 24h soak test passes without memory growth regressions.

### Phase B - Permission Plane (safety boundary)

Goal: enforce Linux-native approvals for high-impact actions.

Implementation:

- Introduce explicit permission scopes:
  - `screen.capture`
  - `audio.capture`
  - `camera.capture`
  - `browser.control`
  - `shell.exec.elevated`
- Add approval policies in `security/` with:
  - deny by default
  - policy profiles (`developer`, `daily-driver`, `kiosk`)
  - per-tool + per-scope checks
- Add approval UX contract for Web UI and future shell host:
  - pending requests
  - reason, scope, timeout
  - allow once / allow session / deny

Exit criteria:

- Dangerous actions are blocked without explicit permission.
- Policy decisions are logged and queryable.
- Revoking permission takes effect immediately.

### Phase C - Managed Browser Runtime (supervised automation)

Goal: replace ad hoc browser assumptions with a supervised runtime.

Implementation:

- Add browser supervisor service:
  - lifecycle start/stop
  - profile isolation per session
  - crash detection and restart
- Add capability checks:
  - browser binary availability
  - automation protocol availability
  - sandbox compatibility on Linux
- Route browser-use skill calls through supervisor APIs, not direct process calls.
- Add runtime health endpoint and structured failure states.

Exit criteria:

- Browser sessions are launched and managed by FERAL, not user manual setup.
- Crash/restart recovers active automation session state where possible.
- Skill layer surfaces precise operator errors for unavailable browser capabilities.

### Phase D - GenUI Shell Host Elevation (operator surface)

Goal: promote UI from settings/chat pages to a shell-grade host surface.

Implementation:

- Add shell-host primitives:
  - launcher
  - quick actions
  - notification tray
  - permission prompts
  - running task cards
- Add `shell_host` capability contract in GenUI payloads for host-level actions.
- Add task pinning and one-click resume for TaskFlows from the shell surface.
- Keep current web UI as compatibility path; shell host is additive.

Exit criteria:

- Operator can start key actions from shell host without CLI.
- Permission prompts are actionable in shell surface.
- Active workflows and node status are visible from one place.

### Phase E - Installer and First-Boot Productization (deployment path)

Goal: provide reproducible installation and first-run experience after phases A-D are stable.

Implementation:

- Build installer artifacts:
  - workstation profile
  - appliance profile
- Add first-boot workflow:
  - runtime contract validation
  - provider preset selection
  - identity bootstrap
  - policy profile selection
- Add rollback and recovery hooks:
  - last-known-good generation
  - safe-mode boot option
  - diagnostics export bundle

Exit criteria:

- Fresh install reaches operational state in one guided flow.
- Failed update can roll back to last-known-good.
- Recovery path is documented and tested.

## Safe Overlap Rules

Allowed overlap:

- UI prototyping for shell host can start during late Phase C.
- Installer UX drafts can start during late Phase D.

Not allowed:

- Installer implementation before permission and managed browser foundations stabilize.
- Shell host launch before permission prompt contract is defined.

## Validation Matrix

Each phase ships with:

- unit tests for new services and policy logic
- integration tests for runtime edges
- failure-injection tests for restart/permission denial/crash recovery
- operator playbook updates in docs

## Risks and Mitigations

- Linux fragmentation risk -> target one baseline first (NixOS minimal), then Debian fallback.
- Permission UX complexity -> lock a narrow permission taxonomy before UI implementation.
- Browser runtime instability -> enforce supervisor ownership and health probes.
- Scope creep -> defer channel expansion and media pipelines to post-wave backlog.

## Wave 2 Done Definition

Wave 2 is complete when:

- Linux node is first-class and stable.
- Permission plane enforces real guardrails.
- Browser automation is managed and observable.
- GenUI shell host can operate core workflows.
- Installer and first-boot path are reproducible with rollback.
