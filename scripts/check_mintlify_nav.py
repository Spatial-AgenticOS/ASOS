#!/usr/bin/env python3
"""Assert that every mdx under docs/mintlify/ is referenced by docs.json.

Mintlify's PR-preview renderer refuses to ship a build when an mdx file
exists in the docs tree but no nav entry points at it. Running this
script in CI (and the `main`-protection hook) guarantees that every new
W* deliverable remembers to wire its docs into `docs/mintlify/docs.json`.

Exit codes:
    0 — every mdx is referenced.
    1 — one or more orphans exist (printed as `orphan: <relative path>`).
    2 — cannot parse docs.json or docs tree.

Usage:
    python3 scripts/check_mintlify_nav.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKIP_DIR_NAMES = {"snippets"}


def _iter_nav_pages(doc: object):
    """Yield every string that appears under `navigation.groups[].pages[...]`.

    Mintlify allows nested groups (a page entry can itself be a group dict
    with its own `pages` list) so we walk the tree defensively.
    """
    if isinstance(doc, dict):
        if "group" in doc and "pages" in doc:
            for page in doc.get("pages") or []:
                yield from _iter_nav_pages(page)
            return
        for key in ("navigation", "groups", "pages"):
            if key in doc:
                yield from _iter_nav_pages(doc[key])
    elif isinstance(doc, list):
        for item in doc:
            yield from _iter_nav_pages(item)
    elif isinstance(doc, str):
        yield doc


def _collect_mdx(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*.mdx"):
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        if path.name.startswith("_"):
            continue
        out.append(path)
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root (defaults to the parent of scripts/).",
    )
    args = parser.parse_args(argv)

    if args.root is not None:
        repo_root = args.root.resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent

    docs_root = repo_root / "docs" / "mintlify"
    docs_json = docs_root / "docs.json"

    if not docs_root.is_dir():
        print(f"error: docs/mintlify/ not found under {repo_root}", file=sys.stderr)
        return 2
    if not docs_json.is_file():
        print(f"error: docs/mintlify/docs.json not found at {docs_json}", file=sys.stderr)
        return 2

    try:
        doc = json.loads(docs_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: docs.json is not valid JSON: {exc}", file=sys.stderr)
        return 2

    referenced: set[str] = set()
    for page in _iter_nav_pages(doc):
        referenced.add(page.removesuffix(".mdx"))

    orphans: list[str] = []
    for mdx in _collect_mdx(docs_root):
        rel = mdx.relative_to(docs_root).with_suffix("").as_posix()
        if rel not in referenced:
            orphans.append(rel)

    if orphans:
        for rel in orphans:
            print(f"orphan: {rel}")
        print(
            f"\n{len(orphans)} mdx file(s) under docs/mintlify/ have no entry "
            f"in docs/mintlify/docs.json. Add them to a nav group before the "
            f"Mintlify preview will go green.",
            file=sys.stderr,
        )
        return 1

    print(f"ok: all {len(_collect_mdx(docs_root))} mdx files are referenced in docs.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
