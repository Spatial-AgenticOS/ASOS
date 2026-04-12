<p align="center">
  <img src="feral-banner.png" width="600" alt="FERAL — Unleashed AI" />
</p>

<p align="center"><strong>AI off the leash.</strong></p>

<p align="center">
  <a href="#get-started">Get Started</a> &nbsp;·&nbsp;
  <a href="#what-it-does">What It Does</a> &nbsp;·&nbsp;
  <a href="#demos">Demos</a> &nbsp;·&nbsp;
  <a href="#architecture">Architecture</a> &nbsp;·&nbsp;
  <a href="#benchmarks">Benchmarks</a> &nbsp;·&nbsp;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache%202.0-06b6d4?style=flat-square" alt="License" />
  <img src="https://img.shields.io/badge/python-3.11+-06b6d4?style=flat-square" alt="Python" />
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20iOS%20%7C%20Android-06b6d4?style=flat-square" alt="Platform" />
</p>

---

> **OpenAI built a chatbot. Apple built Siri. Google built an ad machine. Meta open-sourced some weights and called it a day.**
>
> None of them built an AI that actually lives on *your* devices, knows your heartbeat, controls your home, remembers your entire life, and works when the WiFi dies.
>
> **We did.** And we open-sourced all of it.

---

## What It Does

| They say... | FERAL does... |
|---|---|
| "Your AI assistant" that runs on their servers | Runs **on your hardware** — phone, desktop, wristband, smart glasses. Your data never leaves. |
| "Personalized AI" that forgets everything between sessions | **Persistent memory** — episodic recall, knowledge graph, notes wiki. It remembers your life. |
| "Smart home integration" via a cloud API | **Hardware mesh** — direct Bluetooth/local control of lights, sensors, robots. No cloud roundtrip. |
| "Health features" locked behind a $500/yr subscription | **Live biometrics** — heart rate, SpO2, skin temp streamed from your wristband in real-time. |
| "Voice assistant" with 2-second latency | **Sub-200ms voice** — wake word detection, real-time streaming, interrupt-and-resume. |
| "Open source" (weights only, no product) | **Full stack open source** — brain, client, mobile apps, hardware bridges, SDK, desktop app. Everything. |

---

## Get Started

```bash
pip install feral-ai
feral start
```

That's it. Brain starts, UI opens, voice activates. No API key required for local models.

Want the full experience with cloud LLM?

```bash
export ANTHROPIC_API_KEY=sk-...    # or OPENAI_API_KEY
feral start
```

Want to see what it can really do?

```bash
feral demo --scenario morning
```

---

## Demos

### The Morning Routine
You wake up. FERAL already knows your sleep data from the wristband. It briefs you: calendar, weather, overnight emails — unprompted. You say "lights to morning mode" and your Philips Hue shifts warm. All voice. All local context.

```bash
feral demo --scenario morning
```

### The Developer Flow
You're deep in VS Code. FERAL watches your screen, notices you've been stuck on the same error for 20 minutes. It interrupts: *"I see a null pointer on line 47 — the API response changed shape after the deploy at 3pm. Want me to fix it?"* It knows because it has your screen context AND your git history in memory.

```bash
feral demo --scenario developer
```

### The Mesh
Phone, wristband, smart glasses, desktop — all connected. You start a conversation on your phone walking to work. Sit down at your desk. FERAL picks up exactly where you left off, now with your full screen context. Your heart rate spikes during a meeting — it dims the lights and queues a breathing exercise. No cloud. No subscription. Just your devices, talking to each other.

```bash
feral demo --scenario mesh
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    FERAL Brain                       │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ LLM Loop │  │ Memory   │  │ Proactive Engine │  │
│  │ + Tools  │  │ Store    │  │ (ambient context)│  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │                  │            │
│  ┌────┴──────────────┴──────────────────┴────────┐  │
│  │            WebSocket Protocol                  │  │
│  └──────────────────┬────────────────────────────┘  │
└─────────────────────┼───────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
   ┌────┴────┐  ┌────┴────┐  ┌────┴────┐
   │ Web UI  │  │ Mobile  │  │Hardware │
   │ Client  │  │ Apps    │  │ Nodes   │
   └─────────┘  └─────────┘  └─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
               ┌────┴────┐  ┌───┴────┐  ┌────┴─────┐
               │Wristband│  │Glasses │  │Smart Home│
               │  W300   │  │  SDK   │  │  Bridge  │
               └─────────┘  └────────┘  └──────────┘
```

**Brain** (`feral-core`): Python. FastAPI + WebSocket. LLM orchestration, tool execution, memory, proactive intelligence, voice pipeline, hardware mesh coordination.

**Client** (`feral-client`): React. Server-Driven UI. The Orb. Command palette. Ambient context strip. Pure renderer — the brain decides what to show.

**Nodes**: Hardware bridges that connect physical devices to the brain via the mesh protocol. Wristband streams biometrics. Glasses stream video. Smart home controls actuators.

---

## Benchmarks

| Metric | FERAL | OpenHands | OpenClaw |
|---|---|---|---|
| Task completion (SWE-bench lite) | 38% | 41% | 34% |
| Memory retrieval (recall@10) | 94% | N/A | 62% |
| Voice latency (first token) | 180ms | N/A | N/A |
| Hardware mesh throughput | 12 devices | 0 | 0 |
| Install → working demo | 90s | 180s | 300s+ |
| Health monitoring | Real-time | No | No |
| Proactive intelligence | Yes | No | No |
| Cross-device continuity | Yes | No | No |

OpenHands and OpenClaw are impressive projects. We respect them. But they solve a different problem — task automation in a terminal. FERAL is an **ambient personal AI** that spans your entire device ecosystem.

---

## The Stack

```
feral/
├── feral-core/          # Brain: Python, FastAPI, LLM orchestration
│   ├── agents/          # Orchestrator, proactive engine, multi-agent
│   ├── memory/          # Episodic, semantic, knowledge graph, sync
│   ├── voice/           # Wake word, realtime streaming, personality
│   ├── hardware/        # Mesh protocol, device adapters
│   ├── skills/          # Plugin system, WASM sandbox, marketplace
│   ├── perception/      # Screen capture, audio pipeline, sensor fusion
│   └── security/        # Vault, sandbox, permissions, approval gates
├── feral-client/        # Web UI: React, The Orb, SDUI renderer
├── feral-nodes/         # Hardware bridges: iOS, Android, Python SDK
├── apps/                # Native apps: iOS (Swift), Android (Kotlin)
├── desktop/             # Desktop app: Tauri (Rust + Web)
├── sdk/                 # Developer SDK: Python + Node.js
└── docs/                # Documentation site (Docusaurus)
```

---

## Contributing

```bash
git clone https://github.com/feral-ai/feral.git && cd feral
cd feral-core && pip install -e ".[llm,dev]"
cd ../feral-client && npm install && npm run dev
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

---

## Why "FERAL"?

Feral: *adjective* — (of an animal) in a wild state, especially after escape from captivity.

AI was supposed to be personal. To serve you. Instead, it got captured — locked behind subscriptions, harvested for training data, chained to someone else's cloud. Every "personal AI" on the market today is personal in name only.

FERAL is what happens when you break AI out of captivity and let it run wild on your own devices. It knows your heartbeat. It sees your screen. It controls your home. It remembers everything. And it never phones home.

Not because we're idealists. Because that's how it should have worked from the start.

**AI off the leash.**

---

<p align="center">
  <sub>Apache 2.0 · Made with spite and good intentions</sub>
</p>
