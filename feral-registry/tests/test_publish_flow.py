"""End-to-end publish+catalog flow using a locally generated Ed25519 keypair."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from nacl.signing import SigningKey
from sqlalchemy import select


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    blob_dir = tmp_path / "blobs"
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("FERAL_REGISTRY_BLOB_DIR", str(blob_dir))
    monkeypatch.setenv("FERAL_REGISTRY_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("FEATURED_PUBLISHERS", "feral")
    monkeypatch.setenv("FERAL_REGISTRY_PUBLIC_URL", "http://testserver")

    # Force config + db modules to pick up the overridden env.
    import importlib

    from feral_registry import config as config_mod
    config_mod.get_settings.cache_clear()  # type: ignore[attr-defined]

    from feral_registry import db as db_mod
    importlib.reload(db_mod)

    from feral_registry import models as models_mod
    importlib.reload(models_mod)

    from feral_registry import main as main_mod
    importlib.reload(main_mod)

    app = main_mod.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with db_mod.engine.begin() as conn:
            await conn.run_sync(db_mod.Base.metadata.create_all)
        yield client, db_mod, models_mod


def _build_bundle(manifest: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        impl_bytes = b"def run():\n    return 'hello'\n"
        info = tarfile.TarInfo("impl.py")
        info.size = len(impl_bytes)
        tar.addfile(info, io.BytesIO(impl_bytes))
    return buf.getvalue()


async def _make_publisher(db_mod, models_mod, github_login: str, pubkey_hex: str):
    async with db_mod.SessionLocal() as session:
        pub = models_mod.Publisher(
            github_login=github_login,
            github_id=123456,
            pubkey_hex=pubkey_hex,
        )
        session.add(pub)
        await session.commit()
        await session.refresh(pub)
        return pub.id


def _token_for(github_login: str) -> str:
    from feral_registry.auth import issue_publisher_token
    from feral_registry.config import get_settings

    token, _ = issue_publisher_token(github_login, get_settings())
    return token


async def test_publish_and_catalog(app_client):
    client, db_mod, models_mod = app_client

    sk = SigningKey.generate()
    pubkey_hex = sk.verify_key.encode().hex()

    await _make_publisher(db_mod, models_mod, "feral", pubkey_hex)

    manifest = {
        "kind": "skill",
        "name": "hello_skill",
        "version": "0.1.0",
        "description": "Minimal test skill.",
    }
    bundle = _build_bundle(manifest)
    sha256 = hashlib.sha256(bundle).hexdigest()
    sig = base64.b64encode(sk.sign(sha256.encode("ascii")).signature).decode("ascii")

    token = _token_for("feral")

    r = await client.post(
        "/api/v1/publish",
        headers={"Authorization": f"Bearer {token}"},
        files={"bundle": ("hello.tar.gz", bundle, "application/gzip")},
        data={"signature": sig, "manifest_json": json.dumps(manifest)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sha256"] == sha256
    assert body["verified"] is True
    item_id = body["id"]

    r = await client.get("/api/v1/catalog", params={"kind": "skill"})
    assert r.status_code == 200
    catalog = r.json()
    assert catalog["total"] >= 1
    names = [i["name"] for i in catalog["items"]]
    assert "hello_skill" in names

    r = await client.get(f"/api/v1/item/{item_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["publisher"] == "feral"
    assert detail["publisher_pubkey"] == pubkey_hex
    assert detail["signature_b64"] == sig
    assert detail["sha256"] == sha256

    r = await client.get(f"/api/v1/blobs/{sha256}")
    assert r.status_code == 200
    assert r.content == bundle


async def test_publish_requires_pubkey(app_client):
    client, db_mod, models_mod = app_client
    async with db_mod.SessionLocal() as session:
        pub = models_mod.Publisher(github_login="nokey", github_id=99)
        session.add(pub)
        await session.commit()

    token = _token_for("nokey")
    manifest = {"kind": "skill", "name": "x", "version": "0.0.1"}
    bundle = _build_bundle(manifest)
    sha256 = hashlib.sha256(bundle).hexdigest()

    r = await client.post(
        "/api/v1/publish",
        headers={"Authorization": f"Bearer {token}"},
        files={"bundle": ("x.tar.gz", bundle, "application/gzip")},
        data={"signature": "AAAA", "manifest_json": json.dumps(manifest)},
    )
    assert r.status_code == 412
    assert "register pubkey" in r.json()["detail"]


async def test_health(app_client):
    client, _, _ = app_client
    r = await client.get("/api/v1/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
