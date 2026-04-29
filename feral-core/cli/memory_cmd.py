"""`feral memory` subcommand — view + switch the memory backend.

Usage
-----
    feral memory status          show which backend is active, counts, dim
    feral memory list            list known backend ids + whether deps are installed
    feral memory switch chroma   switch to the Chroma backend (persists to config)

The config key is ``memory.backend`` in ``~/.feral/settings.json``.
Switching is cheap: it's just a config change. The brain reloads the
backend on next start. There is no live-reload endpoint today: until
the vector-adapter wiring lands (MEMORY_SYSTEM_FIX_PLAN Phase 1A) the
brain stores chunk embeddings in ``memory.db`` regardless of this
setting. ``GET /api/memory/backend`` exposes ``active_store`` +
``pending_unapplied`` so dashboards can surface the gap honestly.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from config.loader import feral_home

_KNOWN_BACKENDS = {
    "sqlite_vec": ("memory.backends.sqlite_vec", "built-in (default)"),
    "chroma": ("memory.backends.chroma", "pip install feral-ai[memory-chroma]"),
    "qdrant": ("memory.backends.qdrant", "pip install feral-ai[memory-qdrant]"),
}


def _settings_path() -> Path:
    return feral_home() / "settings.json"


def _load_settings() -> dict:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        print(f"  Could not read {path}: {exc}")
        return {}


def _save_settings(settings: dict) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2))


def _is_installed(module_path: str) -> bool:
    try:
        importlib.import_module(module_path)
        return True
    except ImportError:
        return False


def _current_backend() -> str:
    settings = _load_settings()
    return (settings.get("memory") or {}).get("backend", "sqlite_vec")


def cmd_memory(action: str, backend_id: str | None) -> None:
    if action == "status":
        active = _current_backend()
        module_path, install_hint = _KNOWN_BACKENDS.get(
            active, ("external", "registry-installed")
        )
        installed = _is_installed(module_path) if module_path != "external" else True
        print(f"  Active memory backend: {active}")
        print(f"  Module:                {module_path}")
        print(f"  Installed:             {'yes' if installed else 'no'}")
        if not installed:
            print(f"  Install:               {install_hint}")
        return

    if action == "list":
        active = _current_backend()
        print("  Known memory backends:")
        for name, (module_path, install_hint) in _KNOWN_BACKENDS.items():
            mark = "*" if name == active else " "
            state = "installed" if _is_installed(module_path) else install_hint
            print(f"   {mark} {name:<12} {state}")
        return

    if action == "switch":
        if not backend_id:
            print("  Usage: feral memory switch <backend_id>")
            sys.exit(2)
        if backend_id not in _KNOWN_BACKENDS:
            print(f"  Unknown backend '{backend_id}'.")
            print("  Known: " + ", ".join(_KNOWN_BACKENDS.keys()))
            print("  For a community backend, run `feral install <registry_item_id>` first.")
            sys.exit(1)
        module_path, install_hint = _KNOWN_BACKENDS[backend_id]
        if not _is_installed(module_path):
            print(f"  Backend '{backend_id}' is not installed.")
            print(f"  Run:  {install_hint}")
            sys.exit(1)
        settings = _load_settings()
        mem = settings.setdefault("memory", {})
        mem["backend"] = backend_id
        _save_settings(settings)
        print(f"  Memory backend set to '{backend_id}'.")
        print("  Restart `feral start` for the change to take effect.")
        return

    print(f"  Unknown memory action: {action}")
    sys.exit(2)
