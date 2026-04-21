"""Offline unit tests for w300_daemon.

Uses a FakeCamera + FakeFeralNode so no real camera or brain connection
is required. These run in CI.
"""

from __future__ import annotations

import asyncio
import os
import struct
from typing import Callable, Optional

import pytest

from w300_daemon.daemon import (
    CameraCapture,
    W300Config,
    W300Daemon,
)


# ------------------------------------------------------------------
# Fake doubles
# ------------------------------------------------------------------

class FakeCamera(CameraCapture):
    def __init__(self, frame_bytes: bytes = b"\xff\xd8\xff\xe0tiny") -> None:
        self._frame = frame_bytes
        self.opened = False
        self.closed = False
        self.grabs = 0

    def open(self) -> bool:
        self.opened = True
        return True

    def close(self) -> None:
        self.closed = True

    def grab_jpeg(self, *, width: int, height: int, quality: int) -> Optional[bytes]:
        self.grabs += 1
        return self._frame


class FakeFeralNode:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.video_frames: list[dict] = []
        self.ran = False
        self._stop = asyncio.Event()

    def on_action(self, name: str):
        def _wrap(fn):
            return fn
        return _wrap

    async def emit_event(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))

    async def emit_video_frame(self, data_b64, *, codec, width, height, sequence, keyframe=True):
        self.video_frames.append({
            "codec": codec,
            "width": width,
            "height": height,
            "sequence": sequence,
            "keyframe": keyframe,
            "data_b64": data_b64,
        })

    async def run(self) -> None:
        self.ran = True
        await self._stop.wait()

    def request_stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

@pytest.fixture
def wired_daemon():
    cam_holder: dict = {}

    def camera_factory(device: str) -> FakeCamera:
        cam = FakeCamera()
        cam_holder["cam"] = cam
        return cam

    node = FakeFeralNode()

    def node_factory(_cfg):
        return node

    cfg = W300Config(
        brain_url="ws://127.0.0.1:9090",
        api_key="test",
        node_id="feral-w300-test",
        camera_device="0",
        vision_interval_s=0.05,
    )
    daemon = W300Daemon(cfg, camera_factory=camera_factory, node_factory=node_factory)
    return daemon, cam_holder, node


@pytest.mark.asyncio
async def test_start_opens_camera_and_runs_node(wired_daemon):
    daemon, cam_holder, node = wired_daemon
    task = asyncio.create_task(daemon.start())
    for _ in range(30):
        await asyncio.sleep(0.01)
        if node.ran:
            break
    assert node.ran, "node.run() was never invoked"
    assert cam_holder["cam"].opened

    node.request_stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert cam_holder["cam"].closed


@pytest.mark.asyncio
async def test_emit_one_frame_sends_video_frame(wired_daemon):
    daemon, _cam, node = wired_daemon
    task = asyncio.create_task(daemon.start())
    for _ in range(30):
        await asyncio.sleep(0.01)
        if node.ran:
            break
    assert node.ran

    jpeg = await daemon.emit_one_frame()
    assert jpeg is not None
    assert node.video_frames, "video_frame was never emitted"
    last = node.video_frames[-1]
    assert last["codec"] == "jpeg"
    assert last["width"] == daemon.config.width

    node.request_stop()
    await asyncio.wait_for(task, timeout=1.0)


def test_start_refuses_when_camera_fails_to_open():
    class DeadCam(CameraCapture):
        def open(self) -> bool:
            return False

        def close(self) -> None:
            pass

        def grab_jpeg(self, *, width, height, quality):
            return None

    node = FakeFeralNode()
    cfg = W300Config(
        brain_url="ws://127.0.0.1:9090",
        api_key="test",
        node_id="feral-w300-test",
        camera_device="0",
        vision_interval_s=0.1,
    )
    daemon = W300Daemon(cfg, camera_factory=lambda _dev: DeadCam(), node_factory=lambda _: node)
    with pytest.raises(RuntimeError, match="failed to open"):
        asyncio.run(daemon.start())


# ------------------------------------------------------------------
# Live gate
# ------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("FERAL_LIVE_W300_TEST") != "1",
    reason="Set FERAL_LIVE_W300_TEST=1 to run against the real glasses.",
)
def test_live_w300_emits_at_least_one_frame():
    pytest.skip("Live test stub — capture one video_frame when the user runs this.")
