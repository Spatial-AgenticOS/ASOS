from __future__ import annotations

import re
import time

import pytest

from security.device_pairing import (
    DEFAULT_PHONE_BEARER_TTL_SECONDS,
    DEFAULT_TTL_SECONDS,
    PHONE_BEARER_KIND,
    DevicePairingStore,
)


pytestmark = pytest.mark.no_auto_feral_home


def _store(tmp_path):
    return DevicePairingStore(db_path=str(tmp_path / "pair.db"))


def _phone_bearer_row(store: DevicePairingStore, device_id: str):
    conn = store._conn()
    try:
        row = conn.execute(
            """SELECT token_hash, ttl_seconds, expires_at
               FROM device_credentials
               WHERE device_id = ? AND bearer_kind = ?""",
            (device_id, PHONE_BEARER_KIND),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def test_pair_device_browser_node_v2_returns_phone_bearer(tmp_path):
    store = _store(tmp_path)
    issued = store.pair_device("phone", kind="browser_node_v2")

    assert re.fullmatch(r"[0-9a-f]{64}", issued["token"])
    assert re.fullmatch(r"[0-9a-f]{64}", issued["phone_bearer"])
    assert issued["phone_bearer"] != issued["token"]
    assert issued["device_id"]


def test_verify_phone_bearer_returns_device_and_extends_sliding_ttl(tmp_path):
    store = _store(tmp_path)
    issued = store.pair_device("phone", kind="browser_node_v2")

    conn = store._conn()
    try:
        conn.execute(
            "UPDATE device_credentials SET expires_at = ?, ttl_seconds = ? "
            "WHERE device_id = ? AND bearer_kind = ?",
            (
                int(time.time()) + 5,
                300,
                issued["device_id"],
                PHONE_BEARER_KIND,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    before = _phone_bearer_row(store, issued["device_id"])
    assert before is not None
    assert store.verify_phone_bearer(issued["phone_bearer"]) == issued["device_id"]
    after = _phone_bearer_row(store, issued["device_id"])
    assert after is not None
    assert after["expires_at"] > before["expires_at"]


def test_rotate_phone_bearer_invalidates_previous_bearer(tmp_path):
    store = _store(tmp_path)
    issued = store.pair_device("phone", kind="browser_node_v2")
    old_bearer = issued["phone_bearer"]

    rotated = store.rotate_phone_bearer(issued["device_id"])
    assert rotated is not None
    assert rotated["phone_bearer"] != old_bearer
    assert store.verify_phone_bearer(rotated["phone_bearer"]) == issued["device_id"]
    assert store.verify_phone_bearer(old_bearer) is None


def test_phone_bearer_hash_uses_argon2id_format(tmp_path):
    store = _store(tmp_path)
    issued = store.pair_device("phone", kind="browser_node_v2")
    row = _phone_bearer_row(store, issued["device_id"])
    assert row is not None
    assert row["token_hash"].startswith("$argon2id$")


def test_phone_bearer_default_ttl_is_30_days_while_pair_token_stays_24h(tmp_path):
    store = _store(tmp_path)
    issued = store.pair_device("phone", kind="browser_node_v2")
    row = _phone_bearer_row(store, issued["device_id"])
    assert row is not None

    assert issued["ttl_seconds"] == DEFAULT_TTL_SECONDS
    assert issued["phone_bearer_ttl_seconds"] == DEFAULT_PHONE_BEARER_TTL_SECONDS
    assert row["ttl_seconds"] == DEFAULT_PHONE_BEARER_TTL_SECONDS
