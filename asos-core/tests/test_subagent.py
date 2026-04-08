from __future__ import annotations

import pytest

from skills.impl import get_implementation


def test_subagent_registered() -> None:
    impl = get_implementation("subagent")
    assert impl is not None


@pytest.mark.asyncio
async def test_subagent_impl_returns_orchestrator_runtime_error() -> None:
    impl = get_implementation("subagent")
    assert impl is not None
    out = await impl.execute("spawn_subagent", {"tasks": ["a"]}, {})
    assert out["success"] is False
    assert out["status_code"] == 501
