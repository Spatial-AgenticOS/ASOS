"""
THEORA One-Command Demo Runner
================================
Run a complete demo scenario with one command:

    theora demo --scenario morning
    theora demo --scenario developer
    theora demo --scenario mesh
    theora demo  (interactive — pick a scenario)

Launches the brain in demo mode, runs the scenario, and shows results.
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys
import time

logger = logging.getLogger("theora.demo.runner")


def run_demo(scenario: str = ""):
    """Entry point for the demo runner."""
    os.environ["THEORA_DEMO"] = "1"
    os.environ["THEORA_DEMO_FORCE"] = "1"

    if not scenario:
        from demo.scenarios import SCENARIOS
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║     T H E O R A   D E M O           ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        print("  Available demo scenarios:")
        print()
        for key, s in SCENARIOS.items():
            print(f"    {key:12s}  {s['description']}")
        print()
        print("  Usage: theora demo --scenario <name>")
        print("  Or:    theora demo  (launches with all features enabled)")
        print()
        return

    os.environ["THEORA_DEMO_SCENARIO"] = scenario
    print(f"\n  Launching THEORA in demo mode with scenario: {scenario}\n")

    from cli.main import cmd_start
    cmd_start(no_browser=False)
