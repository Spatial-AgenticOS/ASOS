"""Pure-function FERAL registry client.

This module is the single place where "fetch a publisher bundle from
``registry.feral.sh``, verify SHA-256 + Ed25519 signature, and extract
it onto disk" is implemented. ``cli/install.py`` (interactive
``feral install`` flow) and ``api/routes/apps.py`` (brain
``POST /api/apps/install`` with ``registry_id``) both call into this.

Why a separate module rather than reusing ``cli/install.py``: the CLI
helpers print to stdout and call ``sys.exit`` on every failure path,
which is correct for a one-shot CLI but wrong for an HTTP route — a
500 from the brain would tear the request down without a structured
error. Here we raise typed exceptions; callers translate them to
``HTTPException`` (brain) or stdout + ``sys.exit`` (CLI).

References:
- GENUI_PLATFORM_BUILD_SPEC §G1, §G2.
- ``cli/install.py:_fetch_item, _download_bundle, _verify, _safe_extract``
  (the original CLI implementations these functions mirror).
- ``feral-registry/feral_registry/signing.py::verify_bundle_signature``
  on the registry side — both sides MUST sign over
  ``sha256_hex.encode("ascii")``.
"""

from __future__ import annotations

import base64
import os
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:  # pragma: no cover — guarded at call sites
    httpx = None  # type: ignore[assignment]

try:
    from nacl.signing import VerifyKey  # type: ignore[import-untyped]
    from nacl.encoding import HexEncoder  # type: ignore[import-untyped]
    from nacl.exceptions import BadSignatureError  # type: ignore[import-untyped]
    _NACL_AVAILABLE = True
except ImportError:  # pragma: no cover — guarded at call sites
    VerifyKey = None  # type: ignore[assignment]
    HexEncoder = None  # type: ignore[assignment]
    BadSignatureError = Exception  # type: ignore[assignment, misc]
    _NACL_AVAILABLE = False


HTTP_TIMEOUT = 30.0


# ── Exceptions ────────────────────────────────────────────────────────


class RegistryError(Exception):
    """Base exception for any registry-fetch / verify / extract failure."""


class RegistryUnavailable(RegistryError):
    """Network failure or 5xx from the registry HTTP API."""


class RegistryNotFound(RegistryError):
    """The registry returned 404 for the requested item id."""


class RegistryDependencyMissing(RegistryError):
    """A required Python package (``httpx`` or ``pynacl``) is not installed."""


class RegistryVerificationError(RegistryError):
    """SHA-256 mismatch, missing signature, or signature verification failure."""


class RegistryExtractionError(RegistryError):
    """The downloaded tarball escapes its destination directory."""


# ── Pure helpers ─────────────────────────────────────────────────────


def _require_httpx() -> None:
    if httpx is None:
        raise RegistryDependencyMissing(
            "httpx is required for registry installs (pip install httpx)"
        )


def _require_nacl() -> None:
    if not _NACL_AVAILABLE:
        raise RegistryDependencyMissing(
            "pynacl is required to verify registry bundle signatures "
            "(pip install pynacl)"
        )


def fetch_item(registry: str, item_id: str) -> dict:
    """``GET {registry}/api/v1/item/{item_id}`` — returns the item descriptor.

    Raises:
        RegistryDependencyMissing — ``httpx`` not installed.
        RegistryNotFound — registry replied 404.
        RegistryUnavailable — non-2xx that is not 404, or a transport error,
            or a non-JSON body.
    """
    _require_httpx()
    if not registry or not item_id:
        raise RegistryError("registry base URL and item_id are required")
    url = f"{registry.rstrip('/')}/api/v1/item/{item_id}"
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise RegistryUnavailable(f"could not reach registry at {url}: {exc}") from exc
    if resp.status_code == 404:
        raise RegistryNotFound(f"item {item_id!r} not found in registry {registry}")
    if resp.status_code >= 400:
        raise RegistryUnavailable(
            f"registry error ({resp.status_code}) fetching {item_id}: {resp.text[:500]}"
        )
    try:
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — non-JSON is a registry contract failure
        raise RegistryUnavailable(
            f"registry returned non-JSON response from {url}"
        ) from exc


def download_bundle(download_url: str, *, dest_dir: Optional[Path] = None) -> Path:
    """Stream the tarball from ``download_url`` to a temp file.

    Returns the path to the downloaded tarball. Caller is responsible
    for cleaning up the temp directory (use ``dest_dir.parent`` for the
    default).
    """
    _require_httpx()
    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix="feral-install-"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "bundle.tar.gz"
    try:
        with httpx.stream("GET", download_url, timeout=HTTP_TIMEOUT, follow_redirects=True) as resp:
            if resp.status_code >= 400:
                raise RegistryUnavailable(
                    f"download failed ({resp.status_code}) from {download_url}"
                )
            with open(out, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    except httpx.HTTPError as exc:
        raise RegistryUnavailable(f"download failed: {exc}") from exc
    return out


def _sha256_file(path: Path) -> bytes:
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.digest()


def verify_bundle(item: dict, tarball: Path) -> bytes:
    """Verify ``sha256`` + Ed25519 signature on a downloaded tarball.

    Raises ``RegistryVerificationError`` on any mismatch. Returns the
    raw 32-byte SHA-256 digest on success. The signature MUST be over
    ``sha256_hex.encode("ascii")`` to match the registry-side signer in
    ``feral-registry/feral_registry/signing.py``.
    """
    _require_nacl()
    expected_hex = str(item.get("sha256", "")).lower().strip()
    actual = _sha256_file(tarball)
    actual_hex = actual.hex()
    if not expected_hex or actual_hex != expected_hex:
        raise RegistryVerificationError(
            f"sha256 mismatch: got {actual_hex}, expected {expected_hex or '<missing>'}"
        )

    sig_b64 = item.get("signature_b64") or item.get("signature") or ""
    pub_hex = item.get("publisher_pubkey") or item.get("publisher_pubkey_hex") or ""
    if not sig_b64 or not pub_hex:
        raise RegistryVerificationError(
            "missing signature or publisher key in registry response"
        )

    try:
        vk = VerifyKey(pub_hex, encoder=HexEncoder)
        vk.verify(actual_hex.encode("ascii"), base64.b64decode(sig_b64))
    except (BadSignatureError, ValueError, TypeError) as exc:
        raise RegistryVerificationError(
            f"signature verification failed: {exc}"
        ) from exc
    return actual


def safe_extract(tarball: Path, dest: Path) -> None:
    """Extract ``tarball`` into ``dest``, refusing any path escape.

    Defends against CVE-2007-4559 (tar member with absolute or
    parent-directory path). Raises ``RegistryExtractionError`` on any
    suspicious member.
    """
    dest.mkdir(parents=True, exist_ok=True)
    dest_abs = dest.resolve()
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest_abs) + os.sep) and target != dest_abs:
                raise RegistryExtractionError(
                    f"tar member escapes target dir: {member.name!r}"
                )
        tar.extractall(dest)


# ── Public composite ─────────────────────────────────────────────────


def fetch_and_extract(
    registry: str,
    item_id: str,
    extract_to: Path,
) -> dict:
    """Fetch + verify + extract in one call, returning the item descriptor.

    Used by the brain's ``POST /api/apps/install`` registry_id branch
    and by ``cli/install.py``'s app branch. Cleans up the tarball
    temp directory on success or failure.
    """
    item = fetch_item(registry, item_id)
    download_url = item.get("download_url")
    if not download_url:
        raise RegistryError("registry response missing 'download_url'")
    tmp_dir = Path(tempfile.mkdtemp(prefix="feral-install-bundle-"))
    try:
        tarball = download_bundle(download_url, dest_dir=tmp_dir)
        verify_bundle(item, tarball)
        safe_extract(tarball, extract_to)
    finally:
        try:
            for p in tmp_dir.iterdir():
                p.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass
    return item


__all__ = [
    "RegistryError",
    "RegistryUnavailable",
    "RegistryNotFound",
    "RegistryDependencyMissing",
    "RegistryVerificationError",
    "RegistryExtractionError",
    "HTTP_TIMEOUT",
    "fetch_item",
    "download_bundle",
    "verify_bundle",
    "safe_extract",
    "fetch_and_extract",
]
