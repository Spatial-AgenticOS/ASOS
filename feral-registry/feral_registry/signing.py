"""Ed25519 signature verification using PyNaCl."""

from __future__ import annotations

import base64
import hashlib

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_detached(pubkey_hex: str, signature_b64: str, message: bytes) -> bool:
    """Verify an Ed25519 detached signature over the raw message bytes."""
    try:
        vk = VerifyKey(bytes.fromhex(pubkey_hex))
        sig = base64.b64decode(signature_b64)
        vk.verify(message, sig)
        return True
    except (BadSignatureError, ValueError):
        return False


def verify_bundle_signature(pubkey_hex: str, signature_b64: str, sha256_hex: str) -> bool:
    """Verify the signature covers the sha256 digest of the bundle (as ascii hex bytes)."""
    return verify_detached(pubkey_hex, signature_b64, sha256_hex.encode("ascii"))
