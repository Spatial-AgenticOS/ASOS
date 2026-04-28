"""LLM failover support: retry, error classification, cooldown tracking.

Extracted from ``agents.llm_provider`` (W3-A15) to keep the orchestrator
facade focused on dispatch. No behaviour changes — every public symbol
here was previously a module-level name in ``agents.llm_provider`` and
is re-exported from there for import compatibility.
"""

from __future__ import annotations

import asyncio
import logging
import time
import httpx
from enum import Enum
from typing import Any

logger = logging.getLogger("feral.llm")

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # seconds
_RETRIABLE_CODES = ("429", "500", "502", "503", "504", "timeout", "connection")

# DeepSeek's streaming SSE keeps the connection open by sending
# ``: keep-alive`` comment lines (per the 2026-04-26 spec, the
# connection may stay open up to 10 minutes during thinking). The
# streaming path must treat these as liveness signals, not terminators.
_SSE_KEEPALIVE_PREFIXES = (": ", ":", ": keep-alive", ":OPENROUTER PROCESSING")


async def _retry_llm_call(coro_factory):
    """Retry an LLM HTTP call with exponential backoff on transient errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return await coro_factory()
        except Exception as e:
            err_str = str(e).lower()
            retriable = any(code in err_str for code in _RETRIABLE_CODES)
            if not retriable or attempt == MAX_RETRIES - 1:
                raise
            logger.warning("LLM call failed (attempt %d/%d): %s — retrying in %ds",
                           attempt + 1, MAX_RETRIES, e, RETRY_DELAYS[attempt])
            await asyncio.sleep(RETRY_DELAYS[attempt])


class FailoverReason(str, Enum):
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    AUTH_PERMANENT = "auth_permanent"
    BILLING = "billing"
    MODEL_NOT_FOUND = "model_not_found"
    CONTEXT_OVERFLOW = "context_overflow"
    TIMEOUT = "timeout"
    OVERLOADED = "overloaded"
    UNKNOWN = "unknown"


def classify_error(error: Exception) -> FailoverReason:
    """Classify an LLM error into a failover reason for routing decisions."""
    err_str = str(error).lower()
    status = getattr(error, "status_code", 0) or 0
    if hasattr(error, "response"):
        status = getattr(error.response, "status_code", status) or status

    if status == 429 or "rate" in err_str or "quota" in err_str:
        return FailoverReason.RATE_LIMIT
    # 401/403 with an explicit "invalid" or "incorrect" API-key message is a
    # permanent-while-current-key-is-in-place failure. Promote so the cooldown
    # tracker keeps the broken provider out of rotation for 24 h — otherwise
    # we'd probe it every 30 s and the user would see an error log stream.
    hard_key = (
        "invalid api key" in err_str
        or "incorrect api key" in err_str
        or "invalid_api_key" in err_str
        or "api key not valid" in err_str
    )
    if status in (401, 403) and hard_key:
        return FailoverReason.AUTH_PERMANENT
    if status in (401, 403) or "unauthorized" in err_str or "invalid api key" in err_str:
        return FailoverReason.AUTH
    if "billing" in err_str or "payment" in err_str or "insufficient" in err_str:
        return FailoverReason.BILLING
    if status == 404 or ("model" in err_str and "not found" in err_str):
        return FailoverReason.MODEL_NOT_FOUND
    if "context" in err_str and ("length" in err_str or "overflow" in err_str or "too long" in err_str):
        return FailoverReason.CONTEXT_OVERFLOW
    if "timeout" in err_str or status == 408 or "timed out" in err_str:
        return FailoverReason.TIMEOUT
    if status in (500, 502, 503) or "overloaded" in err_str or "server error" in err_str:
        return FailoverReason.OVERLOADED
    return FailoverReason.UNKNOWN


def _describe_http_status_error(error: httpx.HTTPStatusError) -> str:
    """Return a safe, structured summary for an HTTP status failure."""
    status = getattr(error.response, "status_code", "unknown")
    try:
        payload = error.response.json()
    except Exception:
        payload = {}

    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error", payload)
        if isinstance(err, dict):
            parts: list[str] = []
            if err.get("type"):
                parts.append(str(err["type"]))
            if err.get("code"):
                parts.append(f"code={err['code']}")
            if err.get("param"):
                parts.append(f"param={err['param']}")
            msg = str(err.get("message", "")).strip()
            if parts and msg:
                detail = f"{', '.join(parts)}: {msg}"
            elif parts:
                detail = ", ".join(parts)
            elif msg:
                detail = msg

    if not detail:
        try:
            detail = (error.response.text or "").strip()[:500]
        except Exception:
            detail = str(error)

    if detail:
        return f"HTTP {status} — {detail}"
    return f"HTTP {status}"


def _describe_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return _describe_http_status_error(error)
    return str(error)


def _chat_completions_model_guard(provider: str, model: str) -> str:
    """Return a guardrail error string for non-chat model classes.

    Empty string means "no guard hit".
    """
    if not provider or not model:
        return ""
    try:
        from providers.model_classes import classify
        model_class = classify(provider, model)
    except Exception:
        return ""

    incompatible = {"completion-only", "embedding", "audio", "image", "video", "realtime"}
    if model_class in incompatible:
        return (
            f"Model {model!r} for provider {provider!r} is classified as "
            f"{model_class!r} and is not valid for chat completions. "
            "Pick a chat or reasoning model in Settings -> Providers."
        )
    return ""


class ProviderCooldownTracker:
    """Tracks per-provider cooldown state for failover decisions."""

    _COOLDOWN_MAP: dict[FailoverReason, int] = {
        FailoverReason.RATE_LIMIT: 60,
        FailoverReason.AUTH: 300,
        FailoverReason.AUTH_PERMANENT: 86400,
        FailoverReason.BILLING: 3600,
        FailoverReason.OVERLOADED: 30,
        FailoverReason.TIMEOUT: 15,
    }
    _PROBE_INTERVAL = 30.0

    def __init__(self):
        self._cooldowns: dict[str, float] = {}
        self._last_probe: dict[str, float] = {}

    def record_failure(self, provider: str, reason: FailoverReason):
        cooldown_seconds = self._COOLDOWN_MAP.get(reason, 10)
        self._cooldowns[provider] = time.time() + cooldown_seconds

    def is_available(self, provider: str) -> bool:
        return time.time() >= self._cooldowns.get(provider, 0)

    def should_probe(self, provider: str) -> bool:
        if self.is_available(provider):
            return True
        last = self._last_probe.get(provider, 0)
        if time.time() - last >= self._PROBE_INTERVAL:
            self._last_probe[provider] = time.time()
            return True
        return False

    def record_success(self, provider: str):
        self._cooldowns.pop(provider, None)


__all__ = [
    "MAX_RETRIES",
    "RETRY_DELAYS",
    "_RETRIABLE_CODES",
    "_SSE_KEEPALIVE_PREFIXES",
    "_retry_llm_call",
    "FailoverReason",
    "classify_error",
    "_describe_http_status_error",
    "_describe_error",
    "_chat_completions_model_guard",
    "ProviderCooldownTracker",
]
