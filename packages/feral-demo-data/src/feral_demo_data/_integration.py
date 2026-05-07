"""Integration glue between feral-core and feral-demo-data.

All demo-specific imports of feral-core surfaces (BrainState, FastAPI
router) live HERE so the demo package is the only code that knows
both halves. The brain never imports from ``feral_demo_data`` —
discovery is one-way through the ``feral.plugins`` entry point group.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from feral_demo_data.seed import seed_demo_identity, seed_demo_memory
from feral_demo_data.simulator import DemoOrchestrator

logger = logging.getLogger("feral.demo")


def bootstrap(state: Any) -> Optional[DemoOrchestrator]:
    """Stand up the demo on a live BrainState.

    Mirrors the inline block that used to live in
    ``feral-core/api/state.py`` lines ~918-960 before the rip-out:
    seed identity + memory, instantiate orchestrator, register the
    telemetry pusher, set orchestrator refs, register the start task
    as a managed background task on the brain.

    Returns the started ``DemoOrchestrator`` so the caller can stash
    it on ``state._demo`` for later route handlers / status reporting.
    """
    seed_demo_identity()
    seed_demo_memory(state.memory)

    demo = DemoOrchestrator()

    async def _push_demo_telemetry(data: dict) -> None:
        wb = data.get("wristband", {})
        for sid in list(state.sessions):
            frame = state.perception.get_frame(sid)
            if frame and wb:
                frame.heart_rate = wb.get("heart_rate_bpm", 0)
                frame.spo2_pct = int(wb.get("spo2_pct", 0))
                frame.skin_temperature_c = wb.get("skin_temp_c", 0.0)
                frame.activity_state = wb.get("activity", "resting")
            if state.somatic_engine and wb:
                state.somatic_engine.update_biometrics(
                    sid,
                    heart_rate=float(wb.get("heart_rate_bpm", 0)),
                    spo2_pct=float(wb.get("spo2_pct", 0)),
                    skin_temp_c=float(wb.get("skin_temp_c", 0)),
                )
        try:
            from api.routes.dashboard import _get_dashboard_data  # type: ignore

            await state.broadcast_event("dashboard_update", await _get_dashboard_data())
        except Exception:  # noqa: BLE001 — best-effort dashboard tickle
            pass

    demo.on_telemetry(_push_demo_telemetry)
    demo.set_refs(state.orchestrator, state.sessions)
    state.register_background_task(
        asyncio.create_task(demo.start(), name="feral-demo-loop")
    )
    logger.warning(
        "FERAL_DEV_DEMO=1 — demo orchestrator running. "
        "All HR/SpO2/biometric values in this process are SYNTHETIC."
    )
    return demo


def status_routes():
    """Return an optional FastAPI router with ``/api/demo/*`` endpoints.

    Replaces the inline routes that used to live in
    ``feral-core/api/routes/devices.py`` lines ~283-312. Imported lazily
    by the brain hook so feral-core never has FastAPI <-> demo coupling
    when demo isn't installed.
    """
    try:
        from fastapi import APIRouter
    except ImportError:
        return None

    from feral_demo_data.scenarios import SCENARIOS, ScenarioRunner

    router = APIRouter(prefix="/api/demo", tags=["demo"])

    @router.get("/status")
    async def demo_status() -> dict:
        from api.state import state  # type: ignore

        if not getattr(state, "_demo", None):
            return {"active": False}
        demo = state._demo
        wristband = demo.wristband.read() if demo.wristband else {}
        smart_home = getattr(demo.smart_home, "state", {}) if demo.smart_home else {}
        return {
            "active": True,
            "wristband": wristband,
            "smart_home": smart_home,
            "available_scenarios": list(SCENARIOS.keys()),
        }

    @router.post("/scenario")
    async def demo_scenario(payload: dict) -> dict:
        from api.state import state  # type: ignore

        scenario_id = payload.get("scenario", "")
        if scenario_id not in SCENARIOS:
            return {"ok": False, "error": f"unknown scenario {scenario_id!r}"}
        if not getattr(state, "_demo", None):
            return {"ok": False, "error": "demo orchestrator not running"}
        runner = ScenarioRunner(state._demo)
        asyncio.create_task(runner.run(SCENARIOS[scenario_id]))
        return {"ok": True, "scenario": scenario_id}

    return router


def cli_handler(scenario: str = "") -> None:
    """Handle the ``feral demo`` invocation when this package is installed.

    Imported lazily by ``feral-core/cli/main.py`` only after detecting
    the ``demo`` entry point, so the core CLI module never depends on
    ``feral_demo_data`` at import time.
    """
    os.environ["FERAL_DEV_DEMO"] = "1"
    os.environ["FERAL_DEV_DEMO_FORCE"] = "1"

    if not scenario:
        from feral_demo_data.scenarios import SCENARIOS

        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║     F E R A L   D E M O              ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        print("  Available demo scenarios:")
        print()
        for key, scen in SCENARIOS.items():
            print(f"    {key:12s}  {scen['description']}")
        print()
        print("  Usage: feral demo --scenario <name>")
        print()
        return

    os.environ["FERAL_DEMO_SCENARIO"] = scenario
    print(f"\n  Launching FERAL in demo mode with scenario: {scenario}\n")

    from cli.main import cmd_start  # type: ignore

    cmd_start(no_browser=False)
