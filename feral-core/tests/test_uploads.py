"""PR 10: upload store + multipart route + wiki PDF mismatch fix.

The store half lives at memory/uploads.py; the HTTP half lives at
api/routes/uploads.py. Both are covered here. The wiki/ingest/pdf
mismatch is covered in test_wiki_pdf_multipart.py.

Pins:
* per-file quota enforcement (413 not silent truncate)
* SHA-256 dedup (same bytes twice -> one upload row)
* multipart upload round-trip via TestClient
* attachments wired into TextCommandPayload (PR 10 model change)
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from memory.uploads import (  # noqa: E402
    UploadQuotaExceeded,
    UploadStore,
)
from models.protocol import AttachmentRef, TextCommandPayload  # noqa: E402


# ── store ──────────────────────────────────────────────────────────────


def test_store_writes_bytes_and_returns_record(tmp_path):
    store = UploadStore(root=tmp_path / "uploads")
    rec = store.store(data=b"hello", filename="hi.txt", content_type="text/plain")
    assert rec.size_bytes == 5
    assert rec.sha256
    assert Path(rec.path).exists()
    assert Path(rec.path).read_bytes() == b"hello"


def test_store_dedups_by_sha(tmp_path):
    store = UploadStore(root=tmp_path / "uploads")
    a = store.store(data=b"same", filename="a.txt")
    b = store.store(data=b"same", filename="b.txt")
    assert a.upload_id == b.upload_id
    assert store.stats()["count"] == 1


def test_per_file_quota_rejects_oversize(tmp_path):
    store = UploadStore(root=tmp_path / "uploads", max_file_bytes=4)
    with pytest.raises(UploadQuotaExceeded):
        store.store(data=b"123456", filename="big.bin")


def test_total_quota_rejects_when_full(tmp_path):
    store = UploadStore(
        root=tmp_path / "uploads",
        max_file_bytes=10,
        max_total_bytes=15,
    )
    store.store(data=b"12345678", filename="a")  # 8 bytes
    store.store(data=b"abcd", filename="b")       # 4 bytes (total 12)
    with pytest.raises(UploadQuotaExceeded):
        store.store(data=b"xyzwv", filename="c")  # would push to 17 > 15


def test_index_persists_across_reopen(tmp_path):
    root = tmp_path / "uploads"
    s1 = UploadStore(root=root)
    rec = s1.store(data=b"persist", filename="p.txt")
    s2 = UploadStore(root=root)
    fetched = s2.get(rec.upload_id)
    assert fetched is not None
    assert fetched.filename == "p.txt"


def test_delete_removes_record_and_file(tmp_path):
    store = UploadStore(root=tmp_path / "uploads")
    rec = store.store(data=b"bye", filename="x.txt")
    assert store.delete(rec.upload_id)
    assert store.get(rec.upload_id) is None
    assert not Path(rec.path).exists()


# ── model ──────────────────────────────────────────────────────────────


def test_text_command_payload_accepts_attachments():
    payload = TextCommandPayload(
        text="see the file",
        attachments=[
            AttachmentRef(upload_id="abc", filename="report.pdf", size_bytes=10),
        ],
    )
    dumped = payload.model_dump()
    assert dumped["attachments"][0]["upload_id"] == "abc"
    assert dumped["attachments"][0]["filename"] == "report.pdf"


def test_text_command_payload_attachments_optional():
    """Backward-compat: existing clients that don't send attachments
    must still validate cleanly."""
    payload = TextCommandPayload(text="hi")
    assert payload.attachments is None


# ── route ──────────────────────────────────────────────────────────────


@pytest.fixture()
def upload_client(tmp_path):
    """A minimal FastAPI app wiring just the uploads router against a
    fresh tmp-path UploadStore."""
    from api.routes import uploads as uploads_module

    store = UploadStore(root=tmp_path / "uploads", max_file_bytes=512)

    class _State:
        uploads = store

    with patch.object(uploads_module, "state", _State()):
        app = FastAPI()
        app.include_router(uploads_module.router)
        yield TestClient(app, raise_server_exceptions=False), store


def test_post_uploads_round_trips_file(upload_client):
    client, store = upload_client
    resp = client.post(
        "/api/uploads",
        files={"file": ("hello.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "hello.txt"
    assert body["size_bytes"] == len(b"hello world")
    assert body["sha256"]

    # Get metadata
    meta = client.get(f"/api/uploads/{body['upload_id']}").json()
    assert meta["upload_id"] == body["upload_id"]

    # Raw download
    raw = client.get(f"/api/uploads/{body['upload_id']}/raw")
    assert raw.status_code == 200
    assert raw.content == b"hello world"


def test_post_uploads_oversize_returns_413(upload_client):
    client, _store = upload_client
    big = b"x" * 600
    resp = client.post(
        "/api/uploads",
        files={"file": ("big.bin", io.BytesIO(big), "application/octet-stream")},
    )
    assert resp.status_code == 413
    assert "exceeds per-upload limit" in resp.json()["detail"]


def test_post_uploads_empty_file_returns_400(upload_client):
    client, _store = upload_client
    resp = client.post(
        "/api/uploads",
        files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
    )
    assert resp.status_code == 400


def test_get_uploads_lists_recent(upload_client):
    client, _store = upload_client
    client.post(
        "/api/uploads",
        files={"file": ("a.txt", io.BytesIO(b"aa"), "text/plain")},
    )
    client.post(
        "/api/uploads",
        files={"file": ("b.txt", io.BytesIO(b"bb"), "text/plain")},
    )
    resp = client.get("/api/uploads")
    assert resp.status_code == 200
    names = [u["filename"] for u in resp.json()["uploads"]]
    assert "a.txt" in names and "b.txt" in names


def test_unknown_upload_id_returns_404(upload_client):
    client, _store = upload_client
    assert client.get("/api/uploads/missing").status_code == 404
    assert client.get("/api/uploads/missing/raw").status_code == 404
    assert client.delete("/api/uploads/missing").status_code == 404


def test_store_not_initialised_returns_503(tmp_path):
    """No store wired → route must say so honestly, not 500."""
    from api.routes import uploads as uploads_module

    class _State:
        uploads = None

    with patch.object(uploads_module, "state", _State()):
        app = FastAPI()
        app.include_router(uploads_module.router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/uploads",
            files={"file": ("a.txt", io.BytesIO(b"a"), "text/plain")},
        )
        assert resp.status_code == 503
        assert "not initialised" in resp.json()["detail"].lower()
