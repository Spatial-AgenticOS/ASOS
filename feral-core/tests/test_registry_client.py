"""Unit tests for ``services/registry_client.py``.

Covers GENUI_PLATFORM_BUILD_SPEC §G1 + §G2: pure functions for fetch,
verify, and extract that both the brain ``POST /api/apps/install``
``registry_id`` branch and the CLI ``feral install`` flow call into.
"""

from __future__ import annotations

import base64
import os
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


pytestmark = pytest.mark.no_auto_feral_home


# ── Test fixtures ──────────────────────────────────────────────────────


def _ed25519_keypair():
    """Generate a fresh keypair for signing test bundles."""
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


def _make_tar(content: dict, dest: Path) -> Path:
    """Write a tiny tarball with the given filename → text content map."""
    tarball = dest / "bundle.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        for name, body in content.items():
            data = body.encode() if isinstance(body, str) else body
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            import io
            tar.addfile(info, io.BytesIO(data))
    return tarball


def _make_signed_item(tarball: Path, kind: str = "app") -> tuple[dict, str]:
    sk, pub_hex = _ed25519_keypair()
    with open(tarball, "rb") as f:
        digest = sha256(f.read()).digest()
    digest_hex = digest.hex()
    sig = sk.sign(digest_hex.encode("ascii")).signature
    item = {
        "kind": kind,
        "manifest": {"app_id": "test.app", "version": "1.0.0"},
        "download_url": "https://registry.test/items/test.app/bundle.tar.gz",
        "sha256": digest_hex,
        "signature_b64": base64.b64encode(sig).decode(),
        "publisher_pubkey": pub_hex,
    }
    return item, digest_hex


# ── verify_bundle ─────────────────────────────────────────────────────


def test_verify_bundle_succeeds_on_well_formed_payload(tmp_path):
    from services.registry_client import verify_bundle
    tarball = _make_tar({"manifest.yaml": "app_id: test\n"}, tmp_path)
    item, expected_hex = _make_signed_item(tarball)
    digest = verify_bundle(item, tarball)
    assert digest.hex() == expected_hex


def test_verify_bundle_rejects_sha256_mismatch(tmp_path):
    from services.registry_client import RegistryVerificationError, verify_bundle
    tarball = _make_tar({"manifest.yaml": "x"}, tmp_path)
    item, _ = _make_signed_item(tarball)
    item["sha256"] = "00" * 32
    with pytest.raises(RegistryVerificationError) as exc:
        verify_bundle(item, tarball)
    assert "sha256 mismatch" in str(exc.value).lower()


def test_verify_bundle_rejects_missing_signature(tmp_path):
    from services.registry_client import RegistryVerificationError, verify_bundle
    tarball = _make_tar({"x": "y"}, tmp_path)
    item, _ = _make_signed_item(tarball)
    item["signature_b64"] = ""
    with pytest.raises(RegistryVerificationError) as exc:
        verify_bundle(item, tarball)
    assert "missing signature" in str(exc.value)


def test_verify_bundle_rejects_bad_signature(tmp_path):
    from services.registry_client import RegistryVerificationError, verify_bundle
    tarball = _make_tar({"x": "y"}, tmp_path)
    item, _ = _make_signed_item(tarball)
    # Tamper: re-sign with a different key
    sk2, _ = _ed25519_keypair()
    sig = sk2.sign(item["sha256"].encode("ascii")).signature
    item["signature_b64"] = base64.b64encode(sig).decode()
    with pytest.raises(RegistryVerificationError):
        verify_bundle(item, tarball)


# ── safe_extract ──────────────────────────────────────────────────────


def test_safe_extract_extracts_well_formed_tarball(tmp_path):
    from services.registry_client import safe_extract
    tarball = _make_tar({"a.txt": "hello", "b.txt": "world"}, tmp_path)
    dest = tmp_path / "out"
    safe_extract(tarball, dest)
    assert (dest / "a.txt").read_text() == "hello"
    assert (dest / "b.txt").read_text() == "world"


def test_safe_extract_rejects_path_escape(tmp_path):
    from services.registry_client import RegistryExtractionError, safe_extract
    # Build a tarball with a path-escaping member
    tarball = tmp_path / "evil.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        info = tarfile.TarInfo(name="../escaped.txt")
        data = b"pwn"
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))
    dest = tmp_path / "out"
    with pytest.raises(RegistryExtractionError):
        safe_extract(tarball, dest)


# ── fetch_item ────────────────────────────────────────────────────────


def test_fetch_item_404_raises_RegistryNotFound():
    from services.registry_client import RegistryNotFound, fetch_item

    class FakeResp:
        status_code = 404
        text = ""

        def json(self):
            return {}

    with patch("services.registry_client.httpx") as fake_httpx:
        fake_httpx.HTTPError = Exception
        fake_httpx.get.return_value = FakeResp()
        with pytest.raises(RegistryNotFound):
            fetch_item("https://registry.test", "missing.app")


def test_fetch_item_5xx_raises_RegistryUnavailable():
    from services.registry_client import RegistryUnavailable, fetch_item

    class FakeResp:
        status_code = 503
        text = "service unavailable"

        def json(self):
            return {}

    with patch("services.registry_client.httpx") as fake_httpx:
        fake_httpx.HTTPError = Exception
        fake_httpx.get.return_value = FakeResp()
        with pytest.raises(RegistryUnavailable):
            fetch_item("https://registry.test", "any.app")


def test_fetch_item_returns_descriptor():
    from services.registry_client import fetch_item

    class FakeResp:
        status_code = 200
        text = ""
        _payload = {"kind": "app", "download_url": "https://x/y"}

        def json(self):
            return self._payload

    with patch("services.registry_client.httpx") as fake_httpx:
        fake_httpx.HTTPError = Exception
        fake_httpx.get.return_value = FakeResp()
        item = fetch_item("https://registry.test", "test.app")
    assert item["kind"] == "app"


# ── fetch_and_extract (composite happy path) ─────────────────────────


def test_fetch_and_extract_happy_path(tmp_path):
    from services.registry_client import fetch_and_extract

    tarball = _make_tar({"manifest.yaml": "app_id: test\n"}, tmp_path)
    item, _ = _make_signed_item(tarball)

    class FakeStreamResp:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self):
            with open(tarball, "rb") as f:
                yield f.read()

    class FakeGetResp:
        status_code = 200
        text = ""

        def json(self):
            return item

    with patch("services.registry_client.httpx") as fake_httpx:
        fake_httpx.HTTPError = Exception
        fake_httpx.get.return_value = FakeGetResp()
        fake_httpx.stream.return_value = FakeStreamResp()
        extract_to = tmp_path / "extracted"
        result = fetch_and_extract("https://registry.test", "test.app", extract_to)

    assert result == item
    assert (extract_to / "manifest.yaml").read_text() == "app_id: test\n"


# ── Dependency-missing paths ──────────────────────────────────────────


def test_fetch_item_raises_dependency_missing_when_httpx_absent():
    from services.registry_client import RegistryDependencyMissing, fetch_item
    with patch("services.registry_client.httpx", None):
        with pytest.raises(RegistryDependencyMissing):
            fetch_item("https://r", "x")


def test_verify_bundle_raises_dependency_missing_when_nacl_absent(tmp_path):
    from services.registry_client import RegistryDependencyMissing, verify_bundle
    with patch("services.registry_client._NACL_AVAILABLE", False):
        with pytest.raises(RegistryDependencyMissing):
            verify_bundle({}, tmp_path)
