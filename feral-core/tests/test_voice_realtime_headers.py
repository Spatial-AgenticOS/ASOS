"""Regression test pinning the websockets header-kwarg contract.

The brain calls the **legacy** ``websockets.connect`` entrypoint, which
in websockets 13.x is exposed as ``websockets.legacy.client.Connect``.
That entrypoint accepts ``extra_headers``. The newer
``websockets.asyncio.client.connect`` renamed the same kwarg to
``additional_headers``.

If a future refactor swaps in ``additional_headers``, the legacy
``create_connection`` rejects the unknown kwarg with
``TypeError: create_connection() got an unexpected keyword argument
'additional_headers'`` and every voice provider silently fails to
connect (only surfacing as ``Voice session failed to connect`` warnings
in the brain log). This test catches the regression at unit-test time
instead of at real-hardware smoke time.

Pinned by the v2026.5.17 voice fix; see ``voice/realtime_proxy.py``
``OpenAIRealtimeProxy.connect`` and the parallel call sites in
``voice/gemini_realtime.py`` and ``voice/stt_providers/deepgram.py``.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest


def test_websockets_legacy_connect_accepts_extra_headers() -> None:
    """The kwarg the brain passes must be on the installed entrypoint."""
    import websockets

    sig = inspect.signature(websockets.connect)
    params = sig.parameters
    assert "extra_headers" in params, (
        "websockets.connect lost extra_headers — the brain's voice path "
        "passes that kwarg explicitly. Either upgrade the call sites to "
        "websockets.asyncio.client.connect (additional_headers) or pin "
        "websockets to a version that still ships the legacy client."
    )


def _grep_for_bad_kwarg(path: str) -> list[str]:
    """Return any line in ``path`` that passes ``additional_headers=``."""
    hits: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if "additional_headers=" in line and not line.lstrip().startswith("#"):
                hits.append(f"{path}:{lineno}: {line.rstrip()}")
    return hits


def test_no_voice_module_passes_additional_headers() -> None:
    """Pin the wire-level kwarg used by every voice client."""
    from pathlib import Path

    voice_root = Path(__file__).resolve().parent.parent / "voice"
    bad: list[str] = []
    for py in voice_root.rglob("*.py"):
        bad.extend(_grep_for_bad_kwarg(str(py)))
    assert not bad, (
        "Voice modules pass `additional_headers=` to websockets.connect, "
        "which is the legacy entrypoint and rejects that kwarg. Use "
        "`extra_headers=` until the call sites migrate to the asyncio "
        "client. Hits:\n  " + "\n  ".join(bad)
    )


def test_realtime_proxy_connect_attempts_actually_dispatch() -> None:
    """Smoke-test that the proxy hits the patched websockets.connect.

    We don't talk to OpenAI here — we monkey-patch ``websockets.connect``
    to capture the kwargs and raise. The point is to confirm the call
    site survives kwarg validation, which the previous bug did not.
    """
    import websockets

    captured: dict[str, object] = {}

    async def fake_connect(uri, **kwargs):  # type: ignore[no-untyped-def]
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        raise RuntimeError("dial halted (test)")

    original = websockets.connect
    websockets.connect = fake_connect  # type: ignore[assignment]
    try:
        from voice.realtime_proxy import RealtimeSession

        session = RealtimeSession(
            session_id="test-session",
            node_id="test-node",
            api_key="sk-test",
        )

        async def _run() -> None:
            await session.connect()

        asyncio.run(_run())
    finally:
        websockets.connect = original  # type: ignore[assignment]

    assert captured.get("uri", "").startswith("wss://"), captured
    assert "extra_headers" in captured["kwargs"], (
        "OpenAIRealtimeProxy.connect must pass extra_headers to the "
        "legacy websockets.connect entrypoint. Got: "
        f"{sorted(captured['kwargs'].keys())}"
    )
    assert "additional_headers" not in captured["kwargs"], (
        "additional_headers re-introduced — see "
        "tests/test_voice_realtime_headers.py docstring."
    )
