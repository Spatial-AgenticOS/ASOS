"""Tests for GUI Computer Use — coordinate scaling, DPI detection, rate limiting."""
import asyncio
import os
import platform
from unittest.mock import patch, MagicMock

import pytest

from skills.impl.gui_computer_use import (
    detect_dpi_scale,
    scale_coordinates,
    ActionRateLimiter,
    GUIComputerUseSkill,
)


# ─── Coordinate scaling ─────────────────────────────────────────


class TestCoordinateScaling:
    def test_2x_retina_scaling(self):
        """Screenshot coords (200, 300) on 2x display → physical (100, 150)."""
        px, py = scale_coordinates(200, 300, 2.0)
        assert px == 100
        assert py == 150

    def test_1x_no_scaling(self):
        px, py = scale_coordinates(100, 200, 1.0)
        assert px == 100
        assert py == 200

    def test_3x_scaling(self):
        px, py = scale_coordinates(300, 600, 3.0)
        assert px == 100
        assert py == 200

    def test_zero_scale_defaults_to_1(self):
        px, py = scale_coordinates(100, 100, 0.0)
        assert px == 100
        assert py == 100

    def test_negative_scale_defaults_to_1(self):
        px, py = scale_coordinates(50, 50, -2.0)
        assert px == 50
        assert py == 50

    def test_fractional_scale_125(self):
        """Windows-style 125% scaling."""
        px, py = scale_coordinates(125, 250, 1.25)
        assert px == 100
        assert py == 200

    def test_identity_at_origin(self):
        px, py = scale_coordinates(0, 0, 2.0)
        assert px == 0
        assert py == 0


# ─── DPI detection ───────────────────────────────────────────────


class TestDPIDetection:
    @patch("skills.impl.gui_computer_use.platform")
    def test_mac_returns_2_on_retina(self, mock_platform):
        mock_platform.system.return_value = "Darwin"
        with patch("skills.impl.gui_computer_use.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "2.0\n"
            mock_sub.run.return_value = mock_result
            scale = detect_dpi_scale()
            assert scale == 2.0

    @patch("skills.impl.gui_computer_use.platform")
    def test_mac_fallback_to_2_on_error(self, mock_platform):
        mock_platform.system.return_value = "Darwin"
        with patch("skills.impl.gui_computer_use.subprocess") as mock_sub:
            mock_sub.run.side_effect = Exception("no AppKit")
            scale = detect_dpi_scale()
            assert scale == 2.0

    @patch("skills.impl.gui_computer_use.platform")
    def test_linux_reads_gdk_scale(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        with patch.dict(os.environ, {"GDK_SCALE": "1.5"}):
            scale = detect_dpi_scale()
            assert scale == 1.5

    @patch("skills.impl.gui_computer_use.platform")
    def test_linux_default_1(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        env = os.environ.copy()
        env.pop("GDK_SCALE", None)
        with patch.dict(os.environ, env, clear=True):
            scale = detect_dpi_scale()
            assert scale == 1.0

    @patch("skills.impl.gui_computer_use.platform")
    def test_windows_returns_1(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        scale = detect_dpi_scale()
        assert scale == 1.0


# ─── Mouse position on 2x display ───────────────────────────────


class TestMousePositionScaling:
    def test_mouse_position_translates_on_2x(self):
        """Input (100, 100) on a 2x display should send pyautogui to (50, 50)."""
        sx, sy = scale_coordinates(100, 100, 2.0)
        assert sx == 50
        assert sy == 50

    def test_screenshot_capture_coords_2x(self):
        """For screenshot capture, (100,100) on 2x should scale to (200,200) in pixel space.
        This tests the inverse: the VLM sees 1920-wide image, actual screen is 3840.
        scale_coordinates divides by scale, which converts screenshot→physical."""
        physical_x, physical_y = scale_coordinates(100, 100, 2.0)
        assert physical_x == 50
        assert physical_y == 50


# ─── Rate limiter ────────────────────────────────────────────────


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        limiter = ActionRateLimiter(max_per_second=5)
        for _ in range(5):
            assert await limiter.acquire() is True

    @pytest.mark.asyncio
    async def test_rejects_over_limit(self):
        limiter = ActionRateLimiter(max_per_second=3)
        for _ in range(3):
            assert await limiter.acquire() is True
        assert await limiter.acquire() is False

    @pytest.mark.asyncio
    async def test_resets_after_window(self):
        limiter = ActionRateLimiter(max_per_second=2)
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True
        assert await limiter.acquire() is False
        await asyncio.sleep(1.1)
        assert await limiter.acquire() is True

    @pytest.mark.asyncio
    async def test_rate_limit_response_from_skill(self, monkeypatch):
        monkeypatch.setenv("FERAL_GUI_MAX_ACTIONS_PER_S", "1")
        skill = GUIComputerUseSkill()
        skill._scale = 1.0

        async def fake_click(*a, **kw):
            return skill._ok("clicked")

        skill._mouse_click = fake_click

        r1 = await skill.execute("mouse_click", {"x": 10, "y": 10}, {})
        assert r1["success"] is True

        r2 = await skill.execute("mouse_click", {"x": 10, "y": 10}, {})
        assert r2["success"] is False
        assert r2["reason"] == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_screenshot_bypasses_rate_limit(self, monkeypatch):
        monkeypatch.setenv("FERAL_GUI_MAX_ACTIONS_PER_S", "1")
        skill = GUIComputerUseSkill()
        skill._scale = 1.0

        async def fake_screenshot(args):
            return {"success": True, "status_code": 200, "data": {"image_base64": ""}, "error": None}

        skill._screenshot = fake_screenshot

        r1 = await skill.execute("screenshot", {}, {})
        assert r1["success"] is True
        r2 = await skill.execute("screenshot", {}, {})
        assert r2["success"] is True
