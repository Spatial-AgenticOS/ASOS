# THEORA Demo Playbook

This playbook scripts the 10-beat platform demo. Every beat should work end-to-end before presenting. If a beat fails, note the failure honestly and either fix it or skip it with a clear explanation.

## Pre-Flight Checklist

Run these checks before starting the demo.

### Required

- [ ] Python 3.11+ installed
- [ ] `asos-core` installed (`pip install -e ".[llm]"` from the ASOS directory)
- [ ] At least one LLM provider configured:
  - **Cloud:** `OPENAI_API_KEY` set in environment or `~/.theora/credentials.json`
  - **Local:** `ollama serve` running with `llama3.1` pulled (`ollama pull llama3.1`)
- [ ] Brain starts cleanly: `theora serve` or `python -m api.server` from `asos-core/`
- [ ] Health check passes: `curl http://localhost:9090/health` returns `{"status": "ok"}`

### For Voice Beats

- [ ] `OPENAI_API_KEY` set (required for OpenAI Realtime API)
- [ ] Browser permits microphone access at `http://localhost:9090`

### For Vision Beat

- [ ] Ollama running with a VLM model: `ollama pull llava`
- [ ] Apply preset: `curl -X POST http://localhost:9090/api/llm/presets/apply -H 'Content-Type: application/json' -d '{"preset": "ollama_vision"}'`

### For Web Search

- [ ] `TAVILY_API_KEY` set in environment or `~/.theora/credentials.json`

### Optional

- [ ] Web UI built and bundled: `cd asos-client && npm ci && npm run build` then `scripts/build_webui.sh`
- [ ] Docker Compose: `docker compose up -d` (brain at :9090, client at :3000)

---

## Beat 1: Setup and Identity

**Goal:** Show that THEORA has a real guided onboarding flow.

```bash
theora setup
```

Walk through:
1. Choose LLM provider (explain options, pricing)
2. Set agent name and personality
3. Configure voice mode
4. Enable tools
5. Set security preferences

**Expected output:** `~/.theora/config.yaml`, `identity.yaml`, `credentials.json` created. Agent is ready.

**Verify:**
```bash
curl http://localhost:9090/api/identity
```

---

## Beat 2: Text and Voice Conversation

**Goal:** Show natural text conversation, then switch to realtime voice.

### Text

Open `http://localhost:9090` (or `http://localhost:3000` if client is separate).

Type a question:
> "What can you do?"

The agent should respond with a structured list of capabilities.

### Voice

Click the microphone button in the web UI. Say:
> "Tell me about yourself."

The agent should respond with natural speech. Verify:
- Bi-directional audio works
- Tool use mid-conversation is possible (ask it to search the web while talking)
- Interruption works (talk over the agent)

**API check:**
```bash
curl http://localhost:9090/api/voice/status
```

---

## Beat 3: Computer and Browser Actions

**Goal:** Show the agent can execute real actions on the computer.

In the chat, ask:
> "List the files in my current directory"

The agent should run `ls` via the bash tool and return results.

Then:
> "Search the web for the latest news about AI agents"

The agent should use Tavily web search and return a summary with sources.

Then:
> "Read the README.md file in this project"

The agent should use `read_file` and display content.

---

## Beat 4: Ingest Repository, PDF, or Text into Memory Wiki

**Goal:** Show the bulk ingest pipeline and wiki compilation.

### Via API

```bash
# Ingest the ASOS repo itself
curl -X POST http://localhost:9090/api/wiki/ingest/repo \
  -H 'Content-Type: application/json' \
  -d '{"path": ".", "extensions": [".py", ".md"], "max_files": 20}'
```

### Via Web UI

1. Click the book icon (Memory Wiki) in the chat header
2. Click "Ingest"
3. Select "Repo", enter `.` as path
4. Click "Start Ingest"
5. Click "Compile Wiki"

### Verify

```bash
curl http://localhost:9090/api/wiki/pages
curl http://localhost:9090/api/wiki/stats
```

Pages should appear with real content compiled from the ingested files.

---

## Beat 5: Run a TaskFlow

**Goal:** Show durable background workflows with pause/resume.

### Via API

```bash
# Create a TaskFlow that sleeps, saves a note, then compiles wiki
curl -X POST http://localhost:9090/api/taskflows \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "demo-flow",
    "steps": [
      {"type": "sleep", "config": {"seconds": 3}},
      {"type": "note.save", "config": {"content": "TaskFlow demo note"}},
      {"type": "wiki.compile", "config": {}}
    ]
  }'
```

### Via Web UI

Navigate to `/taskflows` from the sidebar. The flow should appear with a step timeline showing progress.

### Verify

```bash
# Check flow status (replace FLOW_ID)
curl http://localhost:9090/api/taskflows/FLOW_ID
```

Steps should show `completed` status with timing data.

**Resume demo:** Create a flow with a long sleep, restart the server, verify the flow re-queues and completes after restart.

---

## Beat 6: Session Snapshot, Branch, and Restore

**Goal:** Show conversation state management.

1. Have a conversation with a few exchanges in the chat.
2. Click "Snapshot" in the session toolbar (or via API).
3. Continue the conversation in a new direction.
4. Click "Branch" on the snapshot to create a parallel session.
5. Click "Restore" to return to the snapshot state.

### Via API

```bash
# Create snapshot
curl -X POST http://localhost:9090/api/session/snapshot \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "SESSION_ID", "label": "before-experiment"}'

# List snapshots
curl http://localhost:9090/api/session/snapshots?session_id=SESSION_ID

# Branch from snapshot
curl -X POST http://localhost:9090/api/session/branch \
  -H 'Content-Type: application/json' \
  -d '{"snapshot_id": "SNAPSHOT_ID", "new_session_id": "experiment-branch"}'

# Restore snapshot
curl -X POST http://localhost:9090/api/session/restore \
  -H 'Content-Type: application/json' \
  -d '{"snapshot_id": "SNAPSHOT_ID", "target_session_id": "SESSION_ID"}'
```

---

## Beat 7: Local Vision and GenUI Output

**Goal:** Show local VLM processing and structured UI output.

### Pre-requisite

Ollama must be running with `llava` model. Apply the vision preset:

```bash
curl -X POST http://localhost:9090/api/llm/presets/apply \
  -H 'Content-Type: application/json' \
  -d '{"preset": "ollama_vision"}'
```

### Demo

1. Enable the camera in the web UI (camera icon).
2. Ask: "What do you see?"
3. The agent should describe the scene using the local VLM.

For GenUI output, ask:
> "Show me a dashboard of my memory stats"

The agent should return structured SDUI cards rendered by the GenUI engine.

Optional GenUI provider proof point:

1. Register a provider JSON contract with brand rules and a named surface.
2. Compile the surface once through the GenUI provider API.
3. Render it again with live data to show that the layout stays fixed while the content updates.

This demonstrates the GenUI thesis: provider-defined surfaces can feel OS-native without regenerating a fresh interface every time.

### Verify

```bash
curl http://localhost:9090/api/llm/status
# Should show provider: ollama, model: llava, vision_supported: true
```

---

## Beat 8: Hardware Telemetry and Control

**Goal:** Show that hardware devices are first-class nodes in the agent system.

### Pre-requisite

A hardware daemon must be running. Use the Python SDK reference daemon or a real device.

**Quick test with the reference daemon:**

```bash
cd asos-nodes/python-node-sdk
python hardware_daemon/daemon.py --node-id demo-sensor --node-type sensor --brain-url ws://localhost:9090/v1/node
```

### Demo

1. Open the Dashboard (`/`). The "Connected Devices" panel should show the daemon.
2. The "Live Health" panel should begin showing telemetry if the daemon streams health data.
3. In the Chat, ask:
   > "What devices are connected?"
4. The agent should list the connected daemon and its capabilities.
5. Ask:
   > "Read the temperature from demo-sensor"
6. The agent should invoke the daemon and return a result.

### Verify

```bash
curl http://localhost:9090/api/devices
# Should list the connected daemon with its capabilities
```

This demonstrates the hardware ecosystem thesis: any device class speaks the same daemon protocol.

---

## Beat 9: Provider-Defined GenUI Surface

**Goal:** Show that service providers can define app surfaces via JSON contracts instead of shipping separate apps.

### Demo

1. Register a provider contract:

```bash
curl -X POST http://localhost:9090/api/genui/providers/register \
  -H 'Content-Type: application/json' \
  -d '{
    "provider_id": "rideos",
    "name": "RideOS",
    "description": "Ride hailing demo",
    "base_url": "https://api.rideos.example",
    "brand": {"primary_color": "#111827", "accent_color": "#10b981", "theme": "dark"},
    "ui_rules": {"layout_mode": "fixed", "brand_mode": "strict"},
    "cache_policy": {"mode": "static", "persist": true},
    "endpoints": [{"id": "quote", "method": "POST", "path": "/quote"}],
    "surfaces": [{
      "id": "home",
      "title": "Book a Ride",
      "entry": true,
      "template": {
        "type": "VStack", "spacing": 16,
        "children": [
          {"type": "Text", "value": "$headline", "style": "headline"},
          {"type": "Card", "corner_radius": 12, "children": [
            {"type": "HStack", "spacing": 8, "children": [
              {"type": "Text", "value": "$eta", "style": "subtitle"},
              {"type": "Text", "value": "$price", "style": "body"}
            ]}
          ]},
          {"type": "Button", "label": "$cta_label", "action_id": "request_ride", "color": "#10b981"}
        ]
      }
    }]
  }'
```

2. Compile the surface:

```bash
curl -X POST http://localhost:9090/api/genui/providers/rideos/surfaces/compile \
  -H 'Content-Type: application/json' \
  -d '{"surface_id": "home"}'
```

3. Render with fresh data (layout stays fixed, data changes):

```bash
curl -X POST http://localhost:9090/api/genui/providers/rideos/surfaces/render \
  -H 'Content-Type: application/json' \
  -d '{"surface_id": "home", "data": {"headline": "Your ride is ready", "eta": "2 min away", "price": "$12.50", "cta_label": "Confirm pickup"}}'
```

4. Show the Dashboard — the "Providers + Devices" panel should list the registered provider.

### Verify

```bash
curl http://localhost:9090/api/genui/providers
# Should list RideOS with 1 surface, brand rules, and cache policy
```

This demonstrates the GenUI thesis: compile once, cache the layout, hydrate with runtime data. No native app binary needed.

---

## Beat 10: Full Story Recap

Summarize what was shown:

1. Guided setup with identity and provider choice
2. Natural text and voice conversation
3. Real computer and web actions
4. Bulk knowledge ingestion into a browsable wiki
5. Durable background workflows that survive restarts
6. Session branching and restoration
7. Local vision with structured UI output
8. Hardware daemon telemetry and control
9. Provider-defined GenUI surface with compile-once caching

All running locally. No cloud dependency for the core loop (with Ollama).

This is not a chatbot demo. This is a platform demo.

---

## Known Environment Dependencies

| Beat | Dependency | Required |
|:-----|:-----------|:---------|
| 1-3 | LLM provider (OpenAI key or Ollama) | Yes |
| 2 (voice) | OpenAI API key + browser mic permission | For voice only |
| 3 (web search) | Tavily API key | For search only |
| 4-6 | None beyond the brain server | Yes |
| 7 (vision) | Ollama + `llava` model | For vision only |
| 7 (GenUI) | Any LLM provider | Yes |
| 8 (hardware) | A running daemon (reference SDK or real device) | For hardware beat only |
| 9 (provider surface) | None beyond the brain server | Yes |

## Failure Modes

- **No API key:** Brain starts but LLM calls fail with clear error messages. Use Ollama for a fully offline demo.
- **No Ollama:** Vision beat cannot run. Text/voice still work with cloud providers.
- **Port conflict:** Set `THEORA_PORT` to an available port. Update client config accordingly.
- **Browser blocks mic:** Use HTTPS or explicitly allow mic in browser settings for localhost.
- **No daemon running:** Hardware beat cannot run. All other beats work without a connected device.
- **Provider surface beat:** Always works — no external dependencies. Uses the brain's REST API.
