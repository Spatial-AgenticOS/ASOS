"""End-to-end publish + acceptance gate flow.

This file used to assert that a freshly published item appeared
immediately in the public catalog. After the registry became an
acceptance-gated app store the contract is different: a successful
publish lands a row in ``status=submitted`` / ``visibility=private``,
the public catalog and item endpoints fail closed until a reviewer
approves it, and the blob route refuses 404 to non-reviewers in the
meantime.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from nacl.signing import SigningKey


REVIEWER_SECRET = "test-reviewer-secret"


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    """Spin up a fresh registry instance with a temp SQLite DB.

    We deliberately avoid ``importlib.reload`` here -- the SQLAlchemy
    declarative registry survives reloads in 2.x, which used to cause
    ``Table 'publishers' is already defined`` errors. Instead we point
    the existing modules at a fresh engine/session and reset cached
    settings.
    """

    blob_dir = tmp_path / "blobs"
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("FERAL_REGISTRY_BLOB_DIR", str(blob_dir))
    monkeypatch.setenv("FERAL_REGISTRY_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("FEATURED_PUBLISHERS", "feral")
    monkeypatch.setenv("FERAL_REGISTRY_PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("FERAL_REGISTRY_REVIEWER_SECRET", REVIEWER_SECRET)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from feral_registry import config as config_mod
    config_mod.get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = config_mod.get_settings()

    from feral_registry import db as db_mod
    from feral_registry import models as models_mod
    from feral_registry import main as main_mod

    new_engine = create_async_engine(settings.db_url, echo=False, future=True)
    new_session_factory = async_sessionmaker(
        new_engine, expire_on_commit=False, class_=db_mod.AsyncSession
    )
    monkeypatch.setattr(db_mod, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_mod, "SessionLocal", new_session_factory, raising=False)

    app = main_mod.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with new_engine.begin() as conn:
            await conn.run_sync(db_mod.Base.metadata.create_all)
        yield client, db_mod, models_mod
    await new_engine.dispose()


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


async def _make_publisher(db_mod, models_mod, github_login: str, pubkey_hex: str | None = None):
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


async def _publish_item(client, db_mod, models_mod, *, login: str = "feral") -> tuple[str, str]:
    """Publish a fresh skill bundle and return (item_id, sha256)."""

    sk = SigningKey.generate()
    pubkey_hex = sk.verify_key.encode().hex()
    await _make_publisher(db_mod, models_mod, login, pubkey_hex)

    manifest = {
        "kind": "skill",
        "name": f"hello_skill_{login}",
        "version": "0.1.0",
        "description": "Minimal test skill.",
        "skill_id": f"hello_skill_{login}",
    }
    bundle = _build_bundle(manifest)
    sha256 = hashlib.sha256(bundle).hexdigest()
    sig = base64.b64encode(sk.sign(sha256.encode("ascii")).signature).decode("ascii")
    token = _token_for(login)

    r = await client.post(
        "/api/v1/publish",
        headers={"Authorization": f"Bearer {token}"},
        files={"bundle": ("hello.tar.gz", bundle, "application/gzip")},
        data={"signature": sig, "manifest_json": json.dumps(manifest)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["id"], body["sha256"]


# ---------------------------------------------------------------------------
# Publish lands in submitted/private (does not become user-installable).
# ---------------------------------------------------------------------------


async def test_publish_lands_in_submitted_private(app_client):
    client, db_mod, models_mod = app_client
    item_id, sha256 = await _publish_item(client, db_mod, models_mod)

    # Publish response advertises pending review state.
    # (re-check via the publisher's own view since publish response is
    # already validated inside _publish_item.)
    token = _token_for("feral")
    r = await client.get(
        "/api/v1/publisher/submissions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    only = body["items"][0]
    assert only["id"] == item_id
    assert only["status"] == "submitted"
    assert only["visibility"] == "private"


async def test_public_catalog_hides_unapproved(app_client):
    client, db_mod, models_mod = app_client
    await _publish_item(client, db_mod, models_mod)

    r = await client.get("/api/v1/catalog", params={"kind": "skill"})
    assert r.status_code == 200
    catalog = r.json()
    assert catalog["total"] == 0
    assert catalog["items"] == []


async def test_public_item_detail_404_for_unapproved(app_client):
    client, db_mod, models_mod = app_client
    item_id, _ = await _publish_item(client, db_mod, models_mod)

    r = await client.get(f"/api/v1/item/{item_id}")
    assert r.status_code == 404
    assert r.json()["detail"] == "item not found"


async def test_public_blob_404_for_unapproved(app_client):
    client, db_mod, models_mod = app_client
    _, sha256 = await _publish_item(client, db_mod, models_mod)

    r = await client.get(f"/api/v1/blobs/{sha256}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Reviewer queue + approve/reject lifecycle.
# ---------------------------------------------------------------------------


async def test_reviewer_can_see_queue_and_approve(app_client):
    client, db_mod, models_mod = app_client
    item_id, sha256 = await _publish_item(client, db_mod, models_mod)

    rh = {"Authorization": f"Bearer {REVIEWER_SECRET}", "X-Reviewer-Actor": "alice"}

    r = await client.get("/api/v1/review/queue", headers=rh)
    assert r.status_code == 200, r.text
    queue = r.json()
    assert queue["total"] == 1
    only = queue["items"][0]
    assert only["id"] == item_id
    assert only["status"] == "submitted"
    assert only["visibility"] == "private"
    # publish_received audit row exists from the publish handler.
    events = only["events"]
    assert any(ev["event"] == "publish_received" for ev in events)

    r = await client.post(
        f"/api/v1/review/{item_id}/approve",
        json={"notes": "looks good"},
        headers=rh,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["visibility"] == "public"
    assert body["reviewed_by"] == "reviewer:alice"

    # After approval the public surfaces start working.
    r = await client.get("/api/v1/catalog", params={"kind": "skill"})
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = await client.get(f"/api/v1/item/{item_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    r = await client.get(f"/api/v1/blobs/{sha256}")
    assert r.status_code == 200


async def test_reviewer_reject_keeps_private(app_client):
    client, db_mod, models_mod = app_client
    item_id, sha256 = await _publish_item(client, db_mod, models_mod)

    rh = {"Authorization": f"Bearer {REVIEWER_SECRET}", "X-Reviewer-Actor": "bob"}
    r = await client.post(
        f"/api/v1/review/{item_id}/reject",
        json={"notes": "missing readme"},
        headers=rh,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["visibility"] == "private"

    r = await client.get(f"/api/v1/item/{item_id}")
    assert r.status_code == 404
    r = await client.get(f"/api/v1/blobs/{sha256}")
    assert r.status_code == 404


async def test_reviewer_quarantine_path(app_client):
    client, db_mod, models_mod = app_client
    item_id, _ = await _publish_item(client, db_mod, models_mod)

    rh = {"Authorization": f"Bearer {REVIEWER_SECRET}"}
    r = await client.post(f"/api/v1/review/{item_id}/quarantine", json={}, headers=rh)
    assert r.status_code == 200
    assert r.json()["status"] == "quarantined"
    assert r.json()["visibility"] == "private"


# ---------------------------------------------------------------------------
# Reviewer auth fail-closed.
# ---------------------------------------------------------------------------


async def test_review_queue_requires_auth(app_client):
    client, *_ = app_client
    r = await client.get("/api/v1/review/queue")
    assert r.status_code == 401


async def test_review_queue_rejects_wrong_secret(app_client):
    client, *_ = app_client
    r = await client.get(
        "/api/v1/review/queue",
        headers={"Authorization": "Bearer not-the-real-secret"},
    )
    assert r.status_code == 403


async def test_publisher_jwt_cannot_act_as_reviewer(app_client):
    client, db_mod, models_mod = app_client
    await _make_publisher(db_mod, models_mod, "feral", "ab" * 32)
    publisher_token = _token_for("feral")
    r = await client.get(
        "/api/v1/review/queue",
        headers={"Authorization": f"Bearer {publisher_token}"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Pre-existing test contracts that still hold.
# ---------------------------------------------------------------------------


async def test_publish_requires_pubkey(app_client):
    client, db_mod, models_mod = app_client
    await _make_publisher(db_mod, models_mod, "nokey")

    token = _token_for("nokey")
    manifest = {"kind": "skill", "name": "x", "version": "0.0.1", "skill_id": "x"}
    bundle = _build_bundle(manifest)
    _ = hashlib.sha256(bundle).hexdigest()

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
