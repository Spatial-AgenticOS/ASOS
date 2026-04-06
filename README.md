# THEORA — Open AI Agent

> Computer use, web search, GenUI, voice, hardware control, persistent memory. One `pip install`.

THEORA is an open-source AI agent that runs locally. It can execute shell commands, read/write files, search the web, render dynamic UI, connect to hardware devices, and remember everything across sessions.

## Install

```bash
# One command
curl -sSL https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/scripts/install.sh | bash
```

Or manually:

```bash
pip install "theora[llm] @ git+https://github.com/Spatial-AgenticOS/ASOS.git#subdirectory=asos-core"
theora setup    # Guided config — pick provider, enter keys, toggle features
theora serve    # Start the agent server
theora          # Interactive chat
```

## What Actually Works (tested)

| Feature | Status | What you get |
|---|---|---|
| **Computer use** | **Working** | bash, read_file, write_file, edit_file, grep_search, glob_search, web_fetch |
| **Web search** | **Working** | Tavily-powered search with AI summaries (needs `TAVILY_API_KEY`) |
| **Chat with LLM** | **Working** | OpenAI, Ollama (local/free), Groq. Streaming responses. |
| **CLI agent** | **Working** | `theora` REPL, `theora "message"` one-shot, `theora status/skills/devices` |
| **Setup wizard** | **Working** | `theora setup` — provider selection, key entry, feature toggles |
| **GenUI rendering** | **Working** | Tool results render as cards, metrics, lists — not just text |
| **Memory** | **Working** | 4-tier: working context, notes, episodes, knowledge graph. SQLite. |
| **Multi-agent** | **Working** | Router dispatches to health/home/research/creative workers |
| **MCP server** | **Working** | Claude Desktop, Cursor can connect and use THEORA's tools |
| **MCP client** | **Working** | Connect external MCP servers, tools auto-merge into agent |
| **Web dashboard** | **Working** | React UI at `localhost:9090` (when using Docker or building client) |
| **Hardware daemons** | **Working** | WebSocket devices connect, send telemetry, receive commands |
| **Blind vault** | **Working** | API keys stored securely, never exposed to LLM |
| **Skill manifests** | **Working** | Drop a JSON file to add any API as an agent tool |
| **Hot provider switch** | **Working** | `POST /api/llm/switch` — change LLM at runtime |

### Requires keys:
- **LLM**: `OPENAI_API_KEY` or run Ollama locally (`ollama serve`) — free
- **Web search**: `TAVILY_API_KEY` (free tier at tavily.com)
- Without an LLM key, the agent runs in direct-execution mode (keyword matching, no reasoning)

## Quick Demo

```bash
# 1. Install
pip install -e "asos-core[llm]"

# 2. Configure
theora setup

# 3. Start server
theora serve

# 4. In another terminal — chat
theora "search the web for latest AI news"
theora "read the file pyproject.toml"
theora "run ls -la in the current directory"
theora status
theora skills
```

## How It Works

```
User message → Orchestrator → LLM (with tools) → Tool execution → GenUI → Response
                    │                                    │
                    ├── Computer use (bash, files, grep)  │
                    ├── Web search (Tavily)               │
                    ├── Hardware daemons (WebSocket)       │
                    ├── MCP tools (external servers)       │
                    └── Memory (read/write context)        │
                                                          │
                                        ┌─────────────────┘
                                        ▼
                              SDUI rendered as cards,
                              metrics, lists in the UI
                              (or plain text in CLI)
```

## Creating Custom Tools

Drop a JSON manifest in `~/.theora/skills/`:

```json
{
  "skill_id": "my_api",
  "brand": { "name": "My API", "primary_color": "#6c5ce7" },
  "description": "What this does — the LLM reads this to decide when to use it",
  "auth": { "type": "api_key", "api_key_header": "X-API-Key" },
  "endpoints": [{
    "id": "get_data",
    "method": "GET",
    "url": "https://api.example.com/data",
    "description": "Fetches data",
    "params": [{ "name": "query", "type": "string", "required": true }]
  }]
}
```

Set `THEORA_KEY_my_api=your-key` and it works.

Or write a Python-backed skill for complex logic (see `skills/impl/computer_use.py` for reference).

## Connecting Hardware

Any WebSocket client can connect as a hardware daemon:

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:9090/v1/node?api_key=dev-secret-key") as ws:
        await ws.send(json.dumps({
            "hop": "daemon", "type": "node_register",
            "payload": {"node_id": "my-sensor", "node_type": "sensor", "capabilities": ["temperature"]}
        }))
        while True:
            await ws.send(json.dumps({
                "hop": "daemon", "type": "telemetry",
                "payload": {"node_id": "my-sensor", "sensors": {"temperature_c": 22.5}}
            }))
            await asyncio.sleep(5)

asyncio.run(main())
```

## MCP Integration

**THEORA as MCP server** (for Claude Desktop):
```json
{ "mcpServers": { "theora": { "command": "python", "args": ["-m", "mcp.server"], "cwd": "/path/to/asos-core" } } }
```

**THEORA as MCP client** (connect external tools):
```json
// ~/.theora/mcp_servers.json
{ "servers": [{ "name": "github", "transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"] }] }
```

## Docker

```bash
docker compose up -d
# Brain: http://localhost:9090
# Client: http://localhost:3000
```

## Project Structure

```
ASOS/
├── asos-core/              # The agent brain (Python, FastAPI)
│   ├── api/server.py       # WebSocket + REST server
│   ├── agents/             # Orchestrator, multi-agent, learner
│   ├── skills/             # Registry, executor, manifests, Python impls
│   ├── memory/             # 4-tier store + federated sync
│   ├── cli/                # CLI (theora command), setup wizard
│   ├── security/           # Blind vault, permissions, WASM sandbox
│   ├── hardware/           # Hardware Use Protocol (HUP)
│   └── mcp/                # MCP server + client
├── asos-client/            # React web UI (Vite + Tailwind)
├── asos-nodes/             # Hardware daemon SDKs (Python, iOS, Android)
├── scripts/install.sh      # curl installer
└── docker-compose.yml
```

## What's Not Done Yet

Being honest:

- **PyPI publishing** — not on PyPI yet, install from GitHub
- **Voice** — code exists but needs `OPENAI_API_KEY` and is not end-to-end tested
- **Vision** — VLM integration code exists but needs camera/screen capture wired
- **Wake word** — "Hey THEORA" detection code exists, needs `openwakeword` installed
- **Android app** — SDK code exists, not a buildable app
- **Desktop GUI** — Tauri scaffold exists, not built
- **Skill marketplace** — registry server code exists, not deployed
- **Federated sync** — CRDT code exists, not tested across real devices

## Environment Variables

| Variable | What | Default |
|---|---|---|
| `OPENAI_API_KEY` | LLM key (or use Ollama) | — |
| `TAVILY_API_KEY` | Web search | — |
| `THEORA_LLM_PROVIDER` | `openai`, `ollama`, `groq` | `openai` |
| `THEORA_LLM_MODEL` | Model name | `gpt-4o-mini` |
| `NODE_API_KEY` | Daemon auth | `dev-secret-key` |
| `THEORA_KEY_*` | Per-skill API keys | — |

## Contact

**Alpay Kasal** — info@theora.io

## License

Apache 2.0 with attribution — see [NOTICE](NOTICE).

> Built with THEORA (https://github.com/Spatial-AgenticOS/ASOS)

Copyright 2024-2026 THEORA, Inc. Created by Mahmoud Omar and Alpay Kasal.
