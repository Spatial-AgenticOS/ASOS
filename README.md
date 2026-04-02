<div align="center">
  <img src="https://img.icons8.com/color/128/artificial-intelligence.png" alt="ASOS Logo" width="128">
  <h1>Spatial-Agentic OS (ASOS)</h1>
  <p><strong>The Enterprise-Grade, Local-First Intelligent Operating System for the Physical World.</strong></p>

  [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
  [![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
</div>

---

## ⚡ What is ASOS?

**Spatial-AgenticOS (ASOS)** is fundamentally different from standard browser automation tools. It is an agentic framework designed specifically to bridge the gap between Large Language Models and **hardware**—spanning from Smart Glasses to physical robotics.

Built on a lightweight, bidirectional WebSocket protocol, ASOS runs an orchestrator "Brain" that manages dynamic physical routing, handles asynchronous actuator hooks, and constructs completely adaptive Server-Driven UIs (SDUI), without requiring any front-end rebuilds.

With **Semantic Tool Routing**, **Biometric Context Vectors** (e.g., streaming Heart Rate context directly to the LLM), and explicit **Safety Hooks**, ASOS is the missing nervous system for IoT.

## 🚀 Key Capabilities

- **🧠 Agentic Orchestrator**: Recursively uses LLMs to interpret commands, generate SDUI payloads, and distribute tasks natively.
- **🔌 Hardware Daemon SDK**: A highly refined WebSocket daemon to instantly expose any ROS or embedded device to the Agentic Loop.
- **🛡️ Pre/Post-Tool Safety Hooks**: Explicit semantic streaming interceptions. If a command tries to blindly move a robot actuator at dangerous speeds, the hook intercepts the stream and safely asks the user for explicit permission via SDUI.
- **📱 Server-Driven UI (SDUI)**: Zero frontend friction. The LLM dictates UI natively (creating Cards, Badges, Lists) allowing extreme flexibility.

## 📁 Repository Structure

We employ a monolithic repository optimized for clean abstraction levels:

- `/asos-core`: The Python-based Brain. Contains the Orchestrator, LLM pipeline, and memory graphs.
- `/asos-nodes/python-node-sdk`: The developer toolkit for rapidly binding sensors and actuators (cameras, servos) to the network.
- `/asos-client`: React/Vite client designed to interpret incoming SDUI payloads dynamically.
- `/docs`: Extensive architecture mapping and guides for extending ASOS capabilities.

## 🔧 Quick Start

### 1. Start the ASOS Brain

Deploy the core via Python Poetry:
```bash
cd asos-core
poetry install
export OPENAI_API_KEY="your_key_here"
poetry run python api/server.py
```
*The WebSocket server will mount on `ws://localhost:9090`.*

### 2. Connect a Hardware Node
Using the Python Node SDK, run a hardware emulator (or real robot):
```bash
cd asos-nodes/python-node-sdk
python3 robot_template.py --brain ws://localhost:9090
```
*Your daemon is now subscribed to the Agentic Loop.*

### 3. Connect the Client
Access the dynamic frontend visualizer:
```bash
cd asos-client
npm install
npm run dev
```

## 📖 Deeper Architecture

Explore our deep-dive manuals to fully understand and build upon ASOS:

- [**Architecture & Protocol Overview**](./docs/ARCHITECTURE.md)
- [**Adding New Skills and Hardware Extensions**](./docs/ADDING_SKILLS.md)

## 🤝 Contributing

We welcome advanced developers looking to integrate modern LLMs into the physical world. Please ensure any pull requests pass our semantic linting and standard testing.

*Spatial-AgenticOS: The software layer for the forthcoming hardware revolution.*
