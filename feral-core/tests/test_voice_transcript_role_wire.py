"""Pin the wire-format role contract for voice transcripts.

Operator report (2026-05-08): "the UI chat on the iOS app shows the
user and assistant have the same chat bubbles." Two coupled bugs:

1. Brain leaked the internal ``[user] `` sentinel into wire payloads,
   so iOS rendered ``"[user] Hello"`` as visible bubble text.
2. iOS ignored the wire ``role`` field and hardcoded every transcript
   as ``user``, so even the assistant's spoken response styled as a
   user bubble.

Brain side now strips the sentinel before any emit AND populates an
explicit ``role`` field so iOS / web can disambiguate without parsing
text. iOS fix lives in ``feral-companion-ios`` BrainClient.swift —
this test pins the brain-side half (the wire contract iOS depends on).

Pinned by:
  * ``RealtimeProxy._handle_transcript`` strips ``[user] `` and emits
    ``role`` correctly to both ``_send_to_session`` and
    ``_send_to_node`` paths.
  * ``TranscriptPayload.role`` survives a Pydantic round-trip.
"""

from __future__ import annotations

import asyncio

import pytest

from models.protocol import TranscriptPayload
from voice.realtime_proxy import RealtimeProxy, RealtimeSession


def test_transcript_payload_round_trips_role():
    payload = TranscriptPayload(text="Hello there", role="assistant")
    dumped = payload.model_dump()
    assert dumped["text"] == "Hello there"
    assert dumped["role"] == "assistant"

    reloaded = TranscriptPayload(**dumped)
    assert reloaded.role == "assistant"


def test_transcript_payload_default_role_is_assistant():
    """Untagged transcripts default to assistant — see TranscriptPayload docstring."""
    payload = TranscriptPayload(text="hi")
    assert payload.role == "assistant"


@pytest.mark.asyncio
async def test_handle_transcript_strips_user_sentinel_and_tags_role_on_node_path():
    """User-spoken transcripts: strip ``[user] `` AND tag role=user."""
    captured: list[tuple[str, dict]] = []

    async def fake_send_to_node(node_id: str, frame: dict):
        captured.append((node_id, frame))

    proxy = RealtimeProxy(send_to_node=fake_send_to_node)
    proxy._sessions["sess-1"] = RealtimeSession(
        session_id="sess-1",
        node_id="feral-iphone-test",
        api_key="sk-test",
    )

    await proxy._handle_transcript("sess-1", "[user] Hello brain", True)

    assert captured, "Expected a transcript frame to reach the node path."
    node_id, frame = captured[-1]
    assert node_id == "feral-iphone-test"
    assert frame["type"] == "transcript"
    payload = frame["payload"]
    assert payload["text"] == "Hello brain", (
        f"Internal `[user] ` sentinel must be stripped before wire emit; "
        f"got {payload['text']!r}"
    )
    assert payload["role"] == "user", (
        f"Sentinel-prefixed transcripts must be tagged role=user; "
        f"got {payload.get('role')!r}"
    )


@pytest.mark.asyncio
async def test_handle_transcript_assistant_text_is_role_assistant_on_node_path():
    """Assistant-spoken transcripts: pass through with role=assistant."""
    captured: list[tuple[str, dict]] = []

    async def fake_send_to_node(node_id: str, frame: dict):
        captured.append((node_id, frame))

    proxy = RealtimeProxy(send_to_node=fake_send_to_node)
    proxy._sessions["sess-2"] = RealtimeSession(
        session_id="sess-2",
        node_id="feral-iphone-test",
        api_key="sk-test",
    )

    await proxy._handle_transcript("sess-2", "Hey, Omar. How's it going?", True)

    assert captured
    payload = captured[-1][1]["payload"]
    assert payload["text"] == "Hey, Omar. How's it going?"
    assert payload["role"] == "assistant"


@pytest.mark.asyncio
async def test_handle_audio_delta_post_close_drops_session_no_throw():
    """Phone-side WS gone mid-stream: tear down session, do not bubble."""
    call_log: list[str] = []

    async def fake_send_to_node(node_id: str, frame: dict):
        call_log.append(node_id)
        raise RuntimeError(
            'Cannot call "send" once a close message has been sent.'
        )

    proxy = RealtimeProxy(send_to_node=fake_send_to_node)
    rs = RealtimeSession(
        session_id="sess-3",
        node_id="feral-iphone-test",
        api_key="sk-test",
    )
    proxy._sessions["sess-3"] = rs
    proxy._node_to_session["feral-iphone-test"] = "sess-3"

    # Should NOT raise — the proxy must swallow the closed-WS error
    # and drop the session so OpenAI stops being charged for tokens
    # we can't deliver.
    await proxy._handle_audio_delta("sess-3", "AAAA", False)

    assert "sess-3" not in proxy._sessions, (
        "Session must be torn down after a downstream RuntimeError; "
        "otherwise the OpenAI WS keeps streaming and the same error "
        "fires on every chunk."
    )
    assert call_log == ["feral-iphone-test"], (
        "send_to_node should have been attempted exactly once before the "
        f"session was dropped. Calls: {call_log}"
    )


@pytest.mark.asyncio
async def test_handle_transcript_post_close_drops_session_no_throw():
    """Same guard for the transcript path."""
    captured: list[str] = []

    async def fake_send_to_node(node_id: str, frame: dict):
        captured.append(node_id)
        raise RuntimeError(
            'Unexpected ASGI message "websocket.send", after sending '
            '"websocket.close"'
        )

    proxy = RealtimeProxy(send_to_node=fake_send_to_node)
    rs = RealtimeSession(
        session_id="sess-4",
        node_id="feral-iphone-test",
        api_key="sk-test",
    )
    proxy._sessions["sess-4"] = rs
    proxy._node_to_session["feral-iphone-test"] = "sess-4"

    await proxy._handle_transcript("sess-4", "tail", True)

    assert "sess-4" not in proxy._sessions
