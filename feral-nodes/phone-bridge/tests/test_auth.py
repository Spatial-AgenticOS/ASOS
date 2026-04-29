"""Tests for phone-bridge Bearer auth migration and fallback logic."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets
from websockets import frames

from bridge import PhoneBridgeDaemon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_invalid_status(status_code: int) -> websockets.InvalidStatus:
    response = MagicMock()
    response.status_code = status_code
    exc = websockets.InvalidStatus.__new__(websockets.InvalidStatus)
    exc.response = response
    return exc


def _make_closed_error(code: int) -> websockets.ConnectionClosedError:
    return websockets.ConnectionClosedError(
        frames.Close(code, "unauthorized"),
        frames.Close(code, ""),
        rcvd_then_sent=True,
    )


def _daemon(
    brain_url: str = "ws://localhost:9090",
    api_key: str = "tok_test",
) -> PhoneBridgeDaemon:
    return PhoneBridgeDaemon(brain_url=brain_url, api_key=api_key)


def _ws_context_mock() -> MagicMock:
    """A mock that works as ``async with websockets.connect(...) as ws:``."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=ws)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# 1. Default path: Bearer header is set, no ?api_key= in URL
# ---------------------------------------------------------------------------

class TestBearerHeaderDefault:

    def test_no_api_key_in_url(self):
        daemon = _daemon()
        assert "api_key" not in daemon.ws_url
        assert daemon.ws_url == "ws://localhost:9090/v1/node"

    @pytest.mark.asyncio
    async def test_bearer_header_passed_to_connect(self):
        ctx = _ws_context_mock()
        daemon = _daemon()

        with patch("bridge.websockets.connect", return_value=ctx) as mock_connect:
            try:
                await daemon._run_session()
            except Exception:
                pass

            mock_connect.assert_called_once()
            _, kwargs = mock_connect.call_args
            assert kwargs["additional_headers"] == {
                "Authorization": "Bearer tok_test",
            }
            url = mock_connect.call_args[0][0]
            assert url == "ws://localhost:9090/v1/node"
            assert "api_key" not in url


# ---------------------------------------------------------------------------
# 2. Brain rejects Bearer → bridge retries with ?api_key= query + warns
# ---------------------------------------------------------------------------

class TestQueryAuthFallback:

    @pytest.mark.asyncio
    async def test_http_401_triggers_query_fallback(self, caplog):
        """InvalidStatus(401) on first connect → retry with ?api_key= query."""
        daemon = _daemon()
        calls: list[dict] = []

        async def fake_run_session(*, use_query_auth: bool = False) -> None:
            calls.append({"use_query_auth": use_query_auth})
            if not use_query_auth:
                raise _make_invalid_status(401)
            daemon.running = False

        with (
            patch.object(daemon, "_run_session", side_effect=fake_run_session),
            caplog.at_level(logging.WARNING),
        ):
            await daemon.run()

        assert len(calls) == 2
        assert calls[0]["use_query_auth"] is False
        assert calls[1]["use_query_auth"] is True
        assert "DEPRECATED" in caplog.text

    @pytest.mark.asyncio
    async def test_ws_4001_triggers_query_fallback(self, caplog):
        """ConnectionClosedError(4001) on first connect → retry with query."""
        daemon = _daemon()
        calls: list[dict] = []

        async def fake_run_session(*, use_query_auth: bool = False) -> None:
            calls.append({"use_query_auth": use_query_auth})
            if not use_query_auth:
                raise _make_closed_error(4001)
            daemon.running = False

        with (
            patch.object(daemon, "_run_session", side_effect=fake_run_session),
            caplog.at_level(logging.WARNING),
        ):
            await daemon.run()

        assert len(calls) == 2
        assert calls[1]["use_query_auth"] is True
        assert "DEPRECATED" in caplog.text

    @pytest.mark.asyncio
    async def test_query_fallback_url_contains_api_key(self):
        """When use_query_auth=True, the URL includes ?api_key=."""
        ctx = _ws_context_mock()
        daemon = _daemon(api_key="secret123")

        with patch("bridge.websockets.connect", return_value=ctx) as mock_connect:
            try:
                await daemon._run_session(use_query_auth=True)
            except Exception:
                pass

            url = mock_connect.call_args[0][0]
            assert "api_key=secret123" in url


# ---------------------------------------------------------------------------
# 3. wss:// URL → TLS scheme preserved, never downgraded
# ---------------------------------------------------------------------------

class TestTLSSchemePreserved:

    def test_wss_preserved(self):
        daemon = _daemon(brain_url="wss://brain.example.ts.net")
        assert daemon.ws_url == "wss://brain.example.ts.net/v1/node"

    def test_https_normalised_to_wss(self):
        daemon = _daemon(brain_url="https://brain.example.ts.net")
        assert daemon.ws_url.startswith("wss://")

    def test_http_normalised_to_ws(self):
        daemon = _daemon(brain_url="http://192.168.1.42:9090")
        assert daemon.ws_url.startswith("ws://")
        assert not daemon.ws_url.startswith("wss://")

    @pytest.mark.asyncio
    async def test_wss_url_sent_to_connect(self):
        ctx = _ws_context_mock()
        daemon = _daemon(brain_url="wss://brain.example.ts.net")

        with patch("bridge.websockets.connect", return_value=ctx) as mock_connect:
            try:
                await daemon._run_session()
            except Exception:
                pass

            url = mock_connect.call_args[0][0]
            assert url.startswith("wss://")


# ---------------------------------------------------------------------------
# 4. User passes plain --api-key value → ends up in Bearer header, not URL
# ---------------------------------------------------------------------------

class TestApiKeyInBearerNotURL:

    @pytest.mark.asyncio
    async def test_api_key_in_header_not_url(self):
        ctx = _ws_context_mock()
        secret = "my-super-secret-token-42"
        daemon = _daemon(api_key=secret)

        with patch("bridge.websockets.connect", return_value=ctx) as mock_connect:
            try:
                await daemon._run_session()
            except Exception:
                pass

            kwargs = mock_connect.call_args[1]
            assert kwargs["additional_headers"]["Authorization"] == f"Bearer {secret}"
            assert secret not in mock_connect.call_args[0][0]
