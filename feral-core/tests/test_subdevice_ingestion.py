"""Sub-device status ingestion contract.

Pins the wire-format the brain accepts for every "my sub-device just
changed state" frame, plus the REST surface a UI binds to.

Two wire shapes both have to land in :class:`NodeSubdeviceStore`:

1. **iOS / native ``device_event``** envelope with ``event_type:
   "glasses_status"``. Payload carries ``status``, ``source``, plus
   any adapter-specific extras as ``data``. The companion app's
   ``JWBleSession.emitGlassesStatus`` produces this shape.
2. **Top-level ``glasses_status``** (legacy ``GlassesStatusPayload``):
   ``glasses_connected: bool``, ``battery_level: int``,
   ``glasses_model: str``. Older daemons / tests can still emit this
   directly.

Both must end up as a single canonical row in the truth store and
fire the ``subdevice_update`` callback exactly once per ingest.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from memory.node_subdevices import NodeSubdeviceStore


pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture()
def store(tmp_path):
    return NodeSubdeviceStore(db_path=str(tmp_path / "memory.db"))


@pytest.fixture()
def patched_state(tmp_path, store):
    """Patch ``api.server.state`` and ``api.routes.devices.state`` with
    a mock that exposes a real ``NodeSubdeviceStore`` plus the bare
    fields the helpers read.
    """
    mock = MagicMock()
    mock.node_subdevices = store
    mock.session_handoff = None
    mock.skill_executor = None
    mock.daemons = {}
    mock.devices = {}
    mock.somatic_engine = None
    mock.perception = MagicMock()
    mock.perception.get_frame.return_value = None
    mock.audio = MagicMock()
    mock.audio.available = True
    mock.audio.ingest_frame = None
    return mock


def test_device_event_glasses_status_lands_as_subdevice_row(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "feral-iphone-abc",
            "glasses_status",
            {
                "event_type": "glasses_status",
                "status": "ready",
                "source": "jw_health_glasses",
                "device_name": "Theora-1234",
                "rssi": -52,
                "ts": 1234567890.0,
            },
        )

    rows = store.list_for_node("feral-iphone-abc")
    assert len(rows) == 1
    row = rows[0]
    assert row["capability"] == "jw_health_glasses"
    assert row["status"] == "ready"
    assert row["provenance"] == "ble"
    assert row["attrs"]["device_name"] == "Theora-1234"
    assert row["attrs"]["rssi"] == -52
    # Reserved envelope fields must not bleed into ``attrs``.
    assert "event_type" not in row["attrs"]
    assert "ts" not in row["attrs"]


def test_device_event_status_failure_payload_lands(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "feral-iphone-abc",
            "glasses_status",
            {
                "status": "failed",
                "source": "jw_health_glasses",
                "reason": "bond_failure",
            },
        )

    rows = store.list_for_node("feral-iphone-abc")
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["attrs"]["reason"] == "bond_failure"


def test_legacy_glasses_status_boolean_maps_to_status_string(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "feral-iphone-abc",
            "glasses_status",
            {
                "glasses_connected": True,
                "battery_level": 88,
                "glasses_model": "Theora-W300",
            },
        )

    rows = store.list_for_node("feral-iphone-abc")
    assert len(rows) == 1
    row = rows[0]
    # No ``source`` declared → falls back to the event_type.
    assert row["capability"] == "glasses_status"
    assert row["status"] == "ready"
    assert row["attrs"]["battery_level"] == 88
    assert row["attrs"]["glasses_model"] == "Theora-W300"


def test_legacy_glasses_status_disconnected_maps_to_disconnected(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "feral-iphone-abc",
            "glasses_status",
            {
                "glasses_connected": False,
                "battery_level": 12,
            },
        )

    rows = store.list_for_node("feral-iphone-abc")
    assert rows[0]["status"] == "disconnected"


def test_missing_status_drops_payload_without_inventing_one(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "feral-iphone-abc",
            "glasses_status",
            {"source": "jw_health_glasses", "device_name": "Theora"},
        )

    # Truth-in-status: no status field → no row. We do NOT invent a
    # default ``"unknown"`` status because that would round-trip to
    # the dashboard as a real binding.
    assert store.list_for_node("feral-iphone-abc") == []


def test_missing_node_id_drops_payload(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "",
            "glasses_status",
            {"status": "ready", "source": "jw_health_glasses"},
        )

    assert store.list_all() == []


def test_unknown_provenance_normalises_to_ble(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "feral-iphone-abc",
            "glasses_status",
            {
                "status": "ready",
                "source": "jw_health_glasses",
                "provenance": "telepathy",  # not a real provenance
            },
        )

    rows = store.list_for_node("feral-iphone-abc")
    assert len(rows) == 1
    assert rows[0]["provenance"] == "ble"


def test_cloud_provenance_routed_through(patched_state, store):
    from api import server as server_mod

    with patch.object(server_mod, "state", patched_state):
        server_mod._handle_subdevice_status(
            "feral-iphone-abc",
            "whoop_status",
            {
                "status": "online",
                "source": "whoop_cloud",
                "provenance": "cloud",
                "last_sync_at": 1234567890.0,
            },
        )

    rows = store.list_for_node("feral-iphone-abc")
    assert len(rows) == 1
    row = rows[0]
    assert row["capability"] == "whoop_cloud"
    assert row["provenance"] == "cloud"
    assert row["liveness_window_s"] == 300.0  # cloud window
    assert row["attrs"]["last_sync_at"] == 1234567890.0
