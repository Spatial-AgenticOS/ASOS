"""Tests for the streaming protocol and message types."""

import pytest
from models.protocol import (
    TheoraMessage,
    StreamDeltaPayload,
    GesturePayload,
    parse_message,
    MESSAGE_TYPES,
)


class TestStreamDelta:
    def test_stream_delta_payload(self):
        payload = StreamDeltaPayload(delta="Hello", stream_id="abc123", is_final=False)
        assert payload.delta == "Hello"
        assert payload.stream_id == "abc123"
        assert payload.is_final is False

    def test_stream_delta_final(self):
        payload = StreamDeltaPayload(delta="", stream_id="abc123", is_final=True)
        assert payload.is_final is True
        assert payload.delta == ""

    def test_stream_delta_in_message(self):
        msg = TheoraMessage(
            session_id="s1", hop="brain", type="stream_delta",
            payload=StreamDeltaPayload(delta="Hi", stream_id="x").model_dump(),
        )
        assert msg.type == "stream_delta"
        assert msg.payload["delta"] == "Hi"

    def test_stream_delta_parse(self):
        raw = {
            "type": "stream_delta",
            "hop": "brain",
            "payload": {"delta": "token", "stream_id": "s1", "is_final": False},
        }
        msg, payload = parse_message(raw)
        assert msg.type == "stream_delta"
        assert isinstance(payload, StreamDeltaPayload)
        assert payload.delta == "token"


class TestGesturePayload:
    def test_gesture_payload_fields(self):
        payload = GesturePayload(gesture="nod", confidence=0.9, source="imu")
        assert payload.gesture == "nod"
        assert payload.confidence == 0.9
        assert payload.source == "imu"

    def test_gesture_defaults(self):
        payload = GesturePayload(gesture="shake")
        assert payload.confidence == 1.0
        assert payload.source == "imu"

    def test_gesture_in_message_types(self):
        assert "gesture" in MESSAGE_TYPES
        assert MESSAGE_TYPES["gesture"] == GesturePayload

    def test_gesture_parse(self):
        raw = {
            "type": "gesture",
            "hop": "daemon",
            "payload": {"gesture": "double_tap", "confidence": 0.85, "source": "imu"},
        }
        msg, payload = parse_message(raw)
        assert isinstance(payload, GesturePayload)
        assert payload.gesture == "double_tap"


class TestNewMessageTypes:
    def test_all_new_types_registered(self):
        assert "stream_delta" in MESSAGE_TYPES
        assert "gesture" in MESSAGE_TYPES

    def test_total_message_types(self):
        # We should have at least 17 message types now
        assert len(MESSAGE_TYPES) >= 17
