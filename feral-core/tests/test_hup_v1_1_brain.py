"""Brain-side HUP v1.1 dispatch — audio_frame + video_frame routing.

Asserts the new branches in the /v1/node WebSocket handler exist and
route correctly:
  - video_frame and device_event(event_type=video_frame) go into
    state.vision_buffer.
  - audio_frame and device_event(event_type=audio_frame) call
    state.audio.ingest_frame when present.

Per HUP_SPEC.md §1's forward-compat rule, unknown device_event
event_types must NOT raise.
"""

from __future__ import annotations

import base64
import importlib

import pytest


pytestmark = pytest.mark.no_auto_feral_home


def _b64(size: int) -> str:
    return base64.b64encode(b"\x00" * size).decode("ascii")


@pytest.fixture()
def server_module(monkeypatch):
    """Import the live server module with a stub state.

    The handlers we exercise are module-level helpers, so we patch
    ``state`` after import and call them directly.
    """
    server = importlib.import_module("api.server")

    pushed = []
    ingested = []
    sessions: list[str] = []

    class FakeVisionBuffer:
        def push(self, node_id, payload):
            pushed.append((node_id, payload))

    class FakePerception:
        def update_vision(self, *_a, **_k):
            pass

    class FakeChangeDetector:
        def should_analyze(self, *_a, **_k):
            return None

    class FakeAudio:
        def ingest_frame(self, node_id, payload):
            ingested.append((node_id, payload))

    class FakeState:
        vision_buffer = FakeVisionBuffer()
        perception = FakePerception()
        change_detector = FakeChangeDetector()
        audio = FakeAudio()
        scene = None
        orchestrator = None

        def get_sessions_for_daemon(self, _node):
            return sessions

    monkeypatch.setattr(server, "state", FakeState())
    return server, pushed, ingested


def test_video_frame_lands_in_vision_buffer(server_module):
    server, pushed, _ingested = server_module
    payload = {
        "event_type": "video_frame",
        "codec": "jpeg",
        "width": 640,
        "height": 480,
        "sequence": 1,
        "data_b64": _b64(2048),
    }
    server._handle_video_frame("feral-w300-test", payload, msg_id="m1")
    assert len(pushed) == 1
    node_id, frame = pushed[0]
    assert node_id == "feral-w300-test"
    assert frame["codec"] == "jpeg"


def test_video_frame_over_cap_is_dropped(server_module):
    server, pushed, _ = server_module
    payload = {
        "event_type": "video_frame",
        "codec": "jpeg",
        "width": 640,
        "height": 480,
        "sequence": 2,
        "data_b64": "x" * (server.VIDEO_FRAME_MAX_BYTES + 8),
    }
    server._handle_video_frame("feral-w300-test", payload, msg_id="m2")
    assert pushed == []


def test_audio_frame_lands_in_audio_pipeline(server_module):
    server, _pushed, ingested = server_module
    payload = {
        "event_type": "audio_frame",
        "codec": "opus",
        "sample_rate": 24000,
        "channels": 1,
        "sequence": 5,
        "data_b64": _b64(512),
    }
    server._handle_audio_frame("feral-band-test", payload)
    assert len(ingested) == 1
    node_id, frame = ingested[0]
    assert node_id == "feral-band-test"
    assert frame["codec"] == "opus"


def test_audio_frame_over_cap_is_dropped(server_module):
    server, _pushed, ingested = server_module
    payload = {
        "event_type": "audio_frame",
        "codec": "opus",
        "sample_rate": 24000,
        "channels": 1,
        "sequence": 6,
        "data_b64": "x" * (server.AUDIO_FRAME_MAX_BYTES + 4),
    }
    server._handle_audio_frame("feral-band-test", payload)
    assert ingested == []


def test_audio_frame_no_pipeline_does_not_raise(server_module, monkeypatch):
    server, _pushed, _ingested = server_module
    # Strip the audio.ingest_frame method to mimic an early-boot brain.
    server.state.audio = object()
    payload = {
        "event_type": "audio_frame",
        "codec": "opus",
        "sample_rate": 24000,
        "channels": 1,
        "sequence": 0,
        "data_b64": _b64(64),
    }
    # Must NOT raise — daemon should not be punished for the brain
    # not being ready.
    server._handle_audio_frame("any", payload)
