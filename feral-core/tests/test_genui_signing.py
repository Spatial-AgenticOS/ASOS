"""Round-trip + adversarial tests for genui.manifest_signing.

Covers the spec's four named cases:

* sign+verify with a freshly generated keypair (happy path)
* tampered manifest → signature_mismatch
* wrong-key signature → key_mismatch (when expected key is pinned)
                       OR signature_mismatch (when not pinned)
* empty / missing fields → ValidationError before sign even runs
"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from genui.manifest_signing import (
    SignedManifest,
    generate_keypair,
    sign,
    verify,
)


@pytest.fixture()
def manifest() -> dict:
    return {
        "name": "demo-app",
        "version": "0.0.1",
        "surface": {"kind": "app", "render": {"root": "main"}},
    }


def test_round_trip_with_fresh_keypair(manifest):
    sk, pk = generate_keypair()
    signed = sign(manifest, sk, key_id="test-key-do-not-commit")
    assert isinstance(signed, SignedManifest)
    assert signed.alg == "ed25519"
    assert signed.key_id == "test-key-do-not-commit"
    # Public key inside the envelope must equal the one we generated.
    assert base64.b64decode(signed.public_key.encode("ascii")) == pk

    ok, reason = verify(signed)
    assert ok, reason
    assert reason is None


def test_tampered_manifest_returns_signature_mismatch(manifest):
    sk, _pk = generate_keypair()
    signed = sign(manifest, sk, key_id="test-key-do-not-commit")
    # Mutate one field after signing so canonical_json no longer matches.
    signed.manifest["name"] = "tampered"

    ok, reason = verify(signed)
    assert not ok
    assert reason == "signature_mismatch"


def test_wrong_key_pinned_returns_key_mismatch(manifest):
    sk_publisher, _pk_publisher = generate_keypair()
    _sk_other, pk_other = generate_keypair()
    other_pk_b64 = base64.b64encode(pk_other).decode("ascii")

    signed = sign(manifest, sk_publisher, key_id="publisher-key")
    # Pin verification to a public key the publisher does NOT own.
    ok, reason = verify(signed, expected_public_key_b64=other_pk_b64)
    assert not ok
    assert reason == "key_mismatch"


def test_wrong_key_unpinned_returns_signature_mismatch(manifest):
    """Without an expected key, swapping the envelope's public key must
    surface as a signature_mismatch (the swapped key can't verify the
    original signature)."""
    sk_publisher, _pk_publisher = generate_keypair()
    _sk_other, pk_other = generate_keypair()

    signed = sign(manifest, sk_publisher, key_id="publisher-key")
    # Swap in a foreign public key inside the envelope itself.
    signed = signed.model_copy(update={
        "public_key": base64.b64encode(pk_other).decode("ascii"),
    })

    ok, reason = verify(signed)
    assert not ok
    assert reason == "signature_mismatch"


def test_missing_fields_raises_validation_error_before_sign(manifest):
    sk, pk = generate_keypair()
    pk_b64 = base64.b64encode(pk).decode("ascii")

    # Empty signature, missing key_id — pydantic must reject the
    # envelope itself, not the verifier.
    with pytest.raises(ValidationError):
        SignedManifest(
            manifest=manifest,
            signature="",
            public_key=pk_b64,
            key_id="",
            signed_at="2026-04-25T00:00:00+00:00",
            alg="ed25519",
        )

    # Empty manifest dict must be refused by sign() itself.
    with pytest.raises(ValueError):
        sign({}, sk, key_id="test-key-do-not-commit")

    # Empty key_id is also invalid at the sign() entry point.
    with pytest.raises(ValueError):
        sign(manifest, sk, key_id="")


def test_envelope_round_trip_through_json(manifest):
    """Serialise the envelope as JSON, parse it back, and re-verify.

    Mirrors the on-disk shape the CLI's `feral app sign` writes.
    """
    sk, _pk = generate_keypair()
    signed = sign(manifest, sk, key_id="round-trip-key")
    blob = signed.model_dump_json()
    rehydrated = SignedManifest.model_validate_json(blob)

    ok, reason = verify(rehydrated)
    assert ok, reason
