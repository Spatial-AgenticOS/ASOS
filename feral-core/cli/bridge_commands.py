"""``feral bridge`` CLI — one-liner installer for the phone-bridge daemon.

Thin wrapper around ``scripts/install-phone-bridge.sh`` so the v2 Pair
modal's copy-paste one-liner is exactly what the CLI user types. We
keep the shell script as the source of truth (launchctl / systemctl
logic is OS-specific) and expose it here + over HTTP so a fresh machine
can bootstrap with one curl-into-bash.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    # feral-core/cli/bridge_commands.py -> ../../ = repo root
    return Path(__file__).resolve().parent.parent.parent


def _script_path() -> Path:
    return _repo_root() / "scripts" / "install-phone-bridge.sh"


def cmd_bridge(args) -> None:
    action = getattr(args, "action", "") or ""
    if action != "install":
        print("usage: feral bridge install --token <T> --brain-url <URL> [--node-id <ID>] [--prefix <PATH>]")
        sys.exit(2)

    script = _script_path()
    if not script.exists():
        print(f"error: installer not found at {script}", file=sys.stderr)
        print("This is a repo checkout issue; the released package ships the script via /install-phone-bridge.sh.", file=sys.stderr)
        sys.exit(1)

    cmd = [
        "bash", str(script),
        "--token", args.token,
        "--brain-url", args.brain_url,
    ]
    if getattr(args, "node_id", ""):
        cmd.extend(["--node-id", args.node_id])
    if getattr(args, "prefix", ""):
        cmd.extend(["--prefix", args.prefix])

    env = os.environ.copy()
    print(f"→ bash {script} --token {args.token[:6]}... --brain-url {args.brain_url}")
    result = subprocess.run(cmd, env=env)
    sys.exit(result.returncode)
