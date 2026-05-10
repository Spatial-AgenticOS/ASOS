#!/usr/bin/env python3
"""DEPRECATED — thin shim that delegates to ``scripts/sync_versions.py``.

Historical role: this file used to carry its own
``VERSION_LOCATIONS`` list parallel to ``scripts/sync_versions.py``.
The two lists drifted out of sync (audit-r7 brief 8 §11), causing real
CI failures: a literal lived in only one of the two and the
``test_single_calver_across_all_files`` gate flagged the other.

In ``phase-1/truthfulness-sweep`` we consolidated the canonical list
in ``scripts/sync_versions.py``; this file now exists only so the
external CLI surface (``python3 scripts/bump_version.py 2026.5.17``)
remains stable for any docs / runbooks that still cite it.

New code MUST use ``scripts/sync_versions.py`` directly:

    # bump:
    # 1. Edit feral-core/pyproject.toml's [project] version literal.
    # 2. Run:
    python3 scripts/sync_versions.py --write

    # check:
    python3 scripts/sync_versions.py --check

This shim:

* Accepts the legacy positional ``<version>`` and ``--check`` flag.
* Edits ``feral-core/pyproject.toml`` to the requested version (the
  upstream of ``sync_versions``' source-of-truth resolution chain).
* Then forwards to ``sync_versions.py`` so every other location is
  rewritten or checked off the same list.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ASOS_ROOT = Path(__file__).resolve().parent.parent
CALVER_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")
VERSION_PATTERN = r"(?P<version>\d{4}\.\d{1,2}\.\d{1,2})"

PYPROJECT = ASOS_ROOT / "feral-core" / "pyproject.toml"
SYNC_SCRIPT = ASOS_ROOT / "scripts" / "sync_versions.py"


def _set_pyproject_version(new_version: str, *, check: bool) -> bool:
    """Rewrite (or just probe) the [project] version in feral-core/pyproject.toml.

    Returns True if the file would change / did change. The shim
    keeps writing to this file directly because ``sync_versions.py``
    treats it as the upstream of its source-of-truth resolution
    chain — bumping it is what makes the propagate step downstream do
    work.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    pat = re.compile(rf'(?m)^version = "{VERSION_PATTERN}"')
    m = pat.search(text)
    if m is None:
        raise SystemExit(
            f"could not locate [project] version literal in {PYPROJECT}"
        )
    if m.group("version") == new_version:
        return False
    if check:
        return True
    new_text = pat.sub(f'version = "{new_version}"', text, count=1)
    PYPROJECT.write_text(new_text, encoding="utf-8")
    return True


def _run_sync(*, check: bool) -> int:
    """Forward to scripts/sync_versions.py with --check or --write."""
    cmd = [sys.executable, str(SYNC_SCRIPT)]
    cmd.append("--check" if check else "--write")
    cmd.append("--no-metadata")
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bump_version",
        description=(
            "DEPRECATED shim. Delegates to scripts/sync_versions.py. "
            "Bumps feral-core/pyproject.toml and then propagates."
        ),
    )
    parser.add_argument(
        "version",
        help="New calver version, e.g. 2026.5.17",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry run: print what would change without writing files.",
    )
    args = parser.parse_args(argv)

    if not CALVER_RE.match(args.version):
        raise SystemExit(
            f"version {args.version!r} does not look like YYYY.M.D"
        )

    print(
        "scripts/bump_version.py is a deprecated shim — "
        "future invocations should use scripts/sync_versions.py "
        "directly. Forwarding…",
        file=sys.stderr,
    )

    changed = _set_pyproject_version(args.version, check=args.check)
    if args.check:
        verb = "would set" if changed else "already at"
        print(f"feral-core/pyproject.toml: {verb} version {args.version}")
    else:
        verb = "set" if changed else "already at"
        print(f"feral-core/pyproject.toml: {verb} version {args.version}")

    return _run_sync(check=args.check)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
