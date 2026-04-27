"""A6 — ambient-loop gating + toggle-path correctness.

These tests pin the Wave-0 A6 behaviour contract so the ambient
``ScreenLoop`` and ``ProactiveEngine`` cannot come back as
"always-on" quota burners, and so the ``/api/config/update``
toggle route stays await-correct:

* Vision flag drift: ``features.vision`` and ``vision.enabled``
  are coalesced by ``ConfigLoader`` so the UI and the env export
  never disagree.
* ``ScreenLoop._tick`` no longer passes ``force=True`` to the
  ``SceneAnalyzer`` — the cooldown knob exists for a reason and
  must actually apply.
* ``ScreenLoop.stop`` is awaitable; calling it without ``await``
  produces a ``RuntimeWarning`` — the route must await it on
  vision-disable.
* ``ProactiveEngine.stop`` is synchronous; awaiting it raises.
"""

from __future__ import annotations

import asyncio
import json
import warnings
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.loader import ConfigLoader


# ── 1. Config unification ─────────────────────────────────────────

pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture(autouse=True)
def _clean_feral_env(monkeypatch):
    """Scrub ambient FERAL_* env so config-unification tests see the
    file-based values only (not whatever is already in the shell)."""
    import os as _os
    for key in list(_os.environ):
        if key.startswith("FERAL_"):
            monkeypatch.delenv(key, raising=False)


def _loader(tmp_path):
    loader = ConfigLoader(project_dir=str(tmp_path))
    loader.user_home = tmp_path / ".feral"
    loader.user_home.mkdir(parents=True, exist_ok=True)
    return loader


class TestVisionFlagUnification:
    def test_features_vision_true_implies_vision_enabled(self, tmp_path):
        loader = _loader(tmp_path)
        (loader.user_home / "settings.json").write_text(
            json.dumps({"features": {"vision": True}})
        )
        loader.discover()
        assert loader._merged["vision"]["enabled"] is True
        assert loader._merged["features"]["vision"] is True
        assert loader.export_as_env()["FERAL_VISION_ENABLED"] == "true"

    def test_vision_enabled_true_implies_features_vision(self, tmp_path):
        loader = _loader(tmp_path)
        (loader.user_home / "settings.json").write_text(
            json.dumps({"vision": {"enabled": True}})
        )
        loader.discover()
        assert loader._merged["features"]["vision"] is True
        assert loader.export_as_env()["FERAL_VISION_ENABLED"] == "true"

    def test_both_off_keeps_flag_false(self, tmp_path):
        loader = _loader(tmp_path)
        (loader.user_home / "settings.json").write_text(
            json.dumps({"features": {"vision": False}, "vision": {"enabled": False}})
        )
        loader.discover()
        assert loader.export_as_env()["FERAL_VISION_ENABLED"] == "false"

    def test_update_settings_mirrors_vision_keys(self, tmp_path):
        loader = _loader(tmp_path)
        loader.discover()
        loader.update_settings("features", "vision", True)
        assert loader._merged["vision"]["enabled"] is True

        persisted = json.loads((loader.user_home / "settings.json").read_text())
        assert persisted["features"]["vision"] is True
        assert persisted["vision"]["enabled"] is True


# ── 2. ScreenLoop tick cooldown respect ───────────────────────────

class TestScreenLoopCooldownRespected:
    @pytest.mark.asyncio
    async def test_tick_does_not_force_scene_analyze(self, tmp_path, monkeypatch):
        from perception import screen_loop as _sl

        # Pretend the screenshot succeeded and produced bytes.
        monkeypatch.setattr(_sl, "_capture_screenshot", AsyncMock(return_value=True))
        monkeypatch.setattr(
            _sl,
            "_downscale_and_encode",
            lambda raw, target_width=640: ("b64", "image/jpeg"),
        )

        tmp_file = tmp_path / "shot.png"
        tmp_file.write_bytes(b"x")

        scene = MagicMock()
        scene.available = True
        scene.analyze_frame = AsyncMock(
            return_value={"scene_description": "desc", "detected_objects": []}
        )

        loop = _sl.ScreenLoop(
            perception=MagicMock(),
            memory=MagicMock(),
            llm=None,
            scene_analyzer=scene,
        )
        loop._tmp_path = tmp_file

        await loop._tick()

        scene.analyze_frame.assert_awaited_once()
        _args, kwargs = scene.analyze_frame.await_args
        assert kwargs.get("force", False) is False, (
            "ScreenLoop._tick must not force periodic scene analysis; "
            "cooldown is the quota kill-switch."
        )


# ── 3. stop() shapes (await-correctness contract) ─────────────────

class TestStopShapes:
    @pytest.mark.asyncio
    async def test_screen_loop_stop_is_coroutine(self):
        from perception.screen_loop import ScreenLoop

        loop = ScreenLoop()
        result = loop.stop()
        assert asyncio.iscoroutine(result), (
            "ScreenLoop.stop must remain ``async def`` so the config "
            "route's ``await state.screen_loop.stop()`` works."
        )
        await result

    @pytest.mark.asyncio
    async def test_proactive_stop_is_awaitable(self):
        """A6 accepts either sync stop (no await in route) or async
        stop (await in route). A7 landed the async variant so the loop
        task is actually cancelled rather than merely flagged. This
        pins that contract so the config route's
        ``await state.proactive.stop()`` cannot regress."""
        from agents.proactive_engine import ProactiveEngine

        engine = ProactiveEngine(perception=None, memory=None)
        result = engine.stop()
        assert asyncio.iscoroutine(result), (
            "ProactiveEngine.stop must remain ``async def`` (A7) so "
            "the toggle route can cancel the loop task cleanly."
        )
        await result

    def test_bare_screen_loop_stop_without_await_warns(self):
        from perception.screen_loop import ScreenLoop

        loop = ScreenLoop()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            coro = loop.stop()
            del coro
        # On CPython, dropping an un-awaited coroutine emits a
        # RuntimeWarning. If we ever silently "fixed" stop() to be
        # sync we would lose this signal.
        assert any(
            issubclass(w.category, RuntimeWarning) for w in caught
        ), "Expected RuntimeWarning for un-awaited ScreenLoop.stop()"


# ── 4. Boot-time gating ───────────────────────────────────────────

class TestBootGating:
    def test_feature_flag_helper_is_strict(self, monkeypatch):
        from api.state import _feature_flag_enabled

        monkeypatch.delenv("FOO_FLAG", raising=False)
        assert _feature_flag_enabled("FOO_FLAG") is False

        for v in ("true", "1", "YES", "On"):
            monkeypatch.setenv("FOO_FLAG", v)
            assert _feature_flag_enabled("FOO_FLAG") is True

        for v in ("false", "0", "no", "", "maybe"):
            monkeypatch.setenv("FOO_FLAG", v)
            assert _feature_flag_enabled("FOO_FLAG") is False
