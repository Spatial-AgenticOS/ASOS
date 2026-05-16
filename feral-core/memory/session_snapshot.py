"""Phase 3 (audit-r10 overhaul) — primary chat-thread snapshot store.

Operator complaint #15:
> "The chat on the app can't fetch stuff I did on the local brain chat."

The v2026.5.19 `primary_session_id` work unified the wire-level
`session_id` between web and phone. But the in-RAM thread still lives
under `Orchestrator.conversation_history[session_id]` and is wiped by
`on_session_disconnect` whenever ANY WebSocket on that id closes —
including a web tab refresh. So the operator sees the right design
("one brain, one memory") right up until a surface disconnects.

This module is one half of the Phase 3 fix: snapshot the primary
thread to disk so cold-boot rehydrates the last ~50 turns. The other
half is the `BrainState` session-refcount that skips cleanup while
any surface is still attached. Together they make the primary thread
durable across surface lifecycle AND brain restarts.

Wire format (JSON at `<feral_data_home>/primary_session_thread.json`):

    {
      "session_id": "primary-deadbeef",
      "saved_at": 1726342234.12,
      "conversation_history": [
        {"role": "user", "content": "...", "ts": ...},
        {"role": "assistant", "content": "...", "ts": ...},
        ...
      ],
      "working_memory": [
        {"role": "user", "text": "..."},
        {"role": "assistant", "text": "..."},
        ...
      ]
    }

Conservative caps: last 50 turns per surface to keep the file under
~256 KB on disk. Brain memory continues to hold the full deque in
RAM; the snapshot is the cold-boot baseline, not the truth source.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("feral.memory.session_snapshot")


# Default cap on history rows we persist. Tuned for "30 min of active
# back-and-forth" rather than full transcript export.
_DEFAULT_MAX_ENTRIES = 50


class SessionSnapshotStore:
    """JSON-file persistence for a single primary chat thread.

    Single-writer assumption: only the brain process writes. Reads are
    cheap (one file per brain install). If the file is missing or
    corrupt the loader returns `None` and the orchestrator boots from
    a clean primary thread — never raises.
    """

    def __init__(
        self,
        data_home: Path,
        *,
        filename: str = "primary_session_thread.json",
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._path = Path(data_home) / filename
        self._max_entries = max(1, int(max_entries))
        self._last_save_ts: float = 0.0
        self._min_save_interval_s: float = 2.5  # debounce hot loops

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Optional[dict]:
        """Return the persisted snapshot dict or None if absent/corrupt.

        Never raises — a brain that can't read its snapshot still
        boots; it just starts with an empty primary thread.
        """
        try:
            if not self._path.is_file():
                return None
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                logger.warning(
                    "primary_session_thread snapshot at %s is not a dict; ignoring",
                    self._path,
                )
                return None
            if "session_id" not in data:
                logger.warning(
                    "primary_session_thread snapshot missing session_id; ignoring",
                )
                return None
            return data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "primary_session_thread snapshot read failed at %s: %s",
                self._path,
                exc,
            )
            return None

    def save(
        self,
        session_id: str,
        *,
        conversation_history: Optional[list[dict]] = None,
        working_memory: Optional[list[dict]] = None,
        force: bool = False,
    ) -> bool:
        """Atomically write the current primary thread snapshot.

        Returns True on success, False if skipped (debounced) or
        failed. Caller passes only the lists they have access to;
        either list may be omitted and the snapshot keeps whatever
        was there last (so the orchestrator side and the memory side
        can save independently).

        Atomicity: writes to a sibling temp file then renames so a
        crash mid-write never leaves a half-JSON snapshot.
        """
        if not session_id:
            return False

        now = time.time()
        if not force and (now - self._last_save_ts) < self._min_save_interval_s:
            return False

        existing = self.load() or {}
        merged: dict[str, Any] = {
            "session_id": session_id,
            "saved_at": now,
            "conversation_history": (
                _truncate(conversation_history, self._max_entries)
                if conversation_history is not None
                else existing.get("conversation_history", [])
            ),
            "working_memory": (
                _truncate(working_memory, self._max_entries)
                if working_memory is not None
                else existing.get("working_memory", [])
            ),
        }

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._path.parent),
                delete=False,
                suffix=".tmp",
            ) as tmp:
                json.dump(merged, tmp, ensure_ascii=False)
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, self._path)
            self._last_save_ts = now
            return True
        except OSError as exc:
            logger.warning(
                "primary_session_thread snapshot write failed at %s: %s",
                self._path,
                exc,
            )
            return False

    def clear(self) -> None:
        """Remove the snapshot file (operator-initiated 'forget'
        action). Never raises."""
        try:
            self._path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning(
                "primary_session_thread snapshot clear failed at %s: %s",
                self._path,
                exc,
            )


def _truncate(items: Optional[list[dict]], cap: int) -> list[dict]:
    """v2026.5.29 — tool-aware tail that never persists orphan
    ``function_call_output`` rows.

    Two passes:

    1. Tail to the most recent ``cap`` rows, expanding backwards
       through any ``role:"tool"`` rows so the cut never lands inside
       an assistant ``tool_calls`` round-trip.
    2. Drop any leading orphan ``tool`` rows whose announcing assistant
       turn is absent from the tail (covers stale snapshots written
       by older brain builds).
    """
    if not items:
        return []
    cleaned = [dict(x) for x in items if isinstance(x, dict)]
    if len(cleaned) > cap:
        start = len(cleaned) - cap
        while start > 0:
            row = cleaned[start]
            if row.get("role") != "tool":
                break
            prev = cleaned[start - 1]
            prev_role = prev.get("role")
            if prev_role == "tool":
                start -= 1
                continue
            if prev_role == "assistant" and prev.get("tool_calls"):
                start -= 1
                continue
            break
        cleaned = cleaned[start:]
    announced: set[str] = set()
    for row in cleaned:
        if row.get("role") == "assistant" and row.get("tool_calls"):
            for tc in row["tool_calls"]:
                if isinstance(tc, dict):
                    cid = tc.get("id")
                    if isinstance(cid, str) and cid:
                        announced.add(cid)
    drop_until = 0
    for i, row in enumerate(cleaned):
        if row.get("role") != "tool":
            break
        cid = row.get("tool_call_id") or row.get("call_id") or ""
        if cid and cid in announced:
            break
        drop_until = i + 1
    if drop_until:
        cleaned = cleaned[drop_until:]
    return cleaned


__all__ = ["SessionSnapshotStore"]
