"""Enables `python -m feral_node_sdk <subcommand>` — delegates to cli.main."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
