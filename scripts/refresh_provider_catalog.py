#!/usr/bin/env python3
"""Refresh ``feral-core/providers/model_catalog.json`` from live provider APIs.

Usage::

    # Dry-run — fetch nothing, print the target URLs + the drift
    # count vs the current catalog. Safe to run without keys.
    scripts/refresh_provider_catalog.py --dry-run

    # Full refresh — writes the catalog + per-provider fixtures, using
    # whichever env vars the host has set. Providers without a key are
    # skipped with an honest log line.
    scripts/refresh_provider_catalog.py

The script is idempotent and never touches a provider the host has no
credentials for. Output shape matches the shipped catalog so the
existing ``ProviderCatalog`` loader picks up the refreshed data
without a code change.

See ``docs/mintlify/providers/model-classes.mdx`` for a user-facing
summary of when / how to run this.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make ``feral-core/`` importable when the script is run from the repo
# root or from inside the feral-core dir.
REPO_ROOT = Path(__file__).resolve().parent.parent
FERAL_CORE = REPO_ROOT / "feral-core"
sys.path.insert(0, str(FERAL_CORE))


from providers.anthropic_provider import AnthropicProvider  # noqa: E402
from providers.deepseek_provider import DeepSeekProvider  # noqa: E402
from providers.gemini_provider import GeminiProvider  # noqa: E402
from providers.groq_provider import GroqProvider  # noqa: E402
from providers.openai_provider import OpenAIProvider  # noqa: E402
from providers.openrouter_provider import OpenRouterProvider  # noqa: E402


CATALOG_PATH = FERAL_CORE / "providers" / "model_catalog.json"
FIXTURES_DIR = FERAL_CORE / "tests" / "fixtures"


logger = logging.getLogger("feral.refresh-catalog")


PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "openai",
        "env": "OPENAI_API_KEY",
        "endpoint": "https://api.openai.com/v1/models",
        "adapter": lambda key: OpenAIProvider(api_key=key),
    },
    {
        "id": "anthropic",
        "env": "ANTHROPIC_API_KEY",
        "endpoint": "https://api.anthropic.com/v1/models",
        "adapter": lambda key: AnthropicProvider(api_key=key),
    },
    {
        "id": "deepseek",
        "env": "DEEPSEEK_API_KEY",
        "endpoint": "https://api.deepseek.com/v1/models",
        "adapter": lambda key: DeepSeekProvider(api_key=key),
    },
    {
        "id": "gemini",
        "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "adapter": lambda key: GeminiProvider(api_key=key),
    },
    {
        "id": "groq",
        "env": "GROQ_API_KEY",
        "endpoint": "https://api.groq.com/openai/v1/models",
        "adapter": lambda key: GroqProvider(api_key=key),
    },
    {
        "id": "openrouter",
        "env": "OPENROUTER_API_KEY",
        # OpenRouter's /models is public — refresh works without a key.
        "endpoint": "https://openrouter.ai/api/v1/models",
        "adapter": lambda key: OpenRouterProvider(api_key=key or "optional"),
        "keyless_ok": True,
    },
]


def _resolve_key(env: str | list[str]) -> str | None:
    names = [env] if isinstance(env, str) else list(env)
    for n in names:
        val = os.environ.get(n)
        if val:
            return val
    return None


def _load_current_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"schema_version": 3, "providers": {}}
    return json.loads(CATALOG_PATH.read_text())


def _write_catalog(catalog: dict[str, Any]) -> None:
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2) + "\n")
    logger.info("wrote %s", CATALOG_PATH.relative_to(REPO_ROOT))


async def _refresh_one(provider: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    pid = provider["id"]
    key = _resolve_key(provider["env"])
    result: dict[str, Any] = {
        "provider_id": pid,
        "endpoint": provider["endpoint"],
        "status": "skipped",
        "models": [],
        "drift": 0,
    }
    if not key and not provider.get("keyless_ok"):
        result["status"] = "skipped (no key)"
        return result
    if dry_run:
        result["status"] = "dry-run"
        return result
    try:
        adapter = provider["adapter"](key)
        live_models = await adapter.refresh_models() or []
    except Exception as exc:  # pragma: no cover — defensive
        result["status"] = f"failed: {exc}"
        return result
    result["models"] = sorted(live_models)
    result["status"] = "ok" if live_models else "empty"
    return result


def _compute_drift(current: dict[str, Any], refreshed: dict[str, Any]) -> int:
    """Return how many IDs differ between the current catalog and the refresh."""
    curr_ids = set(
        (current.get("providers") or {}).get(refreshed["provider_id"], {}).get("models", [])
    )
    live_ids = set(refreshed["models"])
    return len(curr_ids.symmetric_difference(live_ids))


def _write_fixture(pid: str, models: list[str]) -> None:
    """Mirror the adapter's native response shape so the classifier tests
    can re-use the fixture without a translation layer."""
    if not models:
        return
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURES_DIR / f"{pid}_models.json"
    if pid == "anthropic":
        body = {"data": [{"id": m, "type": "model"} for m in models],
                "has_more": False}
    elif pid == "gemini":
        body = {"models": [{"name": f"models/{m}"} for m in models]}
    elif pid == "openrouter":
        body = {"data": [{"id": m, "architecture": {"modality": "text"}} for m in models]}
    else:
        body = {"object": "list", "data": [{"id": m, "object": "model"} for m in models]}
    path.write_text(json.dumps(body, indent=2) + "\n")
    logger.info("wrote fixture %s", path.relative_to(REPO_ROOT))


async def _run(dry_run: bool) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    current = _load_current_catalog()
    refreshed = await asyncio.gather(
        *[_refresh_one(p, dry_run=dry_run) for p in PROVIDERS]
    )
    total_drift = 0
    report_lines: list[str] = []
    for summary in refreshed:
        pid = summary["provider_id"]
        status = summary["status"]
        if status not in ("ok", "empty", "dry-run") or dry_run:
            report_lines.append(
                f"  - {pid:12s}  {status:32s}  drift=0 (dry-run or skipped)"
            )
            continue
        drift = _compute_drift(current, summary)
        total_drift += drift
        report_lines.append(
            f"  - {pid:12s}  {status:10s}  {len(summary['models'])} models, drift={drift}"
        )
        if not dry_run and summary["models"]:
            providers_block = current.setdefault("providers", {}).setdefault(pid, {})
            providers_block["endpoint"] = summary["endpoint"]
            providers_block["models"] = summary["models"]
            _write_fixture(pid, summary["models"])

    if not dry_run and total_drift >= 0:
        current["schema_version"] = current.get("schema_version") or 3
        current["last_fetched"] = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        _write_catalog(current)

    print("Provider catalog refresh:")
    for line in report_lines:
        print(line)
    print(f"  drift = {total_drift}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the target URLs + drift vs current catalog; no HTTP; no file writes.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
