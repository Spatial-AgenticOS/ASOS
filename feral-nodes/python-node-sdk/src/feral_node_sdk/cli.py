"""Shippable CLI for the Python node SDK.

Vendors bundle this with their daemon so operators can run
``python -m feral_node_sdk pair --node-id foo --brain wss://...`` without
writing any code. Currently supports the `pair`, `discover`, and `version`
subcommands.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

from . import __version__
from .discovery import discover_brain
from .pairing import load_key, pair


def _cmd_pair(args: argparse.Namespace) -> int:
    brain = args.brain
    if not brain:
        brain = asyncio.run(discover_brain(timeout_s=3.0))
    if not brain:
        print("error: no --brain provided and mDNS discovery found nothing.", file=sys.stderr)
        return 2
    try:
        asyncio.run(pair(
            node_id=args.node_id,
            brain_url=brain,
            code=args.code,
            name=args.name or args.node_id,
            timeout_s=args.timeout,
            verify_tls=not args.insecure,
        ))
        return 0
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


def _cmd_discover(args: argparse.Namespace) -> int:
    url: Optional[str] = asyncio.run(discover_brain(timeout_s=args.timeout))
    if url:
        print(url)
        return 0
    print("no brain found", file=sys.stderr)
    return 1


def _cmd_key(args: argparse.Namespace) -> int:
    k = load_key(args.node_id)
    if k:
        print(k)
        return 0
    print("no key stored", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="feral-node",
        description="FERAL HUP v1 node CLI (pair, discover, inspect keys).",
    )
    p.add_argument("--version", action="version", version=f"feral-node-sdk {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pair", help="Run the 6-digit pairing flow.")
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--brain", default=None, help="wss:// URL; defaults to mDNS discovery.")
    sp.add_argument("--code", default=None, help="Use a specific 6-digit code (default: random).")
    sp.add_argument("--name", default="", help="Human-readable device name.")
    sp.add_argument("--timeout", type=float, default=300.0)
    sp.add_argument("--insecure", action="store_true", help="Skip TLS verification (dev only).")
    sp.set_defaults(func=_cmd_pair)

    sd = sub.add_parser("discover", help="Print the URL of the first FERAL brain on the LAN.")
    sd.add_argument("--timeout", type=float, default=3.0)
    sd.set_defaults(func=_cmd_discover)

    sk = sub.add_parser("key", help="Print the stored API key for a node (if any).")
    sk.add_argument("--node-id", required=True)
    sk.set_defaults(func=_cmd_key)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
