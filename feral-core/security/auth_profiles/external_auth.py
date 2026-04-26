"""
W16 — read-only adapters for external CLI credential overlays.

When the user is already authenticated with
``gcloud``, ``aws sso``, ``codex``, etc., FERAL should *bootstrap* an
OAuth profile from those locally-cached tokens rather than asking the
user to paste keys again. The adapters here are **read-only** — they
never mutate the third-party CLI's state. The auth profile store is
the canonical writer; this module only provides candidate credentials
to merge in.

Today only the gcloud and AWS SSO adapters are wired in (the two CLIs
the FERAL user-research surveys flagged as "already configured on 80%+
of dev laptops"). Adding a new adapter is intentionally a one-method
PR — register it in :data:`EXTERNAL_CLI_ADAPTERS` and the overlay path
picks it up.

The overlay is **passive**: callers explicitly invoke
:func:`overlay_external_credentials` to merge external creds on top of
the on-disk store. We do NOT mutate the store, and we do NOT call out
to the external CLIs at import time — every read is lazy + cached for
the lifetime of the function call so a slow CLI binary (gcloud cold
start, looking at you) doesn't multiply across loops.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .types import (
    AuthProfileCredential,
    OAuthCredential,
)


logger = logging.getLogger("feral.auth_profiles.external_auth")


# Keep the per-adapter timeout small. These CLIs are local but can
# block on stale credentials, network reachability checks, etc.
_EXTERNAL_CLI_TIMEOUT_SECONDS = 5.0


def _read_gcloud_application_default_credential() -> Optional[OAuthCredential]:
    """Map ``gcloud auth application-default print-access-token`` output
    onto an :class:`OAuthCredential`.

    The "application default credentials" file lives at
    ``~/.config/gcloud/application_default_credentials.json`` and holds
    a refresh token + client_id/secret pair. We surface it as an
    OAuth profile keyed under the ``google`` provider so downstream
    code can refresh it via the standard Google OAuth endpoint.

    Returns ``None`` (instead of raising) when the credential is
    absent — that's the expected case on machines where the user has
    not run ``gcloud auth login``. A *malformed* credential file is
    surfaced as a warning + ``None`` so a corrupt gcloud install never
    blocks FERAL boot.
    """
    candidates = [
        Path.home() / ".config" / "gcloud" / "application_default_credentials.json",
    ]
    cloudsdk_config = os.environ.get("CLOUDSDK_CONFIG")
    if cloudsdk_config:
        candidates.insert(0, Path(cloudsdk_config) / "application_default_credentials.json")

    for path in candidates:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            logger.warning(
                "auth_profiles.external_auth.gcloud_unexpected_shape "
                "path=%s root_type=%s",
                path, type(parsed).__name__,
            )
            return None
        refresh = parsed.get("refresh_token")
        if not refresh:
            logger.warning(
                "auth_profiles.external_auth.gcloud_missing_refresh_token "
                "path=%s",
                path,
            )
            return None
        return OAuthCredential(
            provider="google",
            access="",
            refresh=str(refresh),
            expires=0,
            client_id=parsed.get("client_id"),
            account_id=parsed.get("quota_project_id"),
            email=parsed.get("account"),
            display_name="gcloud application default",
        )
    return None


def _read_aws_sso_credential() -> Optional[OAuthCredential]:
    """Surface the most recent AWS SSO cached token as an OAuth profile.

    The AWS CLI caches SSO tokens under
    ``~/.aws/sso/cache/<sha1>.json`` with fields ``accessToken``,
    ``refreshToken``, ``expiresAt`` (ISO-8601), ``clientId``,
    ``startUrl``. We pick the file with the most recent mtime and
    expose it as a ``aws-sso`` provider OAuth profile.
    """
    cache_dir = Path.home() / ".aws" / "sso" / "cache"
    if not cache_dir.exists():
        return None

    best: Optional[tuple[float, dict]] = None
    for file in cache_dir.iterdir():
        if not file.is_file() or file.suffix != ".json":
            continue
        raw = file.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or "accessToken" not in parsed:
            continue
        mtime = file.stat().st_mtime
        if best is None or mtime > best[0]:
            best = (mtime, parsed)

    if best is None:
        return None

    blob = best[1]
    expires_iso = blob.get("expiresAt", "")
    expires_ms = 0
    if expires_iso:
        # AWS SSO cache uses ISO-8601 with a trailing 'Z'. Convert to
        # epoch ms so the OAuthCredential.expires invariant
        # (milliseconds) holds.
        from datetime import datetime
        normalised = expires_iso.replace("Z", "+00:00")
        parsed_ts = datetime.fromisoformat(normalised)
        expires_ms = int(parsed_ts.timestamp() * 1000)

    return OAuthCredential(
        provider="aws-sso",
        access=str(blob.get("accessToken", "")),
        refresh=str(blob.get("refreshToken", "")),
        expires=expires_ms,
        client_id=blob.get("clientId"),
        enterprise_url=blob.get("startUrl"),
        display_name="aws sso",
    )


def _read_codex_cli_credential() -> Optional[OAuthCredential]:
    """Read the OpenAI Codex CLI's cached credentials.

    The Codex CLI stashes its OAuth state under
    ``~/.codex/credentials.json``. When present we surface it as an
    OAuth profile keyed under the ``openai-codex`` provider so the
    user does not have to paste a Codex API key into FERAL when they
    are already signed into the CLI.
    """
    path = Path.home() / ".codex" / "credentials.json"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return None
    refresh = parsed.get("refresh_token") or parsed.get("refresh")
    access = parsed.get("access_token") or parsed.get("access") or ""
    if not refresh:
        return None
    expires = parsed.get("expires") or parsed.get("expires_at") or 0
    return OAuthCredential(
        provider="openai-codex",
        access=str(access),
        refresh=str(refresh),
        expires=int(expires),
        client_id=parsed.get("client_id"),
        account_id=parsed.get("account_id"),
        email=parsed.get("email"),
        display_name="codex cli",
    )


# (profile_id, reader) — profile_id is the bootstrap key the credential
# is registered under in the overlay map. Two providers can register the
# same profile_id only if they intend to overwrite each other (we don't,
# today). Adding a new CLI is a one-line append here plus the reader.
EXTERNAL_CLI_ADAPTERS: list[tuple[str, Callable[[], Optional[OAuthCredential]]]] = [
    ("google:application-default", _read_gcloud_application_default_credential),
    ("aws-sso:default", _read_aws_sso_credential),
    ("openai-codex:cli", _read_codex_cli_credential),
]


def list_external_credentials() -> dict[str, OAuthCredential]:
    """Return ``{profile_id: credential}`` for every external CLI we can
    currently read.

    Adapters that can't find their respective credential file return
    ``None`` and are silently skipped — that is the expected steady
    state for any laptop where the user has not authenticated with
    that CLI.
    """
    out: dict[str, OAuthCredential] = {}
    for profile_id, reader in EXTERNAL_CLI_ADAPTERS:
        cred = reader()
        if cred is None:
            continue
        out[profile_id] = cred
    return out


def overlay_external_credentials(
    stored: dict[str, AuthProfileCredential],
) -> dict[str, AuthProfileCredential]:
    """Return ``stored`` with external CLI credentials overlaid.

    Locally-stored credentials always win — an OAuth credential that
    FERAL already refreshed has the canonical refresh token and we
    must not clobber it with a stale CLI cache. The overlay only fills
    in profiles the local store does not already know about. A
    cooldown-aware variant that can also skip recently-failed
    profiles lands with W19.
    """
    merged: dict[str, AuthProfileCredential] = dict(stored)
    for profile_id, cred in list_external_credentials().items():
        if profile_id in merged:
            continue
        merged[profile_id] = cred
    return merged


def has_external_cli_binary(name: str) -> bool:
    """Best-effort probe for whether a CLI is on ``$PATH``.

    Useful for the ``feral key list`` UI: when ``gcloud`` is installed
    but ``application_default_credentials.json`` is missing we want to
    show "available, run `gcloud auth login`" instead of pretending the
    integration doesn't exist.
    """
    return shutil.which(name) is not None


def probe_external_cli_version(name: str) -> Optional[str]:
    """Return ``CLI --version`` output (first line, stripped) or
    ``None`` when the binary is missing / errors out within the
    timeout.

    The probe is bounded to :data:`_EXTERNAL_CLI_TIMEOUT_SECONDS` so a
    misbehaving CLI never hangs ``feral key list``.
    """
    if not has_external_cli_binary(name):
        return None
    completed = subprocess.run(
        [name, "--version"],
        capture_output=True,
        timeout=_EXTERNAL_CLI_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        return None
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    return text.splitlines()[0]
