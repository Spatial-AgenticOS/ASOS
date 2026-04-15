"""
FERAL Runtime Contract helpers.

One place for listen/public URL and local service defaults so app, CLI, and
desktop wrappers do not drift across hardcoded localhost/port assumptions.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def _int_env(*keys: str, default: int) -> int:
    for key in keys:
        value = os.getenv(key)
        if value is None:
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return default


def brain_bind_host() -> str:
    return os.getenv("FERAL_HOST") or os.getenv("FERAL_BIND_HOST") or "127.0.0.1"


def brain_port() -> int:
    return _int_env("FERAL_PORT", "FERAL_BRAIN_PORT", default=9090)


def brain_public_scheme() -> str:
    return os.getenv("FERAL_PUBLIC_SCHEME", "http")


def brain_public_host() -> str:
    return (
        os.getenv("FERAL_PUBLIC_HOST")
        or os.getenv("FERAL_BRAIN_HOST")
        or "localhost"
    )


def brain_public_port() -> int:
    return _int_env("FERAL_PUBLIC_PORT", "FERAL_BRAIN_PORT", "FERAL_PORT", default=9090)


def brain_public_base_url() -> str:
    explicit = os.getenv("FERAL_PUBLIC_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    scheme = brain_public_scheme()
    host = brain_public_host()
    port = brain_public_port()
    default_port = 443 if scheme == "https" else 80
    suffix = "" if port == default_port else f":{port}"
    return f"{scheme}://{host}{suffix}"


def ws_base_url() -> str:
    parsed = urlparse(brain_public_base_url())
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    suffix = f":{parsed.port}" if parsed.port else ""
    return f"{ws_scheme}://{parsed.hostname}{suffix}"


def market_registry_url() -> str:
    return os.getenv("FERAL_MARKETPLACE_URL", "http://localhost:8080/api/v1")


def brain_tls_enabled() -> bool:
    return os.getenv("FERAL_TLS", "").lower() in ("1", "true", "yes")


def brain_tls_cert() -> str:
    return os.getenv("FERAL_TLS_CERT", str(Path.home() / ".feral" / "tls" / "cert.pem"))


def brain_tls_key() -> str:
    return os.getenv("FERAL_TLS_KEY", str(Path.home() / ".feral" / "tls" / "key.pem"))


def ollama_base_url() -> str:
    return os.getenv("FERAL_OLLAMA_BASE_URL", "http://localhost:11434")


def ollama_openai_base_url() -> str:
    base = ollama_base_url().rstrip("/")
    return f"{base}/v1"
