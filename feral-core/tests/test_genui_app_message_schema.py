"""Tests for the app→host postMessage envelope.

Mirrors the spec's four named cases plus a "host validator never
throws" case so an attacker can't crash the parent's message loop
just by sending malformed JSON.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genui.app_message_schema import (
    AppMessage,
    AppMessageType,
    MAX_PAYLOAD_BYTES,
    validate_app_message,
)


def _valid_payload(**overrides):
    base = {
        "type": "request_data",
        "payload": {"surface_id": "home"},
        "message_id": "m-1",
        "signed_with_key_id": "test-key-do-not-commit",
    }
    base.update(overrides)
    return base


def test_valid_app_message_parses():
    msg = AppMessage.model_validate(_valid_payload())
    assert msg.type == AppMessageType.REQUEST_DATA.value
    assert msg.payload == {"surface_id": "home"}
    assert msg.message_id == "m-1"
    assert msg.signed_with_key_id == "test-key-do-not-commit"


def test_missing_type_is_rejected():
    raw = _valid_payload()
    raw.pop("type")
    with pytest.raises(ValidationError):
        AppMessage.model_validate(raw)


def test_unknown_type_is_rejected():
    raw = _valid_payload(type="evil_unknown")
    with pytest.raises(ValidationError):
        AppMessage.model_validate(raw)


def test_oversized_payload_is_rejected():
    # Build a payload whose JSON encoding exceeds MAX_PAYLOAD_BYTES.
    big_string = "x" * (MAX_PAYLOAD_BYTES + 1)
    raw = _valid_payload(payload={"blob": big_string})
    with pytest.raises(ValidationError):
        AppMessage.model_validate(raw)


def test_extra_field_is_rejected():
    """Pydantic ``extra="forbid"`` keeps attackers from smuggling in
    side-channel keys that the host might forward."""
    raw = _valid_payload()
    raw["smuggled"] = "exfil"
    with pytest.raises(ValidationError):
        AppMessage.model_validate(raw)


def test_validate_app_message_drops_malformed_silently():
    """The host's window.message guard must never throw; it returns None
    so the message loop stays alive even under malformed input."""
    assert validate_app_message(None) is None
    assert validate_app_message("plain string") is None
    assert validate_app_message(123) is None
    assert validate_app_message({}) is None
    assert validate_app_message({"type": "evil"}) is None
    # Missing message_id
    assert validate_app_message({
        "type": "request_data",
        "payload": {},
        "signed_with_key_id": "k",
    }) is None
    # Unknown extra field
    assert validate_app_message({
        **_valid_payload(),
        "smuggled": "x",
    }) is None


def test_validate_app_message_passes_through_valid_payload():
    msg = validate_app_message(_valid_payload(type="navigate"))
    assert msg is not None
    assert msg.type == AppMessageType.NAVIGATE.value
