"""
feral-demo-data — optional dev-only demo data + simulators for FERAL.

This package is **never** installed by `pip install feral-ai`. It ships
separately so the production brain has zero synthetic-biometric code
in its install footprint. Install via:

    pip install feral-demo-data
    # or
    pip install feral-ai[demo]

After install, the brain auto-discovers this package via the
``feral.plugins`` entry point group and `feral demo` / `feral start
--demo` work as before. Without this package installed, the brain
prints a clear install hint and refuses to silently no-op.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Public re-exports so callers can do `from feral_demo_data import
# DemoOrchestrator` without reaching into submodules.
from feral_demo_data.simulator import (
    DemoOrchestrator,
    SmartHomeSimulator,
    WristbandSimulator,
)
from feral_demo_data.scenarios import SCENARIOS, ScenarioRunner
from feral_demo_data.seed import seed_demo_identity, seed_demo_memory


def plugin() -> dict:
    """Plugin contract surfaced via ``feral.plugins`` entry point group.

    The brain calls ``importlib.metadata.entry_points(group="feral.plugins")``
    at boot, looks up the ``demo`` entry point, and invokes this function
    when (and only when) ``FERAL_DEV_DEMO`` is truthy. The returned dict
    advertises:

      - ``bootstrap(state) -> None``  — populate demo simulators on the
        live BrainState (replaces the inline import block that used to
        live in feral-core/api/state.py).
      - ``status_routes()`` — optional FastAPI router with
        ``/api/demo/status`` + ``/api/demo/scenario``.
      - ``cli_handler(scenario: str)`` — handles ``feral demo`` from the
        core CLI when this package is installed.

    Keeping this surface tiny and stable lets the brain stay oblivious
    to demo internals.
    """
    from feral_demo_data._integration import bootstrap, status_routes, cli_handler

    return {
        "name": "demo",
        "version": __version__,
        "bootstrap": bootstrap,
        "status_routes": status_routes,
        "cli_handler": cli_handler,
    }


__all__ = [
    "DemoOrchestrator",
    "SmartHomeSimulator",
    "WristbandSimulator",
    "SCENARIOS",
    "ScenarioRunner",
    "seed_demo_identity",
    "seed_demo_memory",
    "plugin",
]
