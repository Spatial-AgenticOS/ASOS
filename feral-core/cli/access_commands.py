"""``feral access`` CLI subcommands.

Maps to the REST endpoints in ``api/routes/access.py``. The CLI prints
human-readable output and returns shell exit codes; the in-process
``integrations/tailscale`` module does the actual Tailscale work.

Usage::

    feral access status         # show pairing mode + Tailscale state
    feral access remote-up      # enable Funnel, switch to remote mode
    feral access remote-down    # disable Funnel, revert to localhost
"""

from __future__ import annotations

import sys
from typing import Any


def _print_status(snap_dict: dict) -> None:
    print()
    mode = snap_dict.get("pairing_mode", "?")
    print(f"  Pairing mode: {mode}")
    remote_url = snap_dict.get("remote_url", "")
    if remote_url:
        print(f"  Remote URL:   {remote_url}")
    else:
        print("  Remote URL:   (none — switch to remote with `feral access remote-up`)")
    ts = snap_dict.get("tailscale", {}) or {}
    if ts.get("installed"):
        if ts.get("running") and ts.get("logged_in"):
            print(f"  Tailscale:    OK — {ts.get('dns_name', '')} ({ts.get('ipv4', '')})")
            tn = ts.get("tailnet")
            if tn:
                print(f"  Tailnet:      {tn}")
        elif ts.get("running"):
            print("  Tailscale:    daemon running but not logged in. "
                  "Run `tailscale up` then retry.")
        else:
            print("  Tailscale:    daemon NOT running. Start the menubar app "
                  "(macOS) or `sudo systemctl start tailscaled` (Linux).")
    else:
        print("  Tailscale:    NOT installed. "
              "macOS: `brew install --cask tailscale`. "
              "Linux: `curl -fsSL https://tailscale.com/install.sh | sh`.")
    fn = snap_dict.get("funnel", {}) or {}
    if fn.get("active"):
        ports = ", ".join(str(p) for p in (fn.get("ports") or []))
        print(f"  Funnel:       ACTIVE on port(s) {ports or '?'}")
    else:
        print("  Funnel:       not active")
    print()


def _do_status() -> int:
    from api.routes.access import access_status
    import asyncio
    snap = asyncio.run(access_status())
    _print_status(snap)
    return 0


def _do_remote_up() -> int:
    from api.routes.access import access_remote_up
    from fastapi import HTTPException
    import asyncio
    try:
        result = asyncio.run(access_remote_up())
    except HTTPException as exc:
        detail: Any = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", "unknown")
            print(f"\n  Failed: {code}")
            print(f"  → {detail.get('message', '')}")
            rem = detail.get("remediation")
            if rem:
                # Highlight the activation URL specifically since that's
                # the most actionable case.
                if code == "funnel_disabled_in_tailnet" and rem.startswith(
                    "https://login.tailscale.com/f/funnel"
                ):
                    print()
                    print("  → ONE-CLICK ENABLE (free, ~5 seconds):")
                    print(f"     {rem}")
                    print(
                        "  → After clicking, re-run "
                        "`feral access remote-up`."
                    )
                else:
                    print(f"  Remediation: {rem}")
        else:
            print(f"\n  Failed: {detail}")
        print()
        return 1
    print()
    print("  Mode C enabled.")
    print(f"  Pairing URL host: {result.get('remote_url', '')}")
    print(f"  pairing_mode now: {result.get('pairing_mode', '')}")
    print()
    print("  Generate a pair URL with `feral pair --name <phone-name>` and")
    print("  scan it from anywhere on the internet.")
    print()
    return 0


def _do_remote_down() -> int:
    from api.routes.access import access_remote_down
    from fastapi import HTTPException
    import asyncio
    try:
        result = asyncio.run(access_remote_down())
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        print(f"\n  Failed: {detail.get('code', 'unknown')} — {detail.get('message', '')}\n")
        return 1
    print()
    print("  Mode C disabled. Pairing reverted to localhost mode.")
    print(f"  pairing_mode now: {result.get('pairing_mode', '')}")
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
    print(f"  Unknown access action '{action}'. Use status / remote-up / remote-down.",
          file=sys.stderr)
    return 2
