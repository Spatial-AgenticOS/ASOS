"""Typed parsing coverage for phone-as-peer HUP v1.3 envelopes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.protocol import (
    BackchannelRequestPayload,
    ChatRequestPayload,
    ChatResponsePayload,
    GenUIEventPayload,
    GenUIPushPayload,
    PeripheralBridgeRegisterPayload,
    VoiceInterruptPayload,
    VoiceSessionStartPayload,
    parse_message,
)


@pytest.mark.parametrize(
    "msg_type,payload,expected_cls",
    [
        (
            "chat_request",
            {
                "session_id": "phone-session-1",
                "text": "what is that object?",
                "reply_mode": "final",
                "channel": "chat",
                "reply_to": None,
            },
            ChatRequestPayload,
        ),
        (
            "chat_response",
            {
                "session_id": "phone-session-1",
                "text": "It looks like a coffee mug.",
                "reply_mode": "final",
                "channel": "chat",
                "reply_to": None,
            },
            ChatResponsePayload,
        ),
        (
            "voice_session_start",
            {
                "stream_id": "voice-stream-1",
                "sample_rate": 16000,
                "channels": 1,
                "language_hint": "en-US",
                "mode": "push_to_talk",
                "interrupt_policy": "barge_in",
                "camera_linked": True,
            },
            VoiceSessionStartPayload,
        ),
        (
            "voice_interrupt",
            {"stream_id": "voice-stream-1", "reason": "user_interrupt"},
            VoiceInterruptPayload,
        ),
        (
            "genui_push",
            {
                "kind": "notification",
                "app_id": "feral.notes",
                "surface_id": "today",
                "title": "Door cam needs permission",
                "body": "Open live view?",
                "actions": [{"id": "approve", "label": "Approve", "value": {"action": "approve"}}],
            },
            GenUIPushPayload,
        ),
        (
            "genui_event",
            {
                "app_id": "feral.notes",
                "surface_id": "today",
                "event_type": "tap",
                "action_id": "approve",
                "value": {"action": "approve"},
            },
            GenUIEventPayload,
        ),
        (
            "peripheral_bridge_register",
            {
                "bridge_id": "phone-bridge-1",
                "platform": "android",
                "devices": [
                    {
                        "device_id": "smart_glasses_01",
                        "kind": "glasses",
                        "protocol": "web_bluetooth",
                        "capabilities": ["imu", "notifications"],
                        "status": "connected",
                        "manifest": {},
                    }
                ],
                "expires_at": "2026-04-30T12:00:00Z",
            },
            PeripheralBridgeRegisterPayload,
        ),
        (
            "backchannel_request",
            {
                "request_id": "req-backchannel-1",
                "device_id": "phone-node-1",
                "kind": "bug",
                "payload": {"summary": "voice dropped mid-turn"},
                "status": "pending",
            },
            BackchannelRequestPayload,
        ),
    ],
)
def test_parse_phone_envelopes(msg_type, payload, expected_cls):
    msg, parsed_payload = parse_message(
        {
            "type": msg_type,
            "hup_version": "1.3.0",
            "ts": 1734369922.123,
            "payload": payload,
        }
    )
    assert msg.type == msg_type
    assert isinstance(parsed_payload, expected_cls)


@pytest.mark.parametrize(
    "msg_type,payload_missing_required",
    [
        ("chat_request", {"text": "missing session_id"}),
        ("chat_response", {"session_id": "phone-session-1"}),
        ("voice_session_start", {"stream_id": "voice-stream-1"}),
        # voice_interrupt NO LONGER has required fields — stream_id
        # moved to Optional in v2026.5.9 so the phone UI's tap-to-
        # interrupt on the orb doesn't fail validation when it
        # doesn't know the current stream id. Dropped from this
        # "missing required fields" parametrisation accordingly.
        (
            "genui_push",
            {"kind": "notification", "app_id": "feral.notes", "surface_id": "today"},
        ),
        ("genui_event", {"app_id": "feral.notes", "surface_id": "today"}),
        ("peripheral_bridge_register", {"bridge_id": "bridge-1", "platform": "android"}),
        ("backchannel_request", {"kind": "bug"}),
    ],
)
def test_parse_phone_envelopes_missing_required_fields_raise(msg_type, payload_missing_required):
    with pytest.raises(ValidationError):
        parse_message(
            {
                "type": msg_type,
                "hup_version": "1.3.0",
                "ts": 1734369922.123,
                "payload": payload_missing_required,
            }
        )


# ─────────────────────────────────────────────────────────────────────
# ChatResponsePayload.error — Phase 1.5 truth-in-status field
# ─────────────────────────────────────────────────────────────────────


def test_chat_response_payload_error_field_round_trips_when_set():
    """The new ``error`` field on ``ChatResponsePayload`` must survive
    ``parse_message`` so a chat-only client (one that doesn't track
    the parallel HUP ``error`` frame) can still surface a real failure
    string. Previously a brain orchestrator exception silently produced
    ``text=""``; the audit-r7 brief 1 §8 flagged that as a real lie.
    """
    msg, parsed = parse_message(
        {
            "type": "chat_response",
            "hup_version": "1.3.0",
            "ts": 1734369922.123,
            "payload": {
                "session_id": "phone-session-1",
                "text": "",
                "reply_mode": "final",
                "channel": "chat",
                "reply_to": None,
                "error": "Orchestrator failed: LLM hard fail: budget exceeded",
            },
        }
    )
    assert msg.type == "chat_response"
    assert isinstance(parsed, ChatResponsePayload)
    assert parsed.error == "Orchestrator failed: LLM hard fail: budget exceeded"
    assert parsed.text == ""


def test_chat_response_payload_error_defaults_to_none_on_success():
    """Success branch: clients that omit the error field must read it
    back as ``None`` so a healthy turn doesn't carry a false truthy
    error to the UI.
    """
    msg, parsed = parse_message(
        {
            "type": "chat_response",
            "hup_version": "1.3.0",
            "ts": 1734369922.123,
            "payload": {
                "session_id": "phone-session-1",
                "text": "Done.",
                "reply_mode": "final",
                "channel": "chat",
                "reply_to": None,
            },
        }
    )
    assert msg.type == "chat_response"
    assert isinstance(parsed, ChatResponsePayload)
    assert parsed.error is None
    assert parsed.text == "Done."


def test_chat_response_payload_error_explicit_null_round_trips():
    """A client that explicitly emits ``error: null`` must round-trip
    cleanly to ``None`` — pinning the wire-format contract that future
    schema validators won't reject the explicit-null shape.
    """
    msg, parsed = parse_message(
        {
            "type": "chat_response",
            "hup_version": "1.3.0",
            "ts": 1734369922.123,
            "payload": {
                "session_id": "phone-session-1",
                "text": "ack",
                "reply_mode": "final",
                "channel": "chat",
                "reply_to": None,
                "error": None,
            },
        }
    )
    assert isinstance(parsed, ChatResponsePayload)
    assert parsed.error is None
