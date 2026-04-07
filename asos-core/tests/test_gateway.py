"""Tests for THEORA gateway WebSocket RPC protocol."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.protocol import (
    GatewayError,
    GatewaySession,
    MethodRegistry,
    make_event,
    make_request,
    make_response,
)


class TestFrameHelpers:
    """make_request / make_response / make_event shapes."""

    def test_make_request_frame_shape(self):
        msg = make_request("chat.send", {"text": "hi"}, req_id="abc123")
        assert msg["type"] == "req"
        assert msg["id"] == "abc123"
        assert msg["method"] == "chat.send"
        assert msg["params"] == {"text": "hi"}

    def test_make_response_ok(self):
        msg = make_response("rid-1", payload={"status": "ok"}, ok=True)
        assert msg["type"] == "res"
        assert msg["id"] == "rid-1"
        assert msg["ok"] is True
        assert msg["payload"] == {"status": "ok"}
        assert "error" not in msg

    def test_make_response_error(self):
        err = {"code": "INVALID_PARAMS", "message": "bad"}
        msg = make_response("rid-2", ok=False, error=err)
        assert msg["ok"] is False
        assert msg["error"] == err

    def test_make_event_has_seq(self):
        msg = make_event("stream.delta", {"token": "x"}, seq=7)
        assert msg["type"] == "event"
        assert msg["event"] == "stream.delta"
        assert msg["payload"] == {"token": "x"}
        assert msg["seq"] == 7


class TestMethodRegistry:
    """Handler registration and dispatch."""

    def test_register_list_call(self):
        reg = MethodRegistry()
        calls = []

        async def handler(session_id: str, params: dict, session):
            calls.append((session_id, params))
            return {"echo": params.get("x")}

        reg.register("demo.echo", handler)
        assert "demo.echo" in reg.methods
        assert reg.get("demo.echo") is handler


class TestGatewayError:
    """Structured gateway errors."""

    def test_code_and_message(self):
        err = GatewayError("NOT_FOUND", "missing resource", {"id": "1"})
        assert err.code == "NOT_FOUND"
        assert "missing resource" in str(err)
        d = err.to_dict()
        assert d["code"] == "NOT_FOUND"
        assert d["details"] == {"id": "1"}


class TestGatewaySession:
    """Session dispatches requests via registry."""

    @pytest.mark.asyncio
    async def test_handle_message_dispatches_to_registry(self):
        reg = MethodRegistry()

        async def ping_handler(session_id: str, params: dict, session: GatewaySession):
            return {"pong": True}

        reg.register("ping", ping_handler)

        ws = MagicMock()
        ws.send_json = AsyncMock()

        session = GatewaySession("sess-1", ws, reg)
        await session.handle_message(
            {"type": "req", "id": "req-9", "method": "ping", "params": {}}
        )

        ws.send_json.assert_awaited()
        sent = ws.send_json.await_args.args[0]
        assert sent["type"] == "res"
        assert sent["id"] == "req-9"
        assert sent["ok"] is True
        assert sent["payload"] == {"pong": True}

    @pytest.mark.asyncio
    async def test_unknown_method_error(self):
        reg = MethodRegistry()
        ws = MagicMock()
        ws.send_json = AsyncMock()
        session = GatewaySession("s", ws, reg)
        await session.handle_message(
            {"type": "req", "id": "x", "method": "nope", "params": {}}
        )
        sent = ws.send_json.await_args.args[0]
        assert sent["ok"] is False
        assert sent["error"]["code"] == "METHOD_NOT_FOUND"
