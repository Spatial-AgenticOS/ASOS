"""
THEORA Brain — Core WebSocket Server
======================================
The local-first agentic brain. Runs on the user's machine.
Clients (phone, web, daemon, glasses) connect via WebSocket.
"""

import asyncio
import json
import logging
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from models.protocol import (
    TheoraMessage,
    TextCommandPayload,
    UIEventPayload,
    NodeRegisterPayload,
    SDUIPayload,
    TextResponsePayload,
    DeviceRegisterPayload,
    parse_message,
)
from agents.orchestrator import Orchestrator
from skills.registry import SkillRegistry
from memory.store import MemoryStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("theora.brain")


# ─────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────

app = FastAPI(
    title="THEORA Brain",
    description="Local-first agentic intelligence core",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# State
# ─────────────────────────────────────────────

class BrainState:
    def __init__(self):
        self.sessions: dict[str, WebSocket] = {}  # session_id → ws
        self.daemons: dict[str, WebSocket] = {}   # node_id → ws
        self.devices: dict[str, dict] = {}         # device_id → device info
        self.skill_registry = SkillRegistry()
        self.memory = MemoryStore()
        self.orchestrator: Optional[Orchestrator] = None

    async def init(self):
        """Initialize the brain components."""
        self.skill_registry.load_builtin_skills()
        self.orchestrator = Orchestrator(
            skill_registry=self.skill_registry,
            send_to_client=self.send_to_session,
            daemons=self.daemons,
            memory=self.memory,
        )
        logger.info(f"Brain initialized with {len(self.skill_registry.skills)} skills, {self.memory.count()} memories")

    async def send_to_session(self, session_id: str, msg: TheoraMessage):
        ws = self.sessions.get(session_id)
        if ws:
            await ws.send_json(msg.model_dump())

    async def send_to_daemon(self, node_id: str, msg: TheoraMessage):
        ws = self.daemons.get(node_id)
        if ws:
            await ws.send_json(msg.model_dump())


state = BrainState()


# ─────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await state.init()


# ─────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "THEORA Brain",
        "version": "0.1.0",
        "status": "running",
        "sessions": len(state.sessions),
        "daemons": len(state.daemons),
        "devices": len(state.devices),
        "skills": len(state.skill_registry.skills),
    }


@app.get("/skills")
async def list_skills():
    return [
        {
            "skill_id": s.skill_id,
            "name": s.brand.name,
            "description": s.description,
            "endpoints": len(s.endpoints),
            "trigger_phrases": s.trigger_phrases,
        }
        for s in state.skill_registry.skills.values()
    ]


# ─────────────────────────────────────────────
# Internal Memory API
# ─────────────────────────────────────────────

@app.post("/internal/memory/save")
async def memory_save(body: dict):
    """Save a note to memory."""
    content = body.get("content", "")
    tags = body.get("tags", [])
    importance = body.get("importance", "normal")
    if not content:
        return {"error": "content is required"}
    result = state.memory.save(content=content, tags=tags, importance=importance)
    return result


@app.get("/internal/memory/search")
async def memory_search(query: str = "", limit: int = 10):
    """Search saved notes."""
    if not query:
        return []
    return state.memory.search(query=query, limit=limit)


@app.get("/internal/memory/recent")
async def memory_recent(limit: int = 10):
    """List recent notes."""
    return state.memory.list_recent(limit=limit)


@app.delete("/internal/memory/{note_id}")
async def memory_delete(note_id: str):
    """Delete a note."""
    deleted = state.memory.delete(note_id)
    return {"deleted": deleted}


# ─────────────────────────────────────────────
# Main Client WebSocket
# ─────────────────────────────────────────────

@app.websocket("/v1/session")
async def client_session(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid4())
    state.sessions[session_id] = ws
    logger.info(f"Client connected: {session_id}")

    # Send welcome
    await ws.send_json(TheoraMessage(
        session_id=session_id,
        hop="brain",
        type="text_response",
        payload=TextResponsePayload(
            text="THEORA Brain connected. How can I help?"
        ).model_dump(),
    ).model_dump())

    try:
        while True:
            raw = await ws.receive_json()
            raw["session_id"] = session_id
            msg, payload = parse_message(raw)

            if msg.type == "text_command" and isinstance(payload, TextCommandPayload):
                # Process text command through the orchestrator
                await state.orchestrator.handle_command(
                    session_id=session_id,
                    text=payload.text,
                    context=payload.context,
                )

            elif msg.type == "ui_event" and isinstance(payload, UIEventPayload):
                # Handle UI interaction
                await state.orchestrator.handle_ui_event(
                    session_id=session_id,
                    action_id=payload.action_id,
                    event=payload.event,
                    value=payload.value,
                )

            elif msg.type == "device_register" and isinstance(payload, DeviceRegisterPayload):
                state.devices[payload.device_id] = payload.model_dump()
                logger.info(f"Device registered: {payload.device_id} ({payload.device_type})")

            elif msg.type == "biometric":
                # Store biometric context for the orchestrator
                if state.orchestrator:
                    state.orchestrator.update_biometric(session_id, raw.get("payload", {}))

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {session_id}")
        del state.sessions[session_id]


# ─────────────────────────────────────────────
# Daemon WebSocket (for OpenClaw-style nodes)
# ─────────────────────────────────────────────

@app.websocket("/v1/node")
async def daemon_session(ws: WebSocket):
    await ws.accept()
    node_id = None
    logger.info("Daemon connecting...")

    try:
        while True:
            raw = await ws.receive_json()
            msg, payload = parse_message(raw)

            if msg.type == "node_register" and isinstance(payload, NodeRegisterPayload):
                node_id = payload.node_id
                state.daemons[node_id] = ws
                logger.info(f"Daemon registered: {node_id} ({payload.node_type}) — capabilities: {payload.capabilities}")

                # Acknowledge
                await ws.send_json(TheoraMessage(
                    hop="brain",
                    type="text_response",
                    payload=TextResponsePayload(
                        text=f"Node '{node_id}' registered successfully."
                    ).model_dump(),
                ).model_dump())

            elif msg.type == "execute_result":
                # Daemon reporting back a command result
                logger.info(f"Daemon result from {node_id}")
                if state.orchestrator:
                    await state.orchestrator.handle_daemon_result(
                        node_id=node_id,
                        result=raw.get("payload", {}),
                        session_id=msg.session_id,
                    )

            elif msg.type == "telemetry":
                # Hardware node pushing sensor data
                telemetry_payload = raw.get("payload", {})
                sensors = telemetry_payload.get("sensors", {})
                # We log at debug to avoid span, but show HR for demo
                if "ppg_heart_rate" in sensors:
                    logger.info(f"Telemetry from {node_id}: {sensors['ppg_heart_rate']} BPM")
                
                # Pass live context to orchestrator
                if state.orchestrator:
                    state.orchestrator.update_biometric(node_id, sensors)

    except WebSocketDisconnect:
        if node_id:
            logger.info(f"Daemon disconnected: {node_id}")
            state.daemons.pop(node_id, None)


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("""
    ╔══════════════════════════════════════╗
    ║        THEORA Brain v0.1.0          ║
    ║   Local-First Agentic Intelligence  ║
    ╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=9090, log_level="info")
