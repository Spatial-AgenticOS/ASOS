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
