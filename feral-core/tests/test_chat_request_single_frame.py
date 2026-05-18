"""Audit-r11 — Bug 1 (iOS double assistant bubble) pinning tests.

Before the fix:
  * Phone sends ``/v1/node chat_request`` over HUP.
  * Brain's chat_request handler binds the phone WS to
    ``state.sessions[target_sid]`` (when no desktop WS is already
    there) and calls ``orchestrator.handle_command*``. Orchestrator
    broadcasts ``text_response`` on that WS — phone sees ``text_response``.
  * Handler then sends a synchronous ``chat_response`` on the same WS.
  * Phone receives BOTH frames -> renders the assistant reply twice.

After the fix:
  * ``api/server.py`` sets
    ``orchestrator._text_response_suppressed[target_sid] = True`` for
    the duration of the turn (cleared in ``finally``).
  * ``response_delivery.send_text`` checks the flag and skips the
    broadcast ``text_response`` when set.
  * Phone receives only the ``chat_response``. Desktop clients (on a
    different session WS) keep getting ``text_response`` on their own
    turns because the flag is per-session-per-turn.

The tests exercise the helper directly to keep them hermetic — the
contract is verified at the seam where the bug used to leak.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.response_delivery import send_text


def _make_orchestrator():
    """Return an orchestrator stub matching the surface ``send_text``
    consults: a ``send`` coroutine, a ``_text_response_suppressed`` dict,
    and an optional ``voice_router``."""
    orchestrator = SimpleNamespace()
    orchestrator.send = AsyncMock()
    orchestrator._text_response_suppressed = {}
    orchestrator.voice_router = None
    return orchestrator


@pytest.mark.asyncio
async def test_send_text_emits_when_not_suppressed():
    orch = _make_orchestrator()
    await send_text(orch, "sess-desktop", "Hello world")

    assert orch.send.await_count == 1
    sent_msg = orch.send.await_args.args[1]
    assert sent_msg.type == "text_response"
    assert sent_msg.payload["text"] == "Hello world"


@pytest.mark.asyncio
async def test_send_text_skips_when_suppressed():
    """When the chat_request handler set the suppress flag, no
    ``text_response`` is broadcast — phone gets only ``chat_response``."""
    orch = _make_orchestrator()
    orch._text_response_suppressed["sess-phone"] = True

    await send_text(orch, "sess-phone", "Single bubble please")

    assert orch.send.await_count == 0


@pytest.mark.asyncio
async def test_suppression_is_per_session():
    """Suppressing the phone session must not silence concurrent
    desktop sessions — the flag is scoped per-session-per-turn."""
    orch = _make_orchestrator()
    orch._text_response_suppressed["sess-phone"] = True

    await send_text(orch, "sess-desktop", "Desktop reply")
    await send_text(orch, "sess-phone", "Phone reply")

    sent_sessions = [c.args[0] for c in orch.send.await_args_list]
    assert sent_sessions == ["sess-desktop"], (
        "phone session must be suppressed but desktop still emits"
    )


@pytest.mark.asyncio
async def test_send_text_triggers_whisper_fallback_when_degraded():
    """When the realtime provider died, send_text drives the whisper
    fallback so audio keeps flowing on degraded sessions."""
    orch = _make_orchestrator()
    router = SimpleNamespace()
    router.is_session_degraded = lambda sid: True
    router.synthesize_assistant_speech = AsyncMock(return_value=True)
    orch.voice_router = router

    await send_text(orch, "sess-degraded", "I am still talking.")

    router.synthesize_assistant_speech.assert_awaited_once_with(
        "sess-degraded", "I am still talking."
    )


@pytest.mark.asyncio
async def test_send_text_skips_whisper_when_session_healthy():
    """Healthy sessions go through the realtime PCM path — fallback
    must not double-synthesise audio."""
    orch = _make_orchestrator()
    router = SimpleNamespace()
    router.is_session_degraded = lambda sid: False
    router.synthesize_assistant_speech = AsyncMock()
    orch.voice_router = router

    await send_text(orch, "sess-ok", "All good.")

    router.synthesize_assistant_speech.assert_not_awaited()
