"""Console entry point for ``feral-demo``.

Standalone script that runs without going through the core CLI. Use
this when developing on the demo package itself; end-users run
``feral demo`` from the brain CLI which delegates here through the
``feral.plugins`` entry point.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="feral-demo",
        description="FERAL demo runner (dev-only). Spins up simulated "
                    "wristband + smart-home + scripted scenarios.",
    )
    parser.add_argument(
        "--scenario",
        default="",
        choices=["", "morning", "developer", "mesh"],
        help="Scenario to run. Empty prints the menu.",
    )
    args = parser.parse_args(argv)

    from feral_demo_data._integration import cli_handler

    cli_handler(args.scenario)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
