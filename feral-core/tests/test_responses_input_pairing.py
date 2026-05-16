"""Tests for v2026.5.29 chat-400 root-cause fix.

The fix has three layers; this suite covers each one:

* **Layer A** — ``_messages_to_responses_input`` drops orphan
  ``role:"tool"`` rows whose announcing assistant turn is missing.
* **Layer B** — ``ContextManager.compact`` walks backwards from the
  tail to keep tool round-trips atomic.
* **Layer C** — ``_sanitize_orphan_tool_rows`` strips orphan tool
  rows on primary-thread rehydrate so stale on-disk snapshots can
  never leak ``function_call_output`` items with no
  ``function_call``.

Regression target: ``Stream error: HTTP 400 — No tool call found for
function call output with call_id …``.
"""

from __future__ import annotations

import pytest

from agents.context_manager import ContextManager
from agents.llm_provider import LLMProvider
from api.state import _sanitize_orphan_tool_rows
from memory.session_snapshot import _truncate


def _assistant_with_tool(call_id: str, name: str = "noop") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


def _tool_result(call_id: str, output: str = "{}") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": output}


# ---------------------------------------------------------------------------
# Layer A — translator pairing guard
# ---------------------------------------------------------------------------


class TestTranslatorPairingGuard:
    def test_orphan_tool_only_is_dropped(self):
        msgs = [
            {"role": "user", "content": "hi"},
            _tool_result("call_orphan", '{"ok": true}'),
        ]
        instructions, items = LLMProvider._messages_to_responses_input(msgs)
        assert instructions == ""
        types = [it.get("type") or it.get("role") for it in items]
        assert "function_call_output" not in types
        assert "user" in types

    def test_matched_pair_survives(self):
        msgs = [
            {"role": "user", "content": "run it"},
            _assistant_with_tool("call_good"),
            _tool_result("call_good", '{"ok": true}'),
            {"role": "assistant", "content": "done"},
        ]
        _, items = LLMProvider._messages_to_responses_input(msgs)
        types = [it.get("type") or it.get("role") for it in items]
        assert types.count("function_call") == 1
        assert types.count("function_call_output") == 1
        assert items[1]["call_id"] == "call_good"
        # function_call must come before its output
        fc_idx = types.index("function_call")
        fco_idx = types.index("function_call_output")
        assert fc_idx < fco_idx

    def test_mixed_valid_and_orphan(self):
        msgs = [
            {"role": "user", "content": "go"},
            _assistant_with_tool("call_good"),
            _tool_result("call_good", "{}"),
            _tool_result("call_stale", "{}"),  # orphan from prior session
            {"role": "user", "content": "hi"},
        ]
        _, items = LLMProvider._messages_to_responses_input(msgs)
        call_outputs = [it for it in items if it.get("type") == "function_call_output"]
        assert len(call_outputs) == 1
        assert call_outputs[0]["call_id"] == "call_good"

    def test_tool_row_with_empty_call_id_dropped(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "", "content": "{}"},
        ]
        _, items = LLMProvider._messages_to_responses_input(msgs)
        assert not any(it.get("type") == "function_call_output" for it in items)


# ---------------------------------------------------------------------------
# Layer B — tool-aware compaction
# ---------------------------------------------------------------------------


class TestToolAwareCompaction:
    def test_short_history_passthrough(self):
        cm = ContextManager(max_messages=15)
        hist = [{"role": "user", "content": "hi"}]
        assert cm.compact(hist) is hist

    def test_cut_inside_tool_roundtrip_expands_window(self):
        # 17 rows, last 15 would start on a tool row.
        # row 0: user, 1: assistant+tool_calls, 2..14: tool, 15: user, 16: user
        cm = ContextManager(max_messages=15)
        history: list[dict] = [{"role": "user", "content": "start"}]
        history.append(_assistant_with_tool("call_a"))
        for _ in range(13):
            history.append(_tool_result("call_a"))
        history.append({"role": "user", "content": "later"})
        history.append({"role": "user", "content": "hi"})
        assert len(history) == 17
        out = cm.compact(history)
        # The slice should include the announcing assistant turn so the
        # tool rows are no longer orphans.
        roles = [r["role"] for r in out]
        assert "assistant" in roles
        assert roles.index("assistant") < roles.index("tool")

    def test_unrecoverable_orphans_are_stripped(self):
        # History where the announcing assistant turn doesn't exist at
        # all (e.g. older brain version snapshot). After expansion the
        # leading tool rows are dropped.
        cm = ContextManager(max_messages=3)
        history = [
            _tool_result("call_lost"),
            _tool_result("call_lost"),
            _tool_result("call_lost"),
            {"role": "user", "content": "hi"},
        ]
        out = cm.compact(history)
        assert all(r["role"] != "tool" for r in out)


# ---------------------------------------------------------------------------
# Layer C — snapshot rehydrate sanitizer
# ---------------------------------------------------------------------------


class TestRehydrateSanitizer:
    def test_orphan_rows_dropped(self):
        rows = [
            {"role": "user", "content": "hi"},
            _tool_result("call_ghost"),
            {"role": "assistant", "content": "ok"},
        ]
        cleaned = _sanitize_orphan_tool_rows(rows)
        assert all(r["role"] != "tool" for r in cleaned)
        assert len(cleaned) == 2

    def test_paired_rows_preserved(self):
        rows = [
            _assistant_with_tool("call_x"),
            _tool_result("call_x"),
            {"role": "user", "content": "hi"},
        ]
        cleaned = _sanitize_orphan_tool_rows(rows)
        assert len(cleaned) == 3
        assert cleaned[1]["role"] == "tool"

    def test_mixed_valid_and_orphan(self):
        rows = [
            _assistant_with_tool("call_a"),
            _tool_result("call_a"),
            _tool_result("call_dead"),
            {"role": "user", "content": "hi"},
        ]
        cleaned = _sanitize_orphan_tool_rows(rows)
        call_ids = [
            r.get("tool_call_id") for r in cleaned if r["role"] == "tool"
        ]
        assert call_ids == ["call_a"]


# ---------------------------------------------------------------------------
# Snapshot truncate (paired with Layer B for save-side cleanliness)
# ---------------------------------------------------------------------------


class TestSnapshotTruncate:
    def test_truncate_keeps_pair_atomic(self):
        rows: list[dict] = [{"role": "user", "content": f"u{i}"} for i in range(48)]
        rows.append(_assistant_with_tool("call_z"))
        rows.append(_tool_result("call_z"))
        rows.append({"role": "user", "content": "after"})
        out = _truncate(rows, 50)
        assert len(out) <= 50
        # call_z output is present, so its function_call must precede it.
        call_z_out = [r for r in out if r.get("tool_call_id") == "call_z"]
        if call_z_out:
            tc_ids = []
            for r in out:
                if r.get("role") == "assistant" and r.get("tool_calls"):
                    tc_ids.extend(tc["id"] for tc in r["tool_calls"])
            assert "call_z" in tc_ids

    def test_truncate_drops_leading_orphans(self):
        rows = [
            _tool_result("call_lost"),
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
        ]
        out = _truncate(rows, 5)
        assert all(r["role"] != "tool" for r in out)
