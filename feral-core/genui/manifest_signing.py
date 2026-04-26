"""Ed25519 manifest signing for FERAL GenUI apps.

Signs the canonical JSON serialisation of an :class:`AppManifest`
dictionary. The envelope (``SignedManifest``) is what publishers ship
alongside the bundle and what installers verify before mounting the
app surface inside the sandboxed iframe (see roadmap §3.3 #1).

Library choice
--------------
We deliberately use **PyNaCl** here even though ``cryptography`` is
also a dependency. Rationale:

* ``cli/publish.py`` and the registry's signed-publish flow are
  already PyNaCl-based (``nacl.signing.SigningKey`` /
  ``nacl.signing.VerifyKey``). Reusing the same primitive means a
  publisher's existing ``~/.feral/publisher.key`` works with
  ``feral app sign`` without an extra "convert your key" step.
* The Ed25519 surface area we need (sign / verify / generate keypair,
  base64 transport) is one screen of code in PyNaCl and avoids the
  ASN.1 / DER round-trip ``cryptography`` requires for the same job.

If at some point ``cryptography`` becomes the only crypto dep, the
public surface here is small enough to re-implement on top of
``cryptography.hazmat.primitives.asymmetric.ed25519`` without
breaking call sites.

Wire format
-----------
:class:`SignedManifest` is the on-disk + on-wire envelope:

* ``manifest`` — the original AppManifest dict, untouched.
* ``signature`` — base64(sig over ``canonical_json(manifest)``).
* ``public_key`` — base64(32-byte Ed25519 public key) used to verify.
* ``key_id`` — opaque publisher-provided identifier (e.g. a slug or
  fingerprint). Lets the vault key off ``key_id`` rather than the
  full public key.
* ``signed_at`` — UTC datetime the signature was produced.
* ``alg`` — pinned to ``"ed25519"``; reserved for future agility.

``verify()`` returns ``(ok, reason)`` instead of raising so the
caller can decide between hard-fail (production install) and warn
(``--allow-unsigned`` flag during local development).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from nacl.signing import SigningKey, VerifyKey  # type: ignore
    from nacl.exceptions import BadSignatureError  # type: ignore
    _NACL_AVAILABLE = True
except ImportError:  # pragma: no cover — pynacl is in pyproject.toml
    SigningKey = None  # type: ignore
    VerifyKey = None  # type: ignore
    BadSignatureError = Exception  # type: ignore
    _NACL_AVAILABLE = False


__all__ = [
    "SignedManifest",
    "SignatureFormatError",
    "generate_keypair",
    "sign",
    "verify",
    "canonical_json",
]


# Single supported algorithm. Pinned so we can introduce alg agility
# (e.g. ed25519 + ML-DSA-44 hybrid) without silently downgrading.
ALG_ED25519 = "ed25519"


class SignatureFormatError(ValueError):
    """Raised when the SignedManifest envelope itself is malformed.

    Distinct from a *valid envelope* whose signature simply doesn't
    verify — that case is reported by :func:`verify` returning
    ``(False, reason)``.
    """


class SignedManifest(BaseModel):
    """Envelope wrapping an AppManifest dict + its Ed25519 signature."""

    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any] = Field(
        ...,
        description="The AppManifest payload as a plain dict.",
    )
    signature: str = Field(
        ...,
        min_length=1,
        description="base64-encoded Ed25519 signature over canonical_json(manifest).",
    )
    public_key: str = Field(
        ...,
        min_length=1,
        description="base64-encoded 32-byte Ed25519 public key.",
    )
    key_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Publisher-provided identifier for the signing key.",
    )
    signed_at: datetime = Field(
        ...,
        description="UTC timestamp the signature was produced.",
    )
    alg: Literal["ed25519"] = Field(
        default=ALG_ED25519,
        description="Signature algorithm; only ed25519 today.",
    )

    @field_validator("manifest")
    @classmethod
    def _manifest_not_empty(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict) or not v:
            raise ValueError("manifest must be a non-empty dict")
        return v

    @field_validator("signature", "public_key")
    @classmethod
    def _is_base64(cls, v: str) -> str:
        try:
            base64.b64decode(v.encode("ascii"), validate=True)
        except Exception as exc:
            raise ValueError(f"value is not valid base64: {exc}") from exc
        return v


# ----------------------------------------------------------------------
# Canonicalisation
# ----------------------------------------------------------------------


def canonical_json(manifest: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding used as the signed payload.

    Two installers must compute the *exact same* byte string for the
    same logical manifest, regardless of insertion order. ``sort_keys``
    + ``separators`` + ``ensure_ascii=False`` gives us that.
    """
    if not isinstance(manifest, dict):
        raise SignatureFormatError("manifest must be a dict")
    return json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


# ----------------------------------------------------------------------
# Key handling
# ----------------------------------------------------------------------


def _require_nacl() -> None:
    if not _NACL_AVAILABLE:
        raise RuntimeError(
            "pynacl is required for manifest signing — install with `pip install pynacl`."
        )


def generate_keypair() -> tuple[bytes, bytes]:
    """Return ``(private_key_bytes, public_key_bytes)`` — both 32 bytes.

    Both halves are raw little-endian byte strings; callers can store
    them however they like (vault, env, file-on-disk). ``sign()`` /
    ``verify()`` only ever see bytes.
    """
    _require_nacl()
    sk = SigningKey.generate()
    return bytes(sk), bytes(sk.verify_key)


def _coerce_signing_key(private_key: bytes) -> "SigningKey":
    if not isinstance(private_key, (bytes, bytearray)):
        raise SignatureFormatError("private_key must be 32 raw bytes")
    if len(private_key) != 32:
        raise SignatureFormatError(
            f"private_key must be 32 bytes (got {len(private_key)})"
        )
    return SigningKey(bytes(private_key))


def _coerce_verify_key(public_key_b64: str) -> "VerifyKey":
    try:
        raw = base64.b64decode(public_key_b64.encode("ascii"), validate=True)
    except Exception as exc:
        raise SignatureFormatError(f"public_key is not base64: {exc}") from exc
    if len(raw) != 32:
        raise SignatureFormatError(
            f"decoded public_key must be 32 bytes (got {len(raw)})"
        )
    return VerifyKey(raw)


# ----------------------------------------------------------------------
# Sign / verify
# ----------------------------------------------------------------------


def sign(
    manifest: dict[str, Any],
    private_key: bytes,
    *,
    key_id: str = "default",
    signed_at: Optional[datetime] = None,
) -> SignedManifest:
    """Produce a SignedManifest wrapping *manifest* with Ed25519.

    * ``manifest`` is left untouched on the way out — it's stored
      verbatim inside the envelope. ``verify`` recomputes
      ``canonical_json`` from it.
    * ``key_id`` lets installers / vaults identify the key without
      needing the public key bytes themselves.
    * ``signed_at`` defaults to ``datetime.now(timezone.utc)``.

    Raises :class:`SignatureFormatError` (subclass of ``ValueError``)
    when the inputs are obviously wrong, and lets PyNaCl raise its
    own exceptions if the key is unusable.
    """
    _require_nacl()
    if not isinstance(manifest, dict) or not manifest:
        raise SignatureFormatError("manifest must be a non-empty dict")
    if not key_id or not isinstance(key_id, str):
        raise SignatureFormatError("key_id must be a non-empty string")

    sk = _coerce_signing_key(private_key)
    payload = canonical_json(manifest)
    signed = sk.sign(payload)
    sig_b64 = base64.b64encode(signed.signature).decode("ascii")
    pk_b64 = base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    ts = signed_at or datetime.now(timezone.utc)

    return SignedManifest(
        manifest=manifest,
        signature=sig_b64,
        public_key=pk_b64,
        key_id=key_id,
        signed_at=ts,
        alg=ALG_ED25519,
    )


def verify(
    signed: SignedManifest,
    *,
    expected_public_key_b64: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Verify *signed* and return ``(ok, reason)``.

    * If the envelope itself is malformed (wrong size key, undecodable
      signature, etc.) we report ``(False, "format_error: ...")``.
    * If the signature doesn't match the manifest under the embedded
      public key, return ``(False, "signature_mismatch")``.
    * If ``expected_public_key_b64`` is supplied and doesn't equal the
      envelope's ``public_key`` field, return ``(False, "key_mismatch")``.
      This is how installers pin to a publisher's known key from the
      vault — even a perfectly valid signature from a *different* key
      is rejected.
    * Otherwise return ``(True, None)``.

    The "reason" strings are part of our wire contract; tests + the CLI
    rely on them. Don't change them silently.
    """
    _require_nacl()

    try:
        if signed.alg != ALG_ED25519:
            return False, f"unsupported_alg:{signed.alg}"

        if expected_public_key_b64 and expected_public_key_b64 != signed.public_key:
            return False, "key_mismatch"

        try:
            verify_key = _coerce_verify_key(signed.public_key)
        except SignatureFormatError as exc:
            return False, f"format_error:{exc}"

        try:
            sig_bytes = base64.b64decode(signed.signature.encode("ascii"), validate=True)
        except Exception as exc:
            return False, f"format_error:signature_not_base64:{exc}"

        try:
            payload = canonical_json(signed.manifest)
        except SignatureFormatError as exc:
            return False, f"format_error:{exc}"

        try:
            verify_key.verify(payload, sig_bytes)
        except BadSignatureError:
            return False, "signature_mismatch"
        except Exception as exc:  # length error, etc.
            return False, f"format_error:{exc}"
        return True, None
    except Exception as exc:  # pragma: no cover — defensive
        return False, f"verify_error:{exc}"
