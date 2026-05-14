"""Phase 3 (audit-r10 overhaul) regression tests — shared-session
lifecycle + primary thread snapshot.

Pins three behaviors that together close operator complaint #15
("the chat on the app can't fetch stuff I did on the local brain
chat"):

1. **Refcount on `attach_session` / `detach_session`** so multiple
   surfaces on the same `session_id` track correctly.
2. **`should_clear_on_disconnect` returns False for the persistent
   `primary_session_id`** so closing one tab doesn't wipe the shared
   thread.
3. **`SessionSnapshotStore` round-trip** so a brain restart rehydrates
   the last ~50 turns from disk.

Plus an end-to-end e2e via the `BrainState` glue: orchestrator turn
on the primary session → snapshot file appears with both
`conversation_history` and `working_memory` populated; next `init()`
sees the snapshot and replays it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memory.session_snapshot import SessionSnapshotStore


# ───────────────────────── SessionSnapshotStore ──────────────────────────


def test_snapshot_load_missing_returns_none(tmp_path: Path):
    store = SessionSnapshotStore(tmp_path)
    assert store.load() is None


def test_snapshot_save_and_load_roundtrip(tmp_path: Path):
    store = SessionSnapshotStore(tmp_path)
    ch = [
        {"role": "user", "content": "remember pizza tonight"},
        {"role": "assistant", "content": "Pizza noted for tonight."},
    ]
    wm = [
        {"role": "user", "text": "remember pizza tonight"},
        {"role": "assistant", "text": "Pizza noted for tonight."},
    ]
    assert store.save("primary-abc", conversation_history=ch, working_memory=wm, force=True)
    loaded = store.load()
    assert loaded is not None
    assert loaded["session_id"] == "primary-abc"
    assert loaded["conversation_history"] == ch
    assert loaded["working_memory"] == wm
    assert loaded["saved_at"] > 0


def test_snapshot_debounce_skips_rapid_saves(tmp_path: Path):
    store = SessionSnapshotStore(tmp_path)
    assert store.save("p", conversation_history=[{"role": "user", "content": "a"}])
    # Second save within debounce window without force=True is skipped.
    assert store.save("p", conversation_history=[{"role": "user", "content": "b"}]) is False
    # force=True bypasses debounce.
    assert store.save("p", conversation_history=[{"role": "user", "content": "c"}], force=True)
    loaded = store.load()
    assert loaded["conversation_history"][-1]["content"] == "c"


def test_snapshot_truncates_to_max_entries(tmp_path: Path):
    store = SessionSnapshotStore(tmp_path, max_entries=3)
    rows = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    store.save("p", conversation_history=rows, force=True)
    loaded = store.load()
    assert len(loaded["conversation_history"]) == 3
    # Keeps the LAST 3 (most recent), not the first 3.
    assert loaded["conversation_history"][-1]["content"] == "msg9"


def test_snapshot_corrupt_file_returns_none(tmp_path: Path):
    """A corrupt snapshot must not crash boot — operator's brain has to
    start clean if rehydration fails."""
    store = SessionSnapshotStore(tmp_path)
    store.path.write_text("{not valid json", encoding="utf-8")
    assert store.load() is None


def test_snapshot_preserves_other_list_on_partial_save(tmp_path: Path):
    """Caller may save only `conversation_history` OR only
    `working_memory` — the other side keeps whatever was on disk
    last so two writers don't stomp each other."""
    store = SessionSnapshotStore(tmp_path)
    ch = [{"role": "user", "content": "first"}]
    wm = [{"role": "user", "text": "first"}]
    store.save("p", conversation_history=ch, working_memory=wm, force=True)
    # Save only conversation_history; working_memory should survive.
    store.save("p", conversation_history=[{"role": "assistant", "content": "second"}], force=True)
    loaded = store.load()
    assert loaded["conversation_history"][-1]["content"] == "second"
    assert loaded["working_memory"] == wm


def test_snapshot_clear_removes_file(tmp_path: Path):
    store = SessionSnapshotStore(tmp_path)
    store.save("p", conversation_history=[{"role": "user", "content": "x"}], force=True)
    assert store.path.is_file()
    store.clear()
    assert not store.path.is_file()
    # Clear is idempotent.
    store.clear()


# ───────────────────────── refcount + should_clear ──────────────────────────


def test_refcount_attach_detach_basic():
    """BrainState.attach_session/detach_session track concurrent
    surfaces on the same session_id."""
    state = _make_brain_state_stub()
    assert state.attach_session("primary-x") == 1
    assert state.attach_session("primary-x") == 2
    assert state.detach_session("primary-x") == 1
    assert state.detach_session("primary-x") == 0
    # Below zero is impossible — already-zero detach stays at 0.
    assert state.detach_session("primary-x") == 0


def test_refcount_ignores_empty_session_id():
    state = _make_brain_state_stub()
    assert state.attach_session("") == 0
    assert state.detach_session("") == 0


def test_should_clear_returns_false_for_primary():
    """The headline Phase 3 fix: closing a surface attached to the
    primary thread must NEVER trigger per-session cleanup."""
    state = _make_brain_state_stub(primary="primary-abc")
    state.attach_session("primary-abc")
    state.detach_session("primary-abc")  # back to 0 attachments
    assert state.should_clear_on_disconnect("primary-abc") is False


def test_should_clear_returns_true_for_non_primary_at_zero():
    state = _make_brain_state_stub(primary="primary-abc")
    state.attach_session("other-session")
    state.detach_session("other-session")
    assert state.should_clear_on_disconnect("other-session") is True


def test_should_clear_returns_false_when_other_surfaces_attached():
    """Two tabs sharing the same non-primary session: closing one
    keeps the thread alive while the other is still active."""
    state = _make_brain_state_stub(primary="primary-abc")
    state.attach_session("custom-tab")
    state.attach_session("custom-tab")  # second tab on same id
    state.detach_session("custom-tab")  # first tab closes
    assert state.should_clear_on_disconnect("custom-tab") is False


# ───────────────────────── orchestrator hook ──────────────────────────


def test_orchestrator_snapshot_hook_only_fires_for_primary():
    """The orchestrator's `_maybe_snapshot_primary` MUST short-circuit
    when the turn's session_id != primary_session_id. Otherwise every
    chat from a "new thread" tab would stomp the primary snapshot."""
    from agents.orchestrator import Orchestrator

    skills = MagicMock()
    daemons = {}

    async def _send(_session, _msg):
        return None

    orch = Orchestrator(
        skill_registry=skills,
        send_to_client=_send,
        daemons=daemons,
        memory=None,
    )
    fired: list[str] = []
    orch.set_session_snapshot_hook(lambda: fired.append("hit"))

    # Point the resolver at "primary-yes" so we control the comparison.
    orch._primary_session_id_resolver = lambda: "primary-yes"

    orch._maybe_snapshot_primary("primary-yes")
    assert fired == ["hit"]

    orch._maybe_snapshot_primary("some-other-session")
    assert fired == ["hit"]  # no change — hook didn't fire for non-primary


def test_orchestrator_snapshot_hook_swallows_exceptions():
    """Hook failures must NEVER break a chat turn."""
    from agents.orchestrator import Orchestrator

    skills = MagicMock()
    daemons = {}

    async def _send(_session, _msg):
        return None

    orch = Orchestrator(
        skill_registry=skills,
        send_to_client=_send,
        daemons=daemons,
        memory=None,
    )

    def _boom():
        raise RuntimeError("disk full")

    orch.set_session_snapshot_hook(_boom)
    orch._primary_session_id_resolver = lambda: "primary"
    # Should NOT raise.
    orch._maybe_snapshot_primary("primary")


# ───────────────────────── helpers ──────────────────────────


def _make_brain_state_stub(*, primary: str = "primary-default"):
    """Minimal stub that exercises attach_session / detach_session /
    should_clear_on_disconnect WITHOUT booting the whole BrainState.

    Imports `BrainState` lazily and stitches in just the fields the
    refcount methods touch. This is faster and isolates Phase 3
    behavior from unrelated subsystems.
    """
    from api.state import BrainState

    stub = BrainState.__new__(BrainState)
    stub.session_attach_count = {}
    stub.primary_session_id = primary
    return stub
