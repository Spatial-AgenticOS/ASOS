"""w300_daemon — FERAL HUP v1.1 W300 smart-glasses node.

Grabs JPEG frames from the W300 camera (UVC by default — swap the
``CameraCapture`` backend for your vendor SDK when needed) and streams
them to the Brain via ``FeralNode.emit_video_frame()``. Audio and IMU
emission are scaffolded but behind vendor-specific hooks because the
exact codec / characteristic choice depends on the SKU.

The IO layer is abstracted through protocols so unit tests inject a
fake camera + fake node without monkeypatching OpenCV.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from feral_node_sdk import FeralNode

logger = logging.getLogger("feral.w300_daemon")


# ------------------------------------------------------------------
# Camera abstraction
# ------------------------------------------------------------------

class CameraCapture(Protocol):
    def open(self) -> bool: ...
    def close(self) -> None: ...
    def grab_jpeg(self, *, width: int, height: int, quality: int) -> Optional[bytes]: ...


def _default_camera_factory(device: str = "0") -> CameraCapture:
    """OpenCV-based UVC capture, used in production. Opt-in via the
    ``camera`` optional dependency so CI never requires OpenCV."""

    try:
        import cv2  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python-headless is not installed. Install the "
            "[camera] extra or swap CameraCapture for your vendor SDK."
        ) from exc

    class _OpenCVCapture(CameraCapture):
        def __init__(self, dev: str) -> None:
            self._dev = int(dev) if dev.isdigit() else dev
            self._cap: object | None = None

        def open(self) -> bool:
            cap = cv2.VideoCapture(self._dev)
            if not cap.isOpened():
                return False
            self._cap = cap
            return True

        def close(self) -> None:
            if self._cap is not None:
                self._cap.release()
                self._cap = None

        def grab_jpeg(self, *, width: int, height: int, quality: int) -> Optional[bytes]:
            if self._cap is None:
                return None
            cap = self._cap
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
            if not ok:
                return None
            return buf.tobytes()

    return _OpenCVCapture(device)


# ------------------------------------------------------------------
# Daemon
# ------------------------------------------------------------------

@dataclass
class W300Config:
    brain_url: Optional[str] = None
    api_key: Optional[str] = None
    node_id: str = "feral-w300-0001"
    camera_device: str = "0"
    vision_interval_s: float = 5.0
    width: int = 1280
    height: int = 720
    quality: int = 75

    @classmethod
    def from_env(cls) -> "W300Config":
        return cls(
            brain_url=os.environ.get("FERAL_BRAIN_URL"),
            api_key=os.environ.get("FERAL_API_KEY"),
            node_id=os.environ.get("FERAL_W300_NODE_ID", "feral-w300-0001"),
            camera_device=os.environ.get("FERAL_W300_CAMERA_DEVICE", "0"),
            vision_interval_s=float(os.environ.get("FERAL_W300_VISION_INTERVAL", "5") or 5.0),
        )


class W300Daemon:
    def __init__(
        self,
        config: Optional[W300Config] = None,
        *,
        camera_factory: Callable[[str], CameraCapture] = _default_camera_factory,
        node_factory: Optional[Callable[[W300Config], FeralNode]] = None,
    ) -> None:
        self.config = config or W300Config.from_env()
        self._camera_factory = camera_factory
        self._node_factory = node_factory or self._make_node
        self.camera: Optional[CameraCapture] = None
        self.node: Optional[FeralNode] = None
        self._sequence = 0
        self._stop = asyncio.Event()

    def _make_node(self, cfg: W300Config) -> FeralNode:
        return FeralNode(
            node_id=cfg.node_id,
            name="FERAL W300",
            manufacturer="Theora",
            firmware_version="1.1.0",
            node_type="glasses",
            brain_url=cfg.brain_url,
            api_key=cfg.api_key,
            capabilities=["camera", "microphone", "imu", "display_hud"],
        )

    async def emit_one_frame(self) -> Optional[bytes]:
        """Grab one frame and ship it as HUP v1.1 ``video_frame``."""
        if self.camera is None or self.node is None:
            return None
        jpeg = self.camera.grab_jpeg(
            width=self.config.width,
            height=self.config.height,
            quality=self.config.quality,
        )
        if jpeg is None:
            return None
        data_b64 = base64.b64encode(jpeg).decode("ascii")
        try:
            await self.node.emit_video_frame(
                data_b64,
                codec="jpeg",
                width=self.config.width,
                height=self.config.height,
                sequence=self._sequence,
                keyframe=True,
            )
        except Exception as exc:
            logger.warning("emit_video_frame rejected locally: %s", exc)
            return jpeg
        self._sequence += 1
        return jpeg

    async def vision_loop(self) -> None:
        interval = max(0.1, self.config.vision_interval_s)
        while not self._stop.is_set():
            try:
                await self.emit_one_frame()
            except Exception as exc:
                logger.warning("vision_loop iteration failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def start(self) -> None:
        cfg = self.config
        self.node = self._node_factory(cfg)
        self.camera = self._camera_factory(cfg.camera_device)
        if not self.camera.open():
            raise RuntimeError(
                f"W300 camera {cfg.camera_device!r} failed to open; cannot "
                "fake a stream, refusing to start."
            )
        logger.info("w300_daemon online; camera=%s interval=%ss", cfg.camera_device, cfg.vision_interval_s)

        loop = asyncio.create_task(self.vision_loop())
        try:
            await self.node.run_async()
        finally:
            self._stop.set()
            await loop
            if self.camera:
                self.camera.close()

    async def stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------
# Entry points
# ------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FERAL W300 daemon")
    parser.add_argument("--brain-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--node-id", default=None)
    parser.add_argument("--camera-device", default=None)
    parser.add_argument("--vision-interval", type=float, default=None)
    return parser.parse_args(argv)


async def _async_main(argv: Optional[list[str]] = None) -> None:
    args = _parse_args(argv)
    cfg = W300Config.from_env()
    if args.brain_url:
        cfg.brain_url = args.brain_url
    if args.api_key:
        cfg.api_key = args.api_key
    if args.node_id:
        cfg.node_id = args.node_id
    if args.camera_device:
        cfg.camera_device = args.camera_device
    if args.vision_interval is not None:
        cfg.vision_interval_s = args.vision_interval

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )
    daemon = W300Daemon(cfg)
    try:
        await daemon.start()
    finally:
        await daemon.stop()


def main(argv: Optional[list[str]] = None) -> None:
    asyncio.run(_async_main(argv))


if __name__ == "__main__":
    main()
