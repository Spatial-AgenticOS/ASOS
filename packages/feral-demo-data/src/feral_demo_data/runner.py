"""
FERAL One-Command Demo Runner
================================
Run a complete demo scenario with one command:

    feral demo --scenario morning
    feral demo --scenario developer
    feral demo --scenario mesh
    feral demo  (interactive — pick a scenario)

Launches the brain in demo mode, runs the scenario, and shows results.
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys
import time

logger = logging.getLogger("feral.demo.runner")


def run_demo(scenario: str = ""):
    """Entry point for the demo runner."""
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
        for key, s in SCENARIOS.items():
            print(f"    {key:12s}  {s['description']}")
        print()
        print("  Usage: feral demo --scenario <name>")
        print("  Or:    feral demo  (launches with all features enabled)")
        print()
        return

    os.environ["FERAL_DEMO_SCENARIO"] = scenario
    print(f"\n  Launching FERAL in demo mode with scenario: {scenario}\n")

    from cli.main import cmd_start
    cmd_start(no_browser=False)
