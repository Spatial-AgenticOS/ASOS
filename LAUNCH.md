# FERAL Launch Plan

## Pre-launch Checklist

- [ ] Create GitHub org: `feral-ai`
- [ ] Create repo: `feral-ai/feral`
- [ ] Reserve npm: `feral-ai`, `create-feral-demo`
- [ ] Reserve PyPI: `feral-ai`
- [ ] Register domain: `feral.ai` or `getferal.ai` or `goferal.dev`
- [ ] Record demo videos (see below)
- [ ] Upload demos to YouTube (unlisted until launch)
- [ ] Prepare launch tweet thread
- [ ] Prepare HackerNews post
- [ ] Prepare Reddit posts (r/LocalLLaMA, r/machinelearning, r/selfhosted)

---

## Demo Videos to Record

### 1. Morning Routine (60-90 seconds)
```bash
feral demo --scenario morning
```
**Script**: Wake up → wristband sleep summary appears proactively → voice briefing (calendar, weather, news) → "lights to morning mode" → lights shift → show health metrics on ambient strip → end with the orb pulsing gently.

**Key shots**: The proactive toast appearing without being asked. The ambient strip showing live heart rate. Voice response under 200ms.

### 2. Developer Flow (60-90 seconds)
```bash
feral demo --scenario developer
```
**Script**: Coding in VS Code → screen capture notices error → proactive interrupt: "You've been stuck on line 47..." → developer asks follow-up → FERAL remembers yesterday's deploy → shows diff → fixes the bug. All while heart rate stays calm on the ambient strip.

**Key shots**: Screen context appearing in the ambient strip. The thinking orb animation. Memory recall from yesterday.

### 3. The Mesh (90-120 seconds)
```bash
feral demo --scenario mesh
```
**Script**: Start on phone (walking) → conversation about the day → sit at desk → seamless handoff to desktop (conversation continues mid-sentence) → wristband heart rate spikes → FERAL dims lights automatically → "Let's do a breathing exercise" → show all 4 devices on the device status bar.

**Key shots**: The device status bar lighting up as devices connect. Session handoff with zero interruption. Smart home reacting to biometrics.

---

## Launch Tweets (Thread)

### Tweet 1 (The Hook)
```
OpenAI built a chatbot.
Apple built Siri.
Google built an ad machine.
Meta open-sourced some weights.

None of them built an AI that lives on YOUR devices, knows your heartbeat, and works when WiFi dies.

We did. It's called FERAL. And it's fully open source.

🧵👇
```

### Tweet 2 (What It Does)
```
FERAL is an AI OS that runs across your phone, desktop, wristband, and smart glasses.

- Persistent memory (it remembers your life)
- Live biometrics (heart rate, SpO2, skin temp)
- Voice with sub-200ms latency
- Smart home control (no cloud)
- Proactive intelligence (it interrupts YOU when it matters)

No subscription. No data harvesting.
```

### Tweet 3 (The Demo)
```
Here's what it looks like:

[Morning Routine Demo Video]

One command: `feral demo --scenario morning`

It briefs you on your day, reads your sleep data from your wristband, adjusts your lights — all unprompted. All running locally.
```

### Tweet 4 (The Mesh)
```
The real flex: cross-device continuity.

Start a conversation on your phone. Walk to your desk. FERAL picks up exactly where you left off — now with your full screen context.

Your heart rate spikes in a meeting? It dims the lights and queues a breathing exercise. Automatically.

[Mesh Demo Video]
```

### Tweet 5 (The CTA)
```
FERAL is Apache 2.0 licensed. The entire stack:

- Brain (Python)
- Web client (React)
- iOS app (Swift)
- Android app (Kotlin)
- Desktop app (Tauri/Rust)
- Hardware bridges
- SDK (Python + Node.js)

pip install feral-ai
feral start

GitHub: github.com/feral-ai/feral

Is your AI feral yet?
```

---

## HackerNews Post

**Title**: `FERAL – An open-source AI OS that runs across your devices with live biometrics and persistent memory`

**Body**:
```
Hi HN,

We built FERAL because every "personal AI" on the market runs on someone else's servers, forgets everything between sessions, and can't interact with the physical world.

FERAL is different:

- It runs on YOUR devices (phone, desktop, wristband, smart glasses)
- It has persistent memory — episodic recall, knowledge graph, personal wiki
- It streams live biometrics from your wristband (HR, SpO2, skin temp)
- It controls your smart home directly via Bluetooth (no cloud roundtrip)
- It has sub-200ms voice with wake word detection
- It proactively interrupts you when something matters (health alert, meeting reminder, context-aware suggestion)

The full stack is open source under Apache 2.0: brain (Python/FastAPI), web client (React), iOS app (Swift), Android app (Kotlin), desktop app (Tauri/Rust), hardware bridges, and developer SDK.

Try it:
  pip install feral-ai && feral start

Or see the demos:
  feral demo --scenario morning    # Wake-up briefing + wristband + smart home
  feral demo --scenario developer  # Screen-aware coding assistant
  feral demo --scenario mesh       # Cross-device continuity

GitHub: https://github.com/feral-ai/feral

We're not competing with OpenHands or OpenClaw — those are great terminal task runners. FERAL is an ambient personal AI that spans your entire device ecosystem.

Happy to answer questions about the architecture, the hardware mesh protocol, or why we think personal AI should never leave your devices.
```

---

## Reddit Posts

### r/LocalLLaMA
**Title**: `FERAL: open-source AI OS with hardware mesh, live biometrics, and persistent memory — runs fully local`

Focus on: local inference support, Ollama/llama.cpp integration, no API keys needed, privacy story.

### r/machinelearning
**Title**: `FERAL: An open-source agentic AI OS with cross-device continuity, real-time health monitoring, and proactive intelligence`

Focus on: architecture, the proactive engine, perception pipeline, multi-modal fusion.

### r/selfhosted
**Title**: `FERAL: Self-hosted AI assistant that runs across all your devices — phone, desktop, wristband, smart home`

Focus on: self-hosting story, Docker support, no cloud dependencies, privacy.
