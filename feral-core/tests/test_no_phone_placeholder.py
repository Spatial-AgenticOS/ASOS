"""Regression: the brain must NEVER invent a phone the user didn't pair.

Four things used to pretend a phone was always connected:

1. ``_infer_node_type`` mapped any ``node_id`` containing "phone" /
   "pixel" / "iphone" to type "phone" even when the daemon didn't
   declare itself that way.
2. ``pair_device_qr`` defaulted ``name`` to ``"phone"`` so every QR
   issued pre-tagged itself as a phone.
3. Messaging channels (Telegram / Slack / Discord / WhatsApp) registered
   their session with ``node_type="phone"`` in SessionHandoff — so the
   handoff manager believed a phone was online forever.
4. ``/api/location/update`` defaulted ``source="phone"`` even when the
   browser pushed its own coordinates.

These tests lock down the honest replacements so the placeholder can
never come back silently.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_infer_node_type_no_phone_from_substring():
    from api.routes.devices import _infer_node_type

    ws = MagicMock()
    # No declared type, no mirror, no glasses/wristband/browser marker.
    ws._feral_node_type = None
    ws._feral_capabilities = []
    # Even a node_id with "phone" / "pixel" / "iphone" substrings must NOT
    # be auto-labelled "phone" — only an explicit register payload does.
    assert _infer_node_type("node-phone-5", ws) == "unknown"
    assert _infer_node_type("pixel-7-camera", ws) == "unknown"
    assert _infer_node_type("iphone-15", ws) == "unknown"


def test_infer_node_type_still_respects_declared_type():
    from api.routes.devices import _infer_node_type

    ws = MagicMock()
    ws._feral_node_type = "phone"
    assert _infer_node_type("node-abc", ws) == "phone"


def test_infer_node_type_classifies_browser_node():
    """Browser-Node (upcoming) must read as browser_node, not unknown."""
    from api.routes.devices import _infer_node_type

    ws = MagicMock()
    ws._feral_node_type = None
    assert _infer_node_type("browser-phone-abc", ws) == "browser_node"


def test_pair_device_qr_default_name_is_not_phone():
    """QR defaults are user-neutral, not implicit phones."""
    import inspect

    from api.routes.devices import pair_device_qr

    sig = inspect.signature(pair_device_qr)
    default = sig.parameters["name"].default
    assert default != "phone"
    assert default in ("unnamed", "device")


def test_session_handoff_allows_channel_node_type():
    """Telegram/Slack sessions register as `channel`, not `phone`."""
    from agents.session_handoff import NODE_TYPES, SessionHandoffManager

    assert "channel" in NODE_TYPES
    assert "browser_node" in NODE_TYPES

    mgr = SessionHandoffManager(sessions={})
    mgr.register_device("sess-1", "channel", node_id="telegram_u1")
    assert mgr._device_registry["sess-1"].node_type == "channel"
    # Phone is still in the list for real phone pairings — but channel
    # sessions no longer get miscategorised as one.
    assert "phone" in NODE_TYPES


def test_location_update_default_source_is_unknown():
    import inspect

    from perception.location import LocationEngine

    sig = inspect.signature(LocationEngine.update_location)
    default = sig.parameters["source"].default
    assert default == "unknown"
