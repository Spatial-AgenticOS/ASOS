"""``feral grant`` — workspace folder access lever.

The computer_use file tools refuse paths outside the policy's
``read_paths`` / ``write_paths`` lists. Operators use this command to
grant explicit folders (Desktop, Documents, project dirs) without
globally widening the home directory.

Granted folders are persisted to ``~/.feral/workspace_grants.json``
via :class:`security.sandbox_policy.SandboxPolicy`. The same store is
read by the running brain, so changes take effect immediately on the
next file-tool call (no restart required).

Subcommands:
  - ``feral grant add <path> [--mode read|readwrite]`` — grant access.
  - ``feral grant list`` — show every active grant.
  - ``feral grant revoke <path>`` — remove a grant.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional


def _policy():
    """Load the SandboxPolicy without booting the brain.

    The CLI must work offline (e.g. before `feral start`). The grants
    file is the source of truth; SandboxPolicy reads it on every
    can_*_path() call, so no in-memory cache needs invalidating.
    """
    from security.sandbox_policy import SandboxPolicy

    return SandboxPolicy.load_default()


def cmd_grant(args: argparse.Namespace) -> int:
    action = getattr(args, "action", None)
    if action in (None, "list"):
        return _list()
    if action == "add":
        path = getattr(args, "path", "") or ""
        mode = getattr(args, "mode", "readwrite") or "readwrite"
        return _add(path, mode)
    if action == "revoke":
        path = getattr(args, "path", "") or ""
        return _revoke(path)
    print(f"Unknown action: {action}. Try one of: add, list, revoke.")
    return 2


def _list() -> int:
    grants = _policy().list_grants()
    if not grants:
        print("  No workspace grants. Add one with:")
        print("    feral grant add ~/Desktop")
        return 0
    print("  FERAL Workspace Grants")
    print("  " + "=" * 60)
    for g in grants:
        granted_at = g.get("granted_at")
        ts = ""
        if isinstance(granted_at, (int, float)) and granted_at > 0:
            ts = time.strftime(" (granted %Y-%m-%d %H:%M)", time.localtime(granted_at))
        mode = g.get("mode", "read")
        print(f"  {mode:<10} {g.get('path', '')}{ts}")
    return 0


def _add(path: str, mode: str) -> int:
    if not path:
        print("  No path supplied. Usage: feral grant add <path> [--mode readwrite]")
        return 2
    target = Path(path).expanduser()
    if not target.exists():
        print(f"  Refusing to grant {target}: path does not exist on disk.")
        print("  Create the folder first, then grant it. FERAL will not")
        print("  fabricate a grant for a path the OS doesn't have.")
        return 1
    if not target.is_dir():
        print(f"  Refusing to grant {target}: not a directory.")
        return 1

    result = _policy().grant_folder(str(target), mode=mode)
    if not result.get("ok"):
        print(f"  Grant FAILED: {result.get('error', 'unknown error')}")
        return 1
    print(f"  Granted {result.get('mode')} access to {result.get('path')}.")
    print("  computer_use file tools can now read/write inside that folder.")
    return 0


def _revoke(path: str) -> int:
    if not path:
        print("  No path supplied. Usage: feral grant revoke <path>")
        return 2
    target = Path(path).expanduser()
    removed = _policy().revoke_folder(str(target))
    if not removed:
        print(f"  No active grant for {target}. Nothing to revoke.")
        return 1
    print(f"  Revoked workspace grant for {target}.")
    return 0


# ─────────────────────────────────────────────────────────────────
# Stand-alone entry point (`python -m cli.grant_commands …`)
# ─────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="feral grant")
    sub = parser.add_subparsers(dest="action")

    add_p = sub.add_parser("add", help="Grant a folder")
    add_p.add_argument("path")
    add_p.add_argument("--mode", choices=("read", "readwrite"), default="readwrite")

    sub.add_parser("list", help="List active grants")

    revoke_p = sub.add_parser("revoke", help="Revoke a folder grant")
    revoke_p.add_argument("path")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return cmd_grant(args)


if __name__ == "__main__":
    raise SystemExit(main())
