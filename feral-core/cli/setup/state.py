"""Shared state passed through every setup step.

Each step reads + mutates three plain dicts (``settings``,
``credentials``, ``identity``) so a step can be invoked in isolation
under tests without the full wizard running.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WizardState:
    """Single mutable object threaded through every step."""

    home: Path
    settings: dict[str, Any] = field(default_factory=dict)
    credentials: dict[str, Any] = field(default_factory=dict)
    identity: dict[str, Any] = field(default_factory=dict)
    completed_steps: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, home: Path) -> "WizardState":
        home.mkdir(parents=True, exist_ok=True)
        settings = _read_json(home / "settings.json")
        credentials = _read_json(home / "credentials.json")
        identity = _read_json(home / "identity.json")
        return cls(
            home=home, settings=settings, credentials=credentials, identity=identity
        )

    def save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        # Mark the wizard complete so future boots don't re-run it.
        self.settings.setdefault("meta", {})
        self.settings["meta"]["setup_complete"] = True
        _write_json(self.home / "settings.json", self.settings)
        _write_json(self.home / "credentials.json", self.credentials, secure=True)
        if self.identity:
            _write_json(self.home / "identity.json", self.identity)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def set_setting(self, section: str, key: str, value: Any) -> None:
        self.settings.setdefault(section, {})[key] = value

    def get_setting(self, section: str, key: str, default: Any = None) -> Any:
        return (self.settings.get(section) or {}).get(key, default)

    def set_credential(self, key: str, value: str) -> None:
        if value:
            self.credentials[key] = value

    def has_credential(self, key: str) -> bool:
        return bool(self.credentials.get(key))


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_json(path: Path, data: dict, *, secure: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    if secure:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
