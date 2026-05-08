"""Pair-dedup contract for ``DevicePairingStore.pair_device``.

Operator report (2026-05-08): "the webUI of the brain is showing again
every pair as a separate even though it's the same thing." Root cause
was that ``add_device`` minted a fresh ``device_id`` UUID4 on every
call without consulting any existing rows, so re-pairing the same
phone left the prior row in place. The dashboard rendered both rows
and authentication still accepted the stale phone bearer.

Fix: when ``node_id`` is non-empty, ``pair_device`` deletes any prior
``paired_devices`` rows for the same ``node_id`` (and any minted
``phone_bearers`` tied to those rows) before inserting the new row.
Rows with an empty ``node_id`` (legacy v1 browser pairs that pre-date
the field) are left untouched, since multiple browsers without a node
identity can legitimately co-exist.

These tests pin the contract end to end so a future caching tweak
or "upsert via INSERT OR IGNORE" refactor can't silently bring the
duplicate-row bug back.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from security.device_pairing import DevicePairingStore


@pytest.fixture
def store(tmp_path):
    """Fresh store backed by a tempfile sqlite DB."""
    db_path = tmp_path / "pair_dedup.db"
    return DevicePairingStore(db_path=str(db_path))


def _list_node_rows(store: DevicePairingStore, node_id: str) -> list[dict]:
    return [r for r in store.list_devices() if r["node_id"] == node_id]


def test_repair_for_same_node_id_replaces_prior_row(store):
    """The headline bug — same iPhone re-pairs, dashboard sees ONE row."""
    node_id = "feral-iphone-abc12345"
    first = store.pair_device(
        name="iPhone (first pair)",
        kind="hup",
        node_id=node_id,
        platform="ios",
    )
    rows_after_first = _list_node_rows(store, node_id)
    assert len(rows_after_first) == 1
    assert rows_after_first[0]["device_id"] == first["device_id"]

    second = store.pair_device(
        name="iPhone (re-pair)",
        kind="hup",
        node_id=node_id,
        platform="ios",
    )
    rows_after_second = _list_node_rows(store, node_id)
    assert len(rows_after_second) == 1, (
        "Re-pair for same node_id must collapse to ONE row — got "
        f"{len(rows_after_second)}: {rows_after_second}"
    )
    assert rows_after_second[0]["device_id"] == second["device_id"]
    assert rows_after_second[0]["device_id"] != first["device_id"]


def test_repair_revokes_prior_phone_bearer(store):
    """Stale phone_bearer must not authenticate after re-pair."""
    node_id = "feral-iphone-bearer1"
    first = store.pair_device(
        name="iPhone first",
        kind="browser_node_v2",
        node_id=node_id,
        mint_phone_bearer=True,
    )
    first_bearer = first.get("phone_bearer")
    assert first_bearer, "test setup: first pair did not mint a phone_bearer"
    assert store.verify_phone_bearer(first_bearer) is not None, (
        "test setup: freshly minted bearer should authenticate"
    )

    store.pair_device(
        name="iPhone re-pair",
        kind="browser_node_v2",
        node_id=node_id,
        mint_phone_bearer=True,
    )
    assert store.verify_phone_bearer(first_bearer) is None, (
        "Stale phone_bearer from a superseded pair must NOT authenticate. "
        "Otherwise re-pairing leaves a usable credential behind on the "
        "old device — security regression."
    )


def test_pair_with_empty_node_id_does_not_dedup(store):
    """Two browser pairs with no node_id are independent (legacy)."""
    first = store.pair_device(name="Browser one", kind="browser")
    second = store.pair_device(name="Browser two", kind="browser")
    rows = [r for r in store.list_devices() if r["node_id"] == ""]
    ids = {r["device_id"] for r in rows}
    assert {first["device_id"], second["device_id"]}.issubset(ids), (
        "Pairs with empty node_id must NOT be deduped against each "
        "other — multiple browsers can legitimately share an empty "
        f"node_id slot. Got rows: {rows}"
    )


def test_pair_for_different_node_ids_does_not_cross_supersede(store):
    """Pairing iPhone-B does not invalidate iPhone-A's row."""
    a = store.pair_device(name="iPhone A", kind="hup", node_id="feral-iphone-aaaaaaaa")
    b = store.pair_device(name="iPhone B", kind="hup", node_id="feral-iphone-bbbbbbbb")

    rows_a = _list_node_rows(store, "feral-iphone-aaaaaaaa")
    rows_b = _list_node_rows(store, "feral-iphone-bbbbbbbb")

    assert len(rows_a) == 1 and rows_a[0]["device_id"] == a["device_id"]
    assert len(rows_b) == 1 and rows_b[0]["device_id"] == b["device_id"]


def test_repair_logs_warning_with_superseded_count(store, caplog):
    """Operator must see a WARNING when re-pair invalidates prior rows."""
    import logging

    caplog.set_level(logging.WARNING, logger="feral.device_pairing")
    node_id = "feral-iphone-logwarn"
    store.pair_device(name="iPhone first", kind="hup", node_id=node_id)
    caplog.clear()
    store.pair_device(name="iPhone re-pair", kind="hup", node_id=node_id)

    matches = [
        rec for rec in caplog.records
        if "superseded" in rec.message.lower() and node_id in rec.message
    ]
    assert matches, (
        "Re-pair for an existing node_id must log a WARNING that names "
        "the node and the count of superseded rows so an operator can "
        "audit. Records: " + str([r.message for r in caplog.records])
    )
    assert matches[0].levelname == "WARNING"
