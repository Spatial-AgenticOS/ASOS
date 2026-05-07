"""
FERAL Demo Scenarios — Scripted flows for recording killer demos.

Three scenarios targeting three audiences:
  1. Morning Routine (consumer) — wake word, health, calendar, smart home, voice
  2. Developer Flow (developer) — install, chat, plugin, GenUI
  3. The Mesh (hardware/AI) — multi-device, health monitoring, proactive alerts, computer use
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger("feral.demo.scenarios")


SCENARIO_MORNING = {
    "id": "demo-morning",
    "name": "Morning Routine Demo",
    "description": "Consumer demo: wake word → health briefing → calendar → smart home → voice",
    "steps": [
        {
            "type": "delay",
            "seconds": 2,
            "description": "Simulate wake word detection",
        },
        {
            "type": "inject_telemetry",
            "wristband": {"activity": "resting", "heart_rate_bpm": 64, "spo2_pct": 98, "skin_temp_c": 36.5},
            "description": "Send resting health data",
        },
        {
            "type": "trigger_proactive",
            "trigger_id": "morning_briefing",
            "description": "Trigger morning briefing",
        },
        {
            "type": "delay",
            "seconds": 5,
            "description": "User reads briefing",
        },
        {
            "type": "user_message",
            "text": "What's on my calendar today?",
            "description": "Calendar query",
        },
        {
            "type": "delay",
            "seconds": 4,
        },
        {
            "type": "user_message",
            "text": "Set the lights to focus mode, I'm starting work",
            "description": "Smart home command",
        },
        {
            "type": "smart_home_action",
            "action": "set_scene",
            "params": {"scene": "focus"},
        },
        {
            "type": "delay",
            "seconds": 3,
        },
        {
            "type": "inject_telemetry",
            "wristband": {"activity": "working", "heart_rate_bpm": 72, "spo2_pct": 98, "skin_temp_c": 36.6},
            "description": "User starts working, HR rises slightly",
        },
        {
            "type": "user_message",
            "text": "Help me prepare for my demo day presentation. What do we know about the current state of our project?",
            "description": "Context-aware question that triggers memory recall",
        },
    ],
}

SCENARIO_DEVELOPER = {
    "id": "demo-developer",
    "name": "Developer Flow Demo",
    "description": "Developer demo: chat → write plugin → see it work → GenUI",
    "steps": [
        {
            "type": "user_message",
            "text": "Hey FERAL, show me the system dashboard with all connected devices and skills",
            "description": "Dashboard query that triggers GenUI",
        },
        {
            "type": "delay",
            "seconds": 5,
        },
        {
            "type": "user_message",
            "text": "Can you check the weather in San Francisco for me?",
            "description": "Triggers skill that may need generation",
        },
        {
            "type": "delay",
            "seconds": 6,
        },
        {
            "type": "user_message",
            "text": "Search the web for 'open source AI agent frameworks comparison 2026' and summarize the top results",
            "description": "Web search demo — shows real tool use",
        },
        {
            "type": "delay",
            "seconds": 8,
        },
        {
            "type": "user_message",
            "text": "Write a Python script that generates a random motivational quote and save it to my desktop",
            "description": "Computer use demo — file creation",
        },
        {
            "type": "delay",
            "seconds": 6,
        },
        {
            "type": "user_message",
            "text": "Show me my recent memories and what you've learned about me this week",
            "description": "Memory recall demo",
        },
    ],
}

SCENARIO_MESH = {
    "id": "demo-mesh",
    "name": "The Mesh Demo",
    "description": "Hardware/AI demo: multi-device → health → proactive alerts → computer use",
    "steps": [
        {
            "type": "inject_telemetry",
            "wristband": {"activity": "resting", "heart_rate_bpm": 65, "spo2_pct": 98, "skin_temp_c": 36.4},
            "description": "Baseline health data",
        },
        {
            "type": "user_message",
            "text": "FERAL, show me all connected devices and their status",
            "description": "Device mesh overview",
        },
        {
            "type": "delay",
            "seconds": 4,
        },
        {
            "type": "user_message",
            "text": "Start monitoring my health while I work on the presentation",
            "description": "Activate health monitoring",
        },
        {
            "type": "delay",
            "seconds": 3,
        },
        {
            "type": "user_message",
            "text": "Open my code editor and help me fix the authentication bug in server.py",
            "description": "Computer use + coding assistance",
        },
        {
            "type": "delay",
            "seconds": 8,
        },
        {
            "type": "inject_telemetry",
            "wristband": {"activity": "working", "heart_rate_bpm": 108, "spo2_pct": 97, "skin_temp_c": 36.8},
            "description": "Simulate stress — HR spikes during debugging",
        },
        {
            "type": "delay",
            "seconds": 3,
            "description": "Proactive engine should detect elevated HR and alert",
        },
        {
            "type": "smart_home_action",
            "action": "set_scene",
            "params": {"scene": "calming"},
            "description": "Auto-adjust lights when stress detected",
        },
        {
            "type": "delay",
            "seconds": 5,
        },
        {
            "type": "inject_telemetry",
            "wristband": {"activity": "resting", "heart_rate_bpm": 72, "spo2_pct": 98, "skin_temp_c": 36.5},
            "description": "HR normalizes after break",
        },
        {
            "type": "user_message",
            "text": "Thanks FERAL. What was my average heart rate during that coding session?",
            "description": "Health analytics query using memory",
        },
    ],
}

SCENARIOS = {
    "morning": SCENARIO_MORNING,
    "developer": SCENARIO_DEVELOPER,
    "mesh": SCENARIO_MESH,
}


class ScenarioRunner:
    """Executes a demo scenario step-by-step against a running brain."""

    def __init__(self, brain_state=None, ws_send=None):
        self._state = brain_state
        self._ws_send = ws_send
        self._running = False

    async def run(self, scenario_name: str):
        scenario = SCENARIOS.get(scenario_name)
        if not scenario:
            logger.error("Unknown scenario: %s (available: %s)", scenario_name, list(SCENARIOS.keys()))
            return

        logger.info("Starting demo scenario: %s", scenario["name"])
        self._running = True

        for i, step in enumerate(scenario["steps"]):
            if not self._running:
                break

            step_type = step["type"]
            desc = step.get("description", step_type)
            logger.info("  Step %d/%d: %s", i + 1, len(scenario["steps"]), desc)

            if step_type == "delay":
                await asyncio.sleep(step.get("seconds", 2))

            elif step_type == "user_message":
                if self._state and self._state.orchestrator:
                    session_id = "demo-scenario"
                    try:
                        await self._state.orchestrator.handle_command(session_id, step["text"])
                    except Exception as e:
                        logger.warning("Scenario message failed: %s", e)

            elif step_type == "inject_telemetry":
                if self._state and self._state._demo:
                    wb = step.get("wristband", {})
                    if wb:
                        demo = self._state._demo
                        if wb.get("activity"):
                            demo.wristband.set_activity(wb["activity"])
                        if wb.get("heart_rate_bpm", 0) > 100:
                            demo.wristband.trigger_stress_spike()

            elif step_type == "trigger_proactive":
                if self._state and self._state.proactive:
                    self._state.proactive._first_interaction_today = True

            elif step_type == "smart_home_action":
                if self._state and self._state._demo:
                    self._state._demo.smart_home.execute(
                        step.get("action", ""), step.get("params", {})
                    )

        logger.info("Demo scenario '%s' completed", scenario["name"])
        self._running = False

    def stop(self):
        self._running = False
