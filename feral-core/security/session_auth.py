"""
FERAL Session Authentication
==============================
Token-based authentication for WebSocket sessions (/v1/session).

Tokens are 32-char hex strings persisted in ~/.feral/session_token.
Localhost connections can optionally bypass auth (FERAL_LOCAL_BYPASS).
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Optional

logger = logging.getLogger("feral.session_auth")


def _token_path() -> Path:
    home = os.environ.get("FERAL_HOME", str(Path.home() / ".feral"))
    return Path(home) / "session_token"


def generate_session_token() -> str:
    """Generate a cryptographically-secure 32-char hex token."""
    return secrets.token_hex(16)


def save_session_token(token: str) -> None:
    """Persist *token* to ~/.feral/session_token with 0600 permissions."""
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    logger.info("Session token saved to %s", path)


def load_session_token() -> Optional[str]:
    """Read the saved session token, or return ``None`` if absent."""
    path = _token_path()
    if not path.exists():
        return None
    text = path.read_text().strip()
    return text or None


def verify_session(token: str) -> bool:
    """Return ``True`` if *token* matches the persisted session token."""
    stored = load_session_token()
    if stored is None:
        return False
    return secrets.compare_digest(stored, token)


def session_auth_required() -> bool:
    """Decide whether incoming WebSocket sessions must authenticate.

    Auth is required when FERAL_SESSION_AUTH=true **or** a token file
    already exists on disk.
    """
    if os.environ.get("FERAL_SESSION_AUTH", "").lower() == "true":
        return True
    return _token_path().exists()


def is_localhost(host: str | None) -> bool:
    """Return ``True`` if *host* is a loopback address."""
    if not host:
        return False
    return host in ("127.0.0.1", "::1", "localhost")


def local_bypass_enabled() -> bool:
    """Whether localhost connections skip session auth (default ``True``)."""
    return os.environ.get("FERAL_LOCAL_BYPASS", "true").lower() in ("true", "1", "yes")
