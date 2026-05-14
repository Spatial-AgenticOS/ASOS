"""``feral access`` CLI subcommands.

Thin shim over :mod:`cli.setup.network` (the shared core also used by
the ``feral setup`` network step). Keeping the persistence + Tailscale
remediation rules in one place means ``feral access status`` and the
wizard step can never disagree about what "remote mode" looks like.

Usage::

    feral access status         # show pairing mode + Tailscale state
    feral access remote-up      # enable Funnel, switch to remote mode
    feral access remote-down    # disable Funnel, revert to localhost
"""

from __future__ import annotations

import asyncio
import sys

from cli import ui_kit


def _print_status(snap) -> None:
    from cli.setup.network import render_snapshot_lines

    print()
    for line in render_snapshot_lines(snap):
        print(line)
    print()


def _do_status() -> int:
    from cli.setup.network import get_snapshot

    snap = asyncio.run(get_snapshot())
    ui_kit.brand_panel("feral access — status")
    _print_status(snap)
    return 0


def _do_remote_up() -> int:
    from cli.setup.network import NetworkApplyError, apply_tailscale_funnel

    ui_kit.brand_panel("feral access — enabling Tailscale Funnel")
    try:
        snap = asyncio.run(apply_tailscale_funnel())
    except NetworkApplyError as exc:
        print()
        print(f"  Failed: {exc.code}")
        print(f"  → {exc}")
        if exc.remediation:
            if exc.code == "funnel_disabled_in_tailnet" and exc.remediation.startswith(
                "https://login.tailscale.com/f/funnel"
            ):
                print()
                print("  → ONE-CLICK ENABLE (free, ~5 seconds):")
                print(f"     {exc.remediation}")
                print(
                    "  → After clicking, re-run "
                    "`feral access remote-up`."
                )
            else:
                print(f"  Remediation: {exc.remediation}")
        print()
        return 1

    print()
    print("  Mode C enabled.")
    print(f"  Pairing URL host: {snap.remote_url}")
    print(f"  pairing_mode now: {snap.mode}")
    print()
    print("  Generate a pair URL with `feral pair --name <phone-name>` and")
    print("  scan it from anywhere on the internet.")
    print()
    return 0


def _do_remote_down() -> int:
    from cli.setup.network import NetworkApplyError, disable_tailscale_funnel

    ui_kit.brand_panel("feral access — disabling Tailscale Funnel")
    try:
        snap = asyncio.run(disable_tailscale_funnel())
    except NetworkApplyError as exc:
        print(f"\n  Failed: {exc.code} — {exc}\n")
        return 1
    print()
    print("  Mode C disabled. Pairing reverted to localhost mode.")
    print(f"  pairing_mode now: {snap.mode}")
    print()
    return 0


def cmd_access(args) -> int:
    action = getattr(args, "action", None) or "status"
    if action == "status":
        return _do_status()
    if action == "remote-up":
        return _do_remote_up()
    if action == "remote-down":
        return _do_remote_down()
    print(
        f"  Unknown access action '{action}'. Use status / remote-up / remote-down.",
        file=sys.stderr,
    )
    return 2
