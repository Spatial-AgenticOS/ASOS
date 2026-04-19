#!/usr/bin/env python3
"""Refresh ``feral-core/providers/model_catalog.json`` from every
provider's public ``/v1/models`` endpoint.

Runs daily via ``.github/workflows/provider-research.yml``. Writes the
updated catalog in place and exits 0. The workflow then opens a PR iff
the file changed.

This is deliberately a small, dependency-free script:

* Only uses ``urllib`` (std-lib) so it works in bare GitHub Actions.
* Requires ``*_API_KEY`` env vars for providers that gate ``/v1/models``
  behind auth (OpenAI, Groq, DeepSeek, OpenRouter, Together). Providers
  without keys just keep their previous catalog entry.
* Never removes a provider entry; only updates ``models`` + timestamp.

Usage
-----
    python scripts/research_providers.py           # rewrite in place
    python scripts/research_providers.py --dry-run # print changes, don't write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "feral-core" / "providers" / "model_catalog.json"


# Providers whose ``/v1/models`` endpoint speaks OpenAI's {"data": [{"id": ...}]}
# shape. Value = name of the env var that holds the API key.
OPENAI_SHAPE = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "together": "TOGETHER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _fetch(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _refresh_openai_shape(pid: str, env_key: str, catalog_entry: dict) -> list[str] | None:
    endpoint = catalog_entry.get("endpoint")
    token = os.environ.get(env_key)
    if not endpoint or not token:
        return None
    try:
        data = _fetch(endpoint, {"Authorization": f"Bearer {token}"})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"  [{pid}] fetch failed: {exc}")
        return None
    ids = sorted({m.get("id") for m in data.get("data", []) if m.get("id")})
    return ids or None


def _refresh_gemini(catalog_entry: dict) -> list[str] | None:
    endpoint = catalog_entry.get("endpoint")
    token = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not endpoint or not token:
        return None
    url = f"{endpoint}?key={token}"
    try:
        data = _fetch(url, {})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"  [gemini] fetch failed: {exc}")
        return None
    ids = sorted({m["name"].split("/")[-1] for m in data.get("models", [])})
    return ids or None


def refresh(catalog: dict) -> tuple[dict, list[str]]:
    """Return (new_catalog, list_of_changes_by_provider)."""
    providers = catalog.setdefault("providers", {})
    changes: list[str] = []

    for pid, env_key in OPENAI_SHAPE.items():
        entry = providers.setdefault(pid, {"models": [], "pricing": {}})
        new_models = _refresh_openai_shape(pid, env_key, entry)
        if new_models and new_models != entry.get("models", []):
            entry["models"] = new_models
            changes.append(f"{pid}: {len(new_models)} models")

    # Gemini has its own auth shape.
    gemini_entry = providers.setdefault("gemini", {"models": [], "pricing": {}})
    new_gemini = _refresh_gemini(gemini_entry)
    if new_gemini and new_gemini != gemini_entry.get("models", []):
        gemini_entry["models"] = new_gemini
        changes.append(f"gemini: {len(new_gemini)} models")

    # Anthropic has no public /v1/models. Leave the hand-curated list alone.
    # Ollama's model list is per-host, not a global truth. Skip.

    if changes:
        catalog["last_fetched"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    return catalog, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print changes but don't write")
    args = ap.parse_args()

    if not CATALOG_PATH.exists():
        print(f"! {CATALOG_PATH} missing; run once to bootstrap.")
        return 1

    catalog = json.loads(CATALOG_PATH.read_text())
    new_catalog, changes = refresh(catalog)

    if not changes:
        print("no provider model lists changed")
        return 0

    print("changes:")
    for change in changes:
        print(f"  + {change}")

    if args.dry_run:
        return 0

    CATALOG_PATH.write_text(json.dumps(new_catalog, indent=2) + "\n")
    print(f"wrote {CATALOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
