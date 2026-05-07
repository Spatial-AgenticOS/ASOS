"""Unit tests for ``memory.node_subdevices.NodeSubdeviceStore``.

Pins the Phase-1 contract that the dashboard / iOS / MCP all rely on:

* ``upsert`` writes one row keyed by ``(node_id, capability)`` and
  refreshes ``last_seen`` to *now*; ``first_seen`` is preserved on
  subsequent upserts.
* ``on_change`` fires synchronously with the post-upsert record so the
  caller can broadcast a ``subdevice_update`` event without a delay.
* ``forget`` deletes one or all rows for a node and emits
  ``subdevice_remove`` events per row.
* Liveness derate is provenance-specific. The ``synthetic`` provenance
  (5 s window) lets us verify the live → stale transition without
  sleeping for 30 s.
* ``sweep_stale`` only emits the rows that crossed the live↔stale
  threshold since the previous sweep.
* The store survives reconstruction (SQLite persistence).
"""

from __future__ import annotations

import time

import pytest

from memory.node_subdevices import (
    LIVENESS_WINDOWS,
    NodeSubdeviceStore,
    liveness_window,
)


def _events_collector():
    captured: list[tuple[str, dict]] = []

    def _on_change(event_name: str, payload: dict) -> None:
        captured.append((event_name, dict(payload)))

    return captured, _on_change


def test_upsert_creates_row_and_emits_event(tmp_path):
    db = str(tmp_path / "memory.db")
    captured, on_change = _events_collector()
    store = NodeSubdeviceStore(db_path=db, on_change=on_change)

    record = store.upsert(
        node_id="feral-iphone-abc",
        capability="jw_health_glasses",
        status="ready",
        attrs={"device_name": "Theora-1234", "rssi": -52},
        provenance="ble",
    )

    assert record["node_id"] == "feral-iphone-abc"
    assert record["capability"] == "jw_health_glasses"
    assert record["status"] == "ready"
    assert record["live"] is True
    assert record["provenance"] == "ble"
    assert record["attrs"]["device_name"] == "Theora-1234"
    assert record["liveness_window_s"] == LIVENESS_WINDOWS["ble"]
    assert record["first_seen"] == record["last_seen"]

    # on_change must have fired with the same record.
    assert len(captured) == 1
    name, payload = captured[0]
    assert name == "subdevice_update"
    assert payload["status"] == "ready"
    assert payload["live"] is True


def test_upsert_preserves_first_seen_and_advances_last_seen(tmp_path):
    db = str(tmp_path / "memory.db")
    store = NodeSubdeviceStore(db_path=db)

    t0 = time.time() - 100.0  # ~100 s ago
    first = store.upsert(
        node_id="phone",
        capability="jw_health_glasses",
        status="ready",
        provenance="ble",
        observed_at=t0,
    )
    second = store.upsert(
        node_id="phone",
        capability="jw_health_glasses",
        status="ready",
        provenance="ble",
        observed_at=t0 + 50.0,
    )

    assert first["first_seen"] == pytest.approx(t0)
    assert second["first_seen"] == pytest.approx(t0)
    assert second["last_seen"] == pytest.approx(t0 + 50.0)
    assert second["last_seen"] > second["first_seen"]


def test_upsert_rejects_unknown_provenance(tmp_path):
    db = str(tmp_path / "memory.db")
    store = NodeSubdeviceStore(db_path=db)
    with pytest.raises(ValueError):
        store.upsert(
            node_id="phone",
            capability="jw_health_glasses",
            status="ready",
            provenance="quantum",
        )


def test_upsert_rejects_missing_required_fields(tmp_path):
    db = str(tmp_path / "memory.db")
    store = NodeSubdeviceStore(db_path=db)
    with pytest.raises(ValueError):
        store.upsert(node_id="", capability="x", status="ready")
    with pytest.raises(ValueError):
        store.upsert(node_id="x", capability="", status="ready")
    with pytest.raises(ValueError):
        store.upsert(node_id="x", capability="y", status="")


def test_get_returns_record_with_computed_live_flag(tmp_path):
    db = str(tmp_path / "memory.db")
    store = NodeSubdeviceStore(db_path=db)
    t0 = time.time()
    store.upsert(
        node_id="phone",
        capability="jw_health_glasses",
        status="ready",
        provenance="synthetic",
        observed_at=t0,
    )

    fresh = store.get("phone", "jw_health_glasses", now=t0 + 1.0)
    assert fresh is not None
    assert fresh["live"] is True

    stale = store.get(
        "phone",
        "jw_health_glasses",
        now=t0 + LIVENESS_WINDOWS["synthetic"] + 1.0,
    )
    assert stale is not None
    assert stale["live"] is False
    # Status is preserved across the derate; only the live flag flips.
    assert stale["status"] == "ready"


def test_list_for_node_orders_recent_first_and_skips_other_nodes(tmp_path):
    db = str(tmp_path / "memory.db")
    store = NodeSubdeviceStore(db_path=db)
    t0 = time.time()
    store.upsert(
        node_id="phoneA", capability="jw_health_glasses",
        status="ready", provenance="ble", observed_at=t0,
    )
    store.upsert(
        node_id="phoneA", capability="apple_healthkit",
        status="ready", provenance="host", observed_at=t0 + 10.0,
    )
    store.upsert(
        node_id="phoneB", capability="jw_health_glasses",
        status="ready", provenance="ble", observed_at=t0 + 20.0,
    )

    rows = store.list_for_node("phoneA")
    caps = [r["capability"] for r in rows]
    assert caps == ["apple_healthkit", "jw_health_glasses"]
    # Did not bleed in phoneB rows.
    assert all(r["node_id"] == "phoneA" for r in rows)


def test_forget_one_capability_removes_only_that_row(tmp_path):
    db = str(tmp_path / "memory.db")
    captured, on_change = _events_collector()
    store = NodeSubdeviceStore(db_path=db, on_change=on_change)
    store.upsert(node_id="phone", capability="jw_health_glasses",
                 status="ready", provenance="ble")
    store.upsert(node_id="phone", capability="apple_healthkit",
                 status="ready", provenance="host")
    captured.clear()

    removed = store.forget("phone", capability="jw_health_glasses")
    assert removed == 1
    remaining = store.list_for_node("phone")
    assert {r["capability"] for r in remaining} == {"apple_healthkit"}
    assert captured == [
        ("subdevice_remove", {"node_id": "phone", "capability": "jw_health_glasses"})
    ]


def test_forget_all_for_node_removes_every_row(tmp_path):
    db = str(tmp_path / "memory.db")
    captured, on_change = _events_collector()
    store = NodeSubdeviceStore(db_path=db, on_change=on_change)
    store.upsert(node_id="phone", capability="jw_health_glasses",
                 status="ready", provenance="ble")
    store.upsert(node_id="phone", capability="apple_healthkit",
                 status="ready", provenance="host")
    captured.clear()

    removed = store.forget("phone")
    assert removed == 2
    assert store.list_for_node("phone") == []
    # One subdevice_remove per row.
    assert sorted(p["capability"] for _, p in captured) == [
        "apple_healthkit", "jw_health_glasses"
    ]


def test_sweep_stale_emits_transition_only_once(tmp_path):
    db = str(tmp_path / "memory.db")
    captured, on_change = _events_collector()
    store = NodeSubdeviceStore(db_path=db, on_change=on_change)
    t0 = time.time()
    store.upsert(
        node_id="phone",
        capability="jw_health_glasses",
        status="ready",
        provenance="synthetic",
        observed_at=t0,
    )
    captured.clear()

    # Inside window — no transition.
    emitted = store.sweep_stale(now=t0 + 1.0)
    assert emitted == []
    assert captured == []

    # Past window — transition to stale, fires once.
    past = t0 + LIVENESS_WINDOWS["synthetic"] + 1.0
    emitted = store.sweep_stale(now=past)
    assert len(emitted) == 1
    assert emitted[0]["live"] is False
    assert emitted[0]["status"] == "ready"  # preserved across derate
    assert len(captured) == 1
    assert captured[0][0] == "subdevice_update"

    # Subsequent sweeps with no change emit nothing.
    captured.clear()
    emitted = store.sweep_stale(now=past + 1.0)
    assert emitted == []
    assert captured == []


def test_sweep_stale_recovers_to_live_after_fresh_observation(tmp_path):
    db = str(tmp_path / "memory.db")
    captured, on_change = _events_collector()
    store = NodeSubdeviceStore(db_path=db, on_change=on_change)
    t0 = time.time()
    store.upsert(
        node_id="phone", capability="jw_health_glasses",
        status="ready", provenance="synthetic", observed_at=t0,
    )

    # Force the stale transition.
    past = t0 + LIVENESS_WINDOWS["synthetic"] + 1.0
    store.sweep_stale(now=past)
    captured.clear()

    # New heartbeat — upsert flips back to live and emits.
    store.upsert(
        node_id="phone", capability="jw_health_glasses",
        status="ready", provenance="synthetic", observed_at=past + 1.0,
    )
    assert any(
        evt == "subdevice_update" and payload["live"] is True
        for evt, payload in captured
    )

    # Sweep right after — already-live, no extra event.
    captured.clear()
    store.sweep_stale(now=past + 2.0)
    assert captured == []


def test_persistence_across_store_reconstruction(tmp_path):
    db = str(tmp_path / "memory.db")
    store_a = NodeSubdeviceStore(db_path=db)
    store_a.upsert(
        node_id="phone", capability="jw_health_glasses",
        status="ready", attrs={"device_name": "Theora-1234"},
        provenance="ble",
    )

    # Brain restart simulation.
    store_b = NodeSubdeviceStore(db_path=db)
    rows = store_b.list_for_node("phone")
    assert len(rows) == 1
    assert rows[0]["status"] == "ready"
    assert rows[0]["attrs"]["device_name"] == "Theora-1234"


def test_liveness_window_defaults_apply_per_provenance():
    assert liveness_window("ble") == 30.0
    assert liveness_window("cloud") == 300.0
    assert liveness_window("host") == 60.0
    assert liveness_window("synthetic") == 5.0
    # Unknown provenance falls back to the default 30 s window.
    # (NodeSubdeviceStore.upsert refuses unknown values, so this only
    # matters for downstream reads if a row ever gets written through
    # raw SQL.)
    assert liveness_window("unobtainium") == 30.0
