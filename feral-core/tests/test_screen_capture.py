from __future__ import annotations

import pytest

from skills.impl import get_implementation


def test_screen_capture_registered() -> None:
    impl = get_implementation("screen_capture")
    assert impl is not None


@pytest.mark.asyncio
async def test_screen_capture_unknown_endpoint() -> None:
    impl = get_implementation("screen_capture")
    assert impl is not None
    out = await impl.execute("unknown", {}, {})
    assert out["success"] is False
    assert out["status_code"] == 404
