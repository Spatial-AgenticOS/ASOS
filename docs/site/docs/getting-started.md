---
id: getting-started
title: Getting Started
sidebar_position: 1
slug: /getting-started
---

# Getting Started

Get THEORA running locally in under five minutes. By the end of this page you will have a brain server, a web dashboard, and your first conversation.

## Prerequisites

- **Python 3.11+** — `python3 --version`
- An LLM API key (OpenAI, Anthropic, Gemini, Groq) **or** a local [Ollama](https://ollama.ai) instance

## Install

```bash
pip install theora-asos[llm]
```

This installs the `theora` CLI, the FastAPI brain server, and the bundled web UI.

## Setup

Run the interactive setup wizard:

```bash
theora setup
```

The wizard walks you through:

| Step | What It Configures |
|:-----|:-------------------|
| **LLM Provider** | Choose OpenAI, Anthropic, Gemini, Groq, or Ollama (free/local). API key is validated live. |
| **Agent Identity** | Name, personality, voice settings, and behavioral rules. |
| **Skills & Tools** | Enable computer use, web search, vision, hardware control. Add keys for Tavily, Spotify, etc. |
| **Features** | Voice mode (realtime / whisper / disabled), streaming, proactive behavior, wake word. |

All configuration is written to `~/.theora/`. No cloud account needed.

## Start

```bash
theora start
```

This launches the brain and serves the web dashboard at [http://localhost:9090](http://localhost:9090).

Open the URL in your browser. Type a message or click the microphone for voice.

## First Chat (CLI)

You can also talk to THEORA from the terminal:

```bash
theora "What files are in my home directory?"
theora "Search the web for latest AI news"
theora "Remember that my favorite color is blue"
theora "What's my favorite color?"
```

## First Chat (SDK)

```python
from theora_sdk import TheoraClient

async with TheoraClient("http://localhost:9090") as client:
    reply = await client.chat("Hello! What can you do?")
    print(reply)
```

## Docker Alternative

If you prefer Docker:

```bash
git clone https://github.com/Spatial-AgenticOS/ASOS.git && cd ASOS
cp .env.example .env   # fill in your API keys
docker compose up -d
```

| Service | URL |
|:--------|:----|
| Brain + API | http://localhost:9090 |
| Web UI | http://localhost:3000 |
| Skill Registry | http://localhost:8080 |

## What's Next

- [Architecture](./architecture.md) — understand how the brain, memory, and device mesh fit together
- [Python SDK](./sdk/python.md) — build plugins and automate THEORA programmatically
- [Write a Skill](./guides/skills.md) — add new capabilities to your agent
- [Connect a Device](./guides/devices.md) — bring hardware into the mesh
