"""A9 / W24d — identity_loader must not leak coroutines on its sync path.

The pre-W24d `_build_memory_context` called `asyncio.run(memory.build_context_for_llm_async(...))`.
If the caller was already inside a running event loop, `asyncio.run` raised
`RuntimeError` *after* the coroutine argument had been created, so the
coroutine object was dropped without ever being awaited, which caused:

    RuntimeWarning: coroutine 'MemoryStore.build_context_for_llm_async' was never awaited

These tests pin the post-fix behaviour: when a running loop exists, the async
factory is NEVER invoked and the sync sibling is used instead.
"""

from __future__ import annotations

import asyncio
import warnings

import pytest

from agents.identity_loader import IdentityLoader


class _StubMemory:
    """A minimal memory store with both sync and async builders.

    Records how many times each builder was called; the async factory is
    implemented as a regular method so that calling it produces a coroutine
    object (exactly the leak we are guarding against).
    """

    def __init__(self) -> None:
        self.async_calls: int = 0
        self.sync_calls: int = 0

    async def build_context_for_llm_async(
        self,
        session_id: str,
        query: str = "",
        max_tokens_budget: int = 2000,
        memory_filter: str = "",
    ) -> str:
        self.async_calls += 1
        return "## Memory (async)\nshould not appear when loop is running"

    def build_context_for_llm(
        self,
        session_id: str,
        query: str = "",
        max_tokens_budget: int = 2000,
        memory_filter: str = "",
    ) -> str:
        self.sync_calls += 1
        return "## Memory (sync)\nhello"


def _make_loader(memory: _StubMemory) -> IdentityLoader:
    """Construct an IdentityLoader without touching ~/.feral.

    We bypass `__init__` to avoid loading on-disk YAML; we only need the
    `_build_memory_context` method under test plus a `memory` attribute.
    """
    loader = IdentityLoader.__new__(IdentityLoader)
    loader.memory = memory  # type: ignore[attr-defined]
    return loader


def test_no_coroutine_warning_when_loop_is_running() -> None:
    memory = _StubMemory()
    loader = _make_loader(memory)

    async def _run() -> str:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = loader._build_memory_context(
                session_id="sess-A",
                query="hello",
                memory_filter="",
            )
            leaks = [
                w for w in caught
                if issubclass(w.category, RuntimeWarning)
                and "coroutine" in str(w.message)
                and "never awaited" in str(w.message)
            ]
            assert not leaks, (
                "sync-fallback path must not allocate an un-awaited "
                f"coroutine; got warnings: {[str(w.message) for w in leaks]}"
            )
        return out

    result = asyncio.run(_run())
    assert "## Memory (sync)" in result
    assert memory.sync_calls == 1
    assert memory.async_calls == 0, (
        "while an event loop is running, the async builder must not be "
        "invoked at all (that is what creates the un-awaited coroutine)"
    )


def test_async_path_still_used_when_no_loop_is_running() -> None:
    memory = _StubMemory()
    loader = _make_loader(memory)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = loader._build_memory_context(
            session_id="sess-B",
            query="world",
            memory_filter="",
        )
        leaks = [
            w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "coroutine" in str(w.message)
            and "never awaited" in str(w.message)
        ]
        assert not leaks, (
            f"no-loop path must also not leak coroutines; got: "
            f"{[str(w.message) for w in leaks]}"
        )

    assert memory.async_calls == 1
    assert memory.sync_calls == 0
    assert "## Memory (async)" in out


def test_no_memory_returns_empty_string_without_warnings() -> None:
    loader = IdentityLoader.__new__(IdentityLoader)
    loader.memory = None  # type: ignore[attr-defined]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = loader._build_memory_context(
            session_id="sess-C",
            query="",
            memory_filter="",
        )
    assert out == ""
    assert not [
        w for w in caught
        if issubclass(w.category, RuntimeWarning)
        and "coroutine" in str(w.message)
    ]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
