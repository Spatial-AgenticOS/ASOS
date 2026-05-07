"""/api/devices/connected must report real HUP node_type.

Until this commit the route hardcoded a ``{"type": "desktop"}`` fake
row for every request and labelled every daemon ``"phone"`` regardless
of what the HUP ``node_register`` payload actually declared. The v2
Devices page then showed a "generic phone always connected" that
wasn't a phone at all — it was the user's own browser, or an actual
wristband / glasses mislabelled.

This test pins the new contract:
* No fake desktop row when session_handoff is absent.
* A registered HUP daemon reports the node_type it declared, not
  ``"phone"``.
* Capabilities and platform declared at node_register are surfaced.
* Empty ``state.daemons`` returns ``{"devices": []}`` — never a
  fabricated row.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


class _FakeWebSocket:
    """Minimal stand-in for the live WebSocket attributes we read.

    The real /v1/node handler calls ``setattr(ws, "_feral_node_type",
    ...)`` at node_register time — these fake sockets mirror that
    exact shape so the route sees the same attributes it would in
    production.
    """

    def __init__(self, *, node_type: str, capabilities=None, platform="", manufacturer="", model=""):
        self._feral_node_type = node_type
        self._feral_capabilities = list(capabilities or [])
        self._feral_platform = platform
        self._feral_manufacturer = manufacturer
        self._feral_model = model


@pytest.fixture()
def client(tmp_path):
    from memory.node_subdevices import NodeSubdeviceStore

    mock = MagicMock()
    mock.session_handoff = None  # force the non-handoff path
    mock.skill_executor = None
    mock.node_subdevices = NodeSubdeviceStore(db_path=str(tmp_path / "memory.db"))
    mock.daemons = {
        "feral-w300-0001": _FakeWebSocket(
            node_type="glasses",
            capabilities=["camera", "microphone", "imu"],
            platform="macOS",
            manufacturer="Theora",
            model="W300",
        ),
        "feral-wristband-0001": _FakeWebSocket(
            node_type="wearable",
            capabilities=["heart_rate", "spo2", "haptic"],
            platform="linux",
            manufacturer="Theora",
            model="WB-100",
        ),
    }

    with patch("api.state.state", mock), patch("api.routes.devices.state", mock):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=False)


def test_no_fake_desktop_row_injected(client):
    r = client.get("/api/devices/connected")
    assert r.status_code == 200
    body = r.json()
    assert "devices" in body
    for dev in body["devices"]:
        # Legacy bug surfaced a hardcoded desktop row with
        # session_id=='local' and no node_id. That must never appear
        # again unless session_handoff supplies it.
        assert not (dev.get("type") == "desktop" and dev.get("session_id") == "local" and not dev.get("node_id"))


def test_glasses_daemon_reports_glasses_not_phone(client):
    r = client.get("/api/devices/connected")
    body = r.json()
    w300 = next(d for d in body["devices"] if d.get("node_id") == "feral-w300-0001")
    assert w300["type"] == "glasses", f"glasses daemon mislabeled as {w300['type']!r}"
    # Capabilities from node_register flow through.
    assert "camera" in w300["capabilities"]
    assert w300["manufacturer"] == "Theora"


def test_wristband_daemon_reports_wearable_not_phone(client):
    r = client.get("/api/devices/connected")
    body = r.json()
    band = next(d for d in body["devices"] if d.get("node_id") == "feral-wristband-0001")
    assert band["type"] == "wearable", f"wristband daemon mislabeled as {band['type']!r}"
    assert "heart_rate" in band["capabilities"]


def test_empty_daemons_returns_empty_list(client):
    # Override daemons to be empty.
    from api.routes import devices as devices_route
    devices_route.state.daemons = {}
    r = client.get("/api/devices/connected")
    body = r.json()
    assert body["devices"] == []


def test_infer_node_type_fallback_heuristic():
    """When _feral_node_type is absent, fall back on node_id heuristic
    rather than defaulting to 'phone'."""
    from api.routes.devices import _infer_node_type

    class _BareWs:
        pass

    assert _infer_node_type("feral-w300-xyz", _BareWs()) == "glasses"
    assert _infer_node_type("feral-wristband-abc", _BareWs()) == "wearable"
    assert _infer_node_type("somebody-robot-01", _BareWs()) == "robot"
    assert _infer_node_type("unknown-thing-01", _BareWs()) == "unknown"


# ─────────────────────────────────────────────
# Sub-device tree on /api/devices/connected
# ─────────────────────────────────────────────

def test_connected_devices_attaches_empty_subdevices_when_none_reported(client):
    r = client.get("/api/devices/connected")
    body = r.json()
    for dev in body["devices"]:
        # Empty list is the truthful answer when no sub-device frames
        # have arrived. Never omit the field — clients should be able
        # to read ``dev["subdevices"]`` without an existence check.
        assert dev["subdevices"] == []


def test_connected_devices_surfaces_real_subdevice_rows(client):
    from api.routes import devices as devices_route

    devices_route.state.node_subdevices.upsert(
        node_id="feral-w300-0001",
        capability="jw_health_glasses",
        status="ready",
        attrs={"device_name": "Theora-1234", "rssi": -52},
        provenance="ble",
    )

    r = client.get("/api/devices/connected")
    body = r.json()
    w300 = next(d for d in body["devices"] if d["node_id"] == "feral-w300-0001")
    assert len(w300["subdevices"]) == 1
    subdev = w300["subdevices"][0]
    assert subdev["capability"] == "jw_health_glasses"
    assert subdev["status"] == "ready"
    assert subdev["live"] is True
    assert subdev["attrs"]["device_name"] == "Theora-1234"

    # Other nodes stay clean (no cross-bleed).
    band = next(d for d in body["devices"] if d["node_id"] == "feral-wristband-0001")
    assert band["subdevices"] == []


def test_node_subdevices_endpoint_returns_full_tree(client):
    from api.routes import devices as devices_route

    devices_route.state.node_subdevices.upsert(
        node_id="feral-iphone-abc",
        capability="jw_health_glasses",
        status="ready",
        provenance="ble",
    )
    devices_route.state.node_subdevices.upsert(
        node_id="feral-iphone-abc",
        capability="apple_healthkit",
        status="ready",
        provenance="host",
    )

    r = client.get("/api/devices/feral-iphone-abc/subdevices")
    assert r.status_code == 200
    body = r.json()
    caps = sorted(s["capability"] for s in body["subdevices"])
    assert caps == ["apple_healthkit", "jw_health_glasses"]


def test_node_subdevices_endpoint_returns_empty_for_unknown_node(client):
    r = client.get("/api/devices/never-paired-node/subdevices")
    assert r.status_code == 200
    assert r.json() == {"subdevices": []}
