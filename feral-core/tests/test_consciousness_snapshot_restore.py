"""ConsciousnessStore — 5th memory tier contract.

Covers the four capabilities the 'know where I left off' story depends on:

1. ``record()`` upserts a ConsciousnessEntity; ``list_active()`` returns it.
2. TTL-based auto-abandonment runs inline on every ``list_active`` call.
3. ``snapshot()`` + ``restore()`` round-trips across a fresh store instance
   (simulating a Brain restart).
4. Natural summary is deterministic + never calls the LLM.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture()
def store(tmp_path: Path):
    from memory.consciousness import ConsciousnessStore

    return ConsciousnessStore(tmp_path / "consciousness.sqlite")


def test_record_and_list_roundtrip(store):
    from memory.consciousness import ConsciousnessEntity

    e = ConsciousnessEntity(
        id="flow-1",
        kind="flow",
        owner_session_id="s1",
        status="active",
        summary="Weekly Summary",
        context_json={"step": 2, "steps": 7},
        ttl_seconds=3600,
    )
    store.record(e)

    active = store.list_active()
    assert len(active) == 1
    got = active[0]
    assert got.id == "flow-1"
    assert got.context_json["step"] == 2
    assert got.summary == "Weekly Summary"


def test_kind_and_session_filters(store):
    from memory.consciousness import ConsciousnessEntity

    store.record(ConsciousnessEntity(kind="flow", owner_session_id="s1", summary="a"))
    store.record(ConsciousnessEntity(kind="intent", owner_session_id="s1", summary="b"))
    store.record(ConsciousnessEntity(kind="flow", owner_session_id="s2", summary="c"))

    just_flows_s1 = store.list_active(kind="flow", owner_session_id="s1")
    assert len(just_flows_s1) == 1
    assert just_flows_s1[0].summary == "a"


def test_invalid_kind_rejected():
    from memory.consciousness import ConsciousnessEntity

    with pytest.raises(ValueError, match="invalid kind"):
        ConsciousnessEntity(kind="banana")


def test_ttl_sweep_auto_abandons_stale_entries(store):
    """A row whose last_heartbeat is older than ttl should flip to abandoned."""
    from memory.consciousness import ConsciousnessEntity

    stale = ConsciousnessEntity(
        id="stale-1",
        kind="thought",
        status="active",
        summary="thinking about lunch",
        ttl_seconds=0.01,  # 10 ms
    )
    store.record(stale)
    time.sleep(0.05)

    active = store.list_active()
    assert all(e.id != "stale-1" for e in active), "stale entity should have been swept"

    # Including abandoned now surfaces it.
    all_rows = store.list_active(include_abandoned=True)
    abandoned_ids = [e.id for e in all_rows if e.status == "abandoned"]
    assert "stale-1" in abandoned_ids


def test_heartbeat_prevents_auto_abandon(store):
    """Heartbeating a short-ttl entity keeps it alive."""
    from memory.consciousness import ConsciousnessEntity

    e = ConsciousnessEntity(id="alive-1", kind="flow", summary="long job", ttl_seconds=0.3)
    store.record(e)
    # Heartbeat every 100 ms for 500 ms — longer than ttl, but each
    # heartbeat resets the clock.
    for _ in range(5):
        time.sleep(0.1)
        assert store.heartbeat("alive-1") is True

    active = store.list_active()
    assert any(it.id == "alive-1" for it in active)


def test_pause_and_resume(store):
    from memory.consciousness import ConsciousnessEntity

    e = ConsciousnessEntity(id="p1", kind="flow", summary="...")
    store.record(e)
    assert store.pause("p1")
    got = store.get("p1")
    assert got.status == "paused"
    # paused is still "active-ish" — list_active includes it.
    assert any(it.id == "p1" for it in store.list_active())
    assert store.resume("p1")
    assert store.get("p1").status == "active"


def test_snapshot_restore_roundtrip_across_stores(tmp_path: Path):
    """Simulate the Brain-restart case: write to store A, snapshot,
    open a fresh store B at a different db path, restore, confirm
    entities come through."""
    from memory.consciousness import ConsciousnessStore, ConsciousnessEntity

    a = ConsciousnessStore(tmp_path / "a.sqlite")
    a.record(ConsciousnessEntity(id="flow-X", kind="flow", summary="X", ttl_seconds=3600))
    a.record(ConsciousnessEntity(id="intent-Y", kind="intent", summary="Y", ttl_seconds=3600))

    blob = a.snapshot()
    assert blob["schema"] == 1
    assert blob["count"] == 2

    b = ConsciousnessStore(tmp_path / "b.sqlite")
    restored = b.restore(blob)
    assert restored == 2

    ids = {e.id for e in b.list_active()}
    assert ids == {"flow-X", "intent-Y"}


def test_snapshot_restore_is_idempotent(store):
    from memory.consciousness import ConsciousnessEntity

    store.record(ConsciousnessEntity(id="z", kind="thought", summary="..."))
    blob = store.snapshot()
    n1 = store.restore(blob)
    n2 = store.restore(blob)
    assert n1 >= 1
    assert n2 >= 1  # rows aren't duplicated because upsert uses ON CONFLICT DO NOTHING

    # Still only one entity in the store.
    assert len(store.list_active()) == 1


def test_restore_rejects_wrong_schema(store):
    assert store.restore({"schema": 999, "entities": [{"id": "x", "kind": "flow"}]}) == 0


def test_natural_summary_deterministic(store):
    from memory.consciousness import ConsciousnessEntity

    store.record(ConsciousnessEntity(id="f", kind="flow", summary="Weekly Summary"))
    store.record(ConsciousnessEntity(id="i", kind="intent", summary="Ship 2026.4.22"))
    summary = store.natural_summary()
    assert "Weekly Summary" in summary
    assert "Ship 2026.4.22" in summary


def test_natural_summary_empty_store_says_clean_slate(store):
    assert store.natural_summary() == "Clean slate — no work in flight."


def test_convenience_record_helpers(store):
    e = store.record_intent(intent_id="int-1", summary="plan the week", session_id="s1", plan={"nodes": []})
    assert e.kind == "intent"
    assert e.ttl_seconds == 24 * 3600

    f = store.record_flow(flow_id="flow-1", title="Morning Brief", step=0, steps=4, session_id="s1")
    assert f.kind == "flow"
    assert f.context_json["steps"] == 4

    t = store.record_thought(thought_id="th-1", session_id="s1", text="mid-sentence thought about lunch plans")
    assert t.kind == "thought"
    assert t.status == "paused"
    assert "lunch" in t.summary


def test_snapshot_written_and_reloadable_via_path(tmp_path: Path):
    """End-to-end: write snapshot to disk, open a fresh store, read
    file, restore. This is the exact path the Brain boot/shutdown
    hooks use in api/server.py + api/state.py.
    """
    from memory.consciousness import ConsciousnessStore, ConsciousnessEntity

    a = ConsciousnessStore(tmp_path / "a.sqlite")
    a.record(ConsciousnessEntity(id="persisted-1", kind="flow", summary="durable", ttl_seconds=3600))
    blob = a.snapshot()
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(blob))

    b = ConsciousnessStore(tmp_path / "b.sqlite")
    restored = b.restore(json.loads(snap_path.read_text()))
    assert restored == 1
    assert any(e.id == "persisted-1" for e in b.list_active())
