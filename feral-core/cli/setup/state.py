"""Shared state passed through every setup step.

Each step reads + mutates three plain dicts (``settings``,
``credentials``, ``identity``) so a step can be invoked in isolation
under tests without the full wizard running.

Credentials persistence (A7)
----------------------------
Credentials are written to the W9 encrypted ``BlindVault`` — NEVER to
a plaintext ``credentials.json``. The vault maps ``credentials.json``
→ ``credentials.enc`` internally, so anchoring it at the wizard's
``home / credentials.json`` path keeps the encrypted payload inside
the same directory without leaving a cleartext file behind.

Backwards compatibility:

- ``load()`` still reads any existing legacy ``credentials.json`` that
  predates the vault. Instantiating the vault during ``save()``
  triggers its built-in auto-migration (``credentials.json`` →
  ``credentials.enc`` with the original moved to
  ``credentials.json.bak.legacy`` at chmod 0600) so returning users'
  keys are preserved.
- ``settings.json`` and ``identity.json`` remain plain JSON — they are
  not secret material.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("feral.cli.setup.state")


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
        credentials = _read_credentials(home)
        identity = _read_json(home / "identity.json")
        return cls(
            home=home, settings=settings, credentials=credentials, identity=identity
        )

    def save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.settings.setdefault("meta", {})
        self.settings["meta"]["setup_complete"] = True
        _write_json(self.home / "settings.json", self.settings)
        _persist_credentials(self.home, self.credentials)
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


def _read_credentials(home: Path) -> dict:
    """Return the current credential map.

    Priority order:

    1. Encrypted vault (``credentials.enc``) — authoritative post-W9.
    2. Legacy plaintext ``credentials.json`` — only present on machines
       that have not yet booted the brain since the vault migration.
       The plaintext file will be rewritten as encrypted and removed
       the next time a vault is instantiated (e.g. on ``save()``).

    Any failure to decrypt surfaces as an empty dict so the wizard can
    still complete; the user will see the usual "please re-enter your
    keys" flow rather than a traceback.
    """
    try:
        from security.vault import BlindVault
    except Exception as exc:  # pragma: no cover — import-time failure
        logger.warning(
            "setup.state: vault import failed (%s); falling back to "
            "legacy plaintext read.",
            exc,
        )
        return _read_json(home / "credentials.json")

    try:
        vault = BlindVault(vault_path=str(home / "credentials.json"))
    except Exception as exc:
        logger.warning(
            "setup.state: vault init failed (%s); returning empty creds "
            "so the wizard can proceed without leaking to plaintext.",
            exc,
        )
        return {}

    try:
        return {k: vault.retrieve(k) or "" for k in vault.list_keys()}
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("setup.state: vault read failed (%s)", exc)
        return {}


def _persist_credentials(home: Path, credentials: dict) -> None:
    """Write every credential to the encrypted vault.

    Empty values are skipped so a half-filled wizard step doesn't
    clobber an existing key with ``""``. If the vault is unavailable
    (keychain broken, cryptography missing, etc.) we refuse to fall
    back to plaintext — the credentials stay in memory for this
    process and the user is instructed to fix the vault on next boot.
    """
    flat = {k: v for k, v in credentials.items() if isinstance(v, str) and v}
    if not flat:
        return

    try:
        from security.vault import BlindVault
    except Exception as exc:  # pragma: no cover — import-time failure
        logger.error(
            "setup.state: vault import failed (%s); refusing to persist "
            "plaintext credentials. Keys remain in memory only.",
            exc,
        )
        return

    try:
        vault = BlindVault(vault_path=str(home / "credentials.json"))
    except Exception as exc:
        logger.error(
            "setup.state: vault init failed (%s); refusing to persist "
            "plaintext credentials. Keys remain in memory only.",
            exc,
        )
        return

    for key, value in flat.items():
        try:
            vault.set_credential(key, value)
        except Exception as exc:
            logger.error("setup.state: vault write for %s failed: %s", key, exc)
