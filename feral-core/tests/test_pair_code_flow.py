"""Phase 3 / C3.1 — SDK code-pair flow.

Covers the new endpoints:

  POST /api/devices/pair/announce      — daemon advertises a code
  GET  /api/devices/pair/status        — daemon polls
  POST /api/devices/pair/code/claim    — operator types the code

Plus the rate limiter at
``feral-core/api/middleware/rate_limit.py:code_claim_limiter`` (5 wrong
attempts / 15min / IP), the per-code 10-attempt invalidation, and the
``PendingPairCode`` table on ``DevicePairingStore``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))

    from config.loader import ConfigLoader
    from security.device_pairing import DevicePairingStore
    from api.middleware.rate_limit import code_claim_limiter

    code_claim_limiter.reset()

    config = ConfigLoader(project_dir=str(tmp_path))
    config.discover()
    store = DevicePairingStore(db_path=str(tmp_path / "pairs.db"))

    mock_state = MagicMock()
    mock_state.config = config
    mock_state.device_pairing_store = store

    with (
        patch("api.state.state", mock_state),
        patch("api.routes.devices.state", mock_state),
    ):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False), store


# ── Announce + Status ──────────────────────────────────────────────


def test_announce_then_status_returns_pending(env):
    c, _ = env
    r = c.post("/api/devices/pair/announce", json={
        "code": "ABCDEFGH",
        "node_id": "feral-w300-test",
        "name": "Test Glasses",
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": True}

    r2 = c.get("/api/devices/pair/status?code=ABCDEFGH&node_id=feral-w300-test")
    assert r2.status_code == 200
    assert r2.json()["status"] == "pending"
    assert "token" not in r2.json()


def test_announce_missing_fields_returns_400(env):
    c, _ = env
    r = c.post("/api/devices/pair/announce", json={"code": "X"})
    assert r.status_code == 400
    r = c.post("/api/devices/pair/announce", json={"node_id": "X"})
    assert r.status_code == 400


def test_status_unknown_code_returns_404(env):
    c, _ = env
    r = c.get("/api/devices/pair/status?code=NEVER_BEEN&node_id=node")
    assert r.status_code == 404


# ── Claim ──────────────────────────────────────────────────────────


def test_claim_with_correct_code_mints_token_and_marks_paired(env):
    c, store = env
    c.post("/api/devices/pair/announce", json={
        "code": "TESTCODE",
        "node_id": "feral-test-node",
        "name": "Test Node",
    })

    r = c.post("/api/devices/pair/code/claim", json={"code": "TESTCODE"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"]
    assert body["device_id"]
    assert body["expires_at"] > 0
    # Token verifies via the regular DevicePairingStore path:
    assert store.verify_device(body["token"]) == body["device_id"]

    # Daemon polling sees ``paired`` next.
    r2 = c.get(
        "/api/devices/pair/status?code=TESTCODE&node_id=feral-test-node"
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "paired"
    assert r2.json()["token"] == body["token"]


def test_claim_idempotent_returns_same_token(env):
    c, _ = env
    c.post("/api/devices/pair/announce", json={
        "code": "IDEMPOTE",
        "node_id": "n",
        "name": "n",
    })
    r1 = c.post("/api/devices/pair/code/claim", json={"code": "IDEMPOTE"})
    r2 = c.post("/api/devices/pair/code/claim", json={"code": "IDEMPOTE"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["token"] == r2.json()["token"]


def test_claim_wrong_code_returns_404(env):
    c, _ = env
    r = c.post("/api/devices/pair/code/claim", json={"code": "NOPENOPE"})
    assert r.status_code == 404


def test_claim_missing_code_returns_400(env):
    c, _ = env
    r = c.post("/api/devices/pair/code/claim", json={})
    assert r.status_code == 400


# ── Rate limit ─────────────────────────────────────────────────────


def test_rate_limit_blocks_after_five_wrong_attempts(env):
    c, _ = env
    for _ in range(5):
        r = c.post("/api/devices/pair/code/claim", json={"code": "WRONG_XX"})
        assert r.status_code == 404
    r6 = c.post("/api/devices/pair/code/claim", json={"code": "WRONG_XX"})
    assert r6.status_code == 429
    assert "Retry-After" in r6.headers


def test_rate_limit_does_not_charge_successful_claims(env):
    c, _ = env
    # Five successful announces + claims must not exhaust the budget.
    for i in range(5):
        code = f"GOOD_{i:03d}"
        c.post("/api/devices/pair/announce", json={
            "code": code, "node_id": f"n{i}", "name": f"N{i}",
        })
        r = c.post("/api/devices/pair/code/claim", json={"code": code})
        assert r.status_code == 200
    # A wrong attempt afterwards must still succeed (not 429).
    r6 = c.post("/api/devices/pair/code/claim", json={"code": "STILL_OK"})
    assert r6.status_code == 404, r6.text


# ── Code TTL / expiry ──────────────────────────────────────────────


def test_status_returns_expired_when_past_ttl(env, monkeypatch):
    c, store = env
    c.post("/api/devices/pair/announce", json={
        "code": "WILLEXPI",
        "node_id": "n",
        "name": "n",
    })
    # Reach into the store to fast-forward expiry.
    import sqlite3
    conn = sqlite3.connect(store._db_path)
    conn.execute(
        "UPDATE pending_pair_codes SET expires_at = 1 WHERE code = 'WILLEXPI'"
    )
    conn.commit()
    conn.close()

    r = c.get("/api/devices/pair/status?code=WILLEXPI&node_id=n")
    assert r.status_code == 200
    assert r.json()["status"] == "expired"


# ── Code entropy sanity ────────────────────────────────────────────


def test_announce_round_trips_arbitrary_8char_code(env):
    """The announce route accepts whatever code the SDK generated.
    The brain does not generate codes — that's a daemon concern.
    Round-trip a few hand-picked base32 codes.
    """
    c, _ = env
    codes = ["ABCDEFGH", "Z2X4Q7M3", "00000001"]
    for i, code in enumerate(codes):
        r = c.post("/api/devices/pair/announce", json={
            "code": code, "node_id": f"node-{i}", "name": f"node-{i}",
        })
        assert r.status_code == 200
        r2 = c.get(f"/api/devices/pair/status?code={code}&node_id=node-{i}")
        assert r2.json()["status"] == "pending"
