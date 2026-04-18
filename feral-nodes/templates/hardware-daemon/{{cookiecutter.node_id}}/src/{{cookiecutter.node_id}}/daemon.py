"""{{cookiecutter.name}} — FERAL HUP v1 daemon entrypoint.

This template is fully runnable with mocked hardware; replace the TODO
blocks with real sensor/actuator integrations, then ship.
"""

from __future__ import annotations

import asyncio
import os
import random

from feral_node_sdk import FeralNode


CAPABILITIES = [c.strip() for c in "{{cookiecutter.capabilities}}".split(",") if c.strip()]


def build_node() -> FeralNode:
    return FeralNode(
        node_id="{{cookiecutter.node_id}}",
        name="{{cookiecutter.name}}",
        manufacturer="{{cookiecutter.manufacturer}}",
        firmware_version="{{cookiecutter.firmware_version}}",
        node_type="{{cookiecutter.node_type}}",
        brain_url=os.environ.get("FERAL_BRAIN_URL"),
        api_key=os.environ.get("FERAL_API_KEY"),
        capabilities=CAPABILITIES,
    )


node = build_node()


@node.on_action("ping")
async def ping(params: dict) -> dict:
    """Placeholder action — reply with an echo. TODO: replace with real diagnostic."""
    return {"ok": True, "echo": params}


@node.on_action("demo_actuator")
async def demo_actuator(params: dict) -> dict:
    """TODO: drive your actuator (buzzer, LED, motor, ...) here."""
    duration_ms = int(params.get("duration_ms", 200))
    return {"ok": True, "actuated_ms": duration_ms}


async def telemetry_loop() -> None:
    """TODO: replace with real sensor reads. Emits a mock sample each second."""
    while True:
        sample = {"value": round(random.uniform(0.0, 1.0), 3), "mocked": True}
        await node.emit_event("demo_sensor", sample)
        await asyncio.sleep(1.0)


def main() -> None:
    node.run(telemetry_loop())


if __name__ == "__main__":
    main()
