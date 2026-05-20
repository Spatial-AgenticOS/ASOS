"""PR 9 gap-fill: voice realtime transcripts land in the durable
conversations store (not only ephemeral working memory).

Pins:
* OpenAI Realtime path persists user + assistant transcripts under
  ``voice:<session_id>`` via ``MemoryStore.conversation_append``.
* Gemini Realtime path persists user input + assistant output likewise.
* Persistence failures degrade gracefully (logger.debug) — they must
  NOT crash the transcript handler.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from memory.store import MemoryStore  # noqa: E402


def _fresh_memory(tmp_path):
    return MemoryStore(db_path=str(tmp_path / "mem.db"))


async def test_conversation_append_creates_and_appends(tmp_path):
    mem = _fresh_memory(tmp_path)
    await mem.conversation_append("voice:s1", "user", "hello", source="voice_realtime_openai", title="t")
    await mem.conversation_append("voice:s1", "assistant", "hi there", source="voice_realtime_openai")
    conv = await mem.conversation_get("voice:s1")
    assert conv is not None
    messages = conv.get("messages", [])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["source"] == "voice_realtime_openai"
    assert conv["message_count"] == 2


async def test_realtime_proxy_persists_final_user_and_assistant(tmp_path):
    from voice.realtime_proxy import RealtimeProxy

    mem = _fresh_memory(tmp_path)
    proxy = RealtimeProxy(memory=mem, send_to_session=None)

    await proxy._handle_transcript("sess-A", "[user] hello", True)
    await proxy._handle_transcript("sess-A", "hello back", True)

    conv = await mem.conversation_get("voice:sess-A")
    assert conv is not None
    msgs = conv.get("messages", [])
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "hello back"


async def test_realtime_proxy_skips_partial_transcripts(tmp_path):
    """Partial deltas must NOT spam the conversation store."""
    from voice.realtime_proxy import RealtimeProxy

    mem = _fresh_memory(tmp_path)
    proxy = RealtimeProxy(memory=mem, send_to_session=None)

    await proxy._handle_transcript("sess-B", "[user] partial", False)
    assert await mem.conversation_get("voice:sess-B") is None


async def test_realtime_proxy_persistence_failure_is_swallowed(tmp_path):
    """A broken store must not crash the transcript handler — the
    voice loop has to keep running even if persistence is unhappy."""
    from voice.realtime_proxy import RealtimeProxy

    async def _broken_append(*args, **kwargs):
        raise RuntimeError("disk full")

    broken = MagicMock()
    broken.working_push = MagicMock()
    broken.conversation_append = _broken_append
    proxy = RealtimeProxy(memory=broken, send_to_session=None)

    # Should not raise
    await proxy._handle_transcript("sess-C", "[user] hi", True)


async def test_gemini_proxy_persists_input_and_output_transcripts(tmp_path):
    from voice.gemini_realtime import GeminiRealtimeProxy

    mem = _fresh_memory(tmp_path)
    proxy = GeminiRealtimeProxy(memory=mem, send_to_session=None)

    await proxy._handle_input_transcript("g-sess", "What's the weather?")
    await proxy._handle_transcript("g-sess", "Sunny and 72.", False)

    conv = await mem.conversation_get("voice:g-sess")
    assert conv is not None
    msgs = conv.get("messages", [])
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert "voice_realtime_gemini" in {m["source"] for m in msgs}


_ = pytest
