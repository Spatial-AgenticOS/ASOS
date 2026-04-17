"""FERAL API Key management — load or generate on first boot.

Extracted to a standalone module so cli.setup_wizard can import
without triggering the heavy server.py init.
"""

import os
import secrets
from pathlib import Path


def get_api_key_path() -> Path:
    """Return the path where the FERAL API key is stored."""
    return Path(os.environ.get("FERAL_HOME", str(Path.home() / ".feral"))) / "api_key"


def load_or_generate_api_key() -> str:
    """Load FERAL_API_KEY from env or ~/.feral/api_key; generate on first boot."""
    env_key = os.environ.get("FERAL_API_KEY", "").strip()
    if env_key:
        return env_key

    key_path = get_api_key_path()
    if key_path.exists():
        key = key_path.read_text().strip()
        if key:
            return key

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    key_path.write_text(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


def load_api_key():
    """Read-only loader: returns key from env or ~/.feral/api_key, or None.
    Never generates a new key.
    """
    env_key = os.environ.get("FERAL_API_KEY", "").strip()
    if env_key:
        return env_key
    key_path = get_api_key_path()
    if key_path.exists():
        key = key_path.read_text().strip()
        if key:
            return key
    return None
