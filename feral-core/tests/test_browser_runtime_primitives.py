"""PR3: BrowserController runtime primitives.

Pinning the new contracts:

* Playwright driver lifecycle — ``close()`` must call ``stop()`` on the
  driver started in ``initialize()``. Skipping it leaks an async
  driver subprocess per controller instance.
* Dual-mode selector resolution — ``:has-text("X")`` is a Playwright
  pseudo-selector; the CDP-only path must split tag + text and locate
  via a JS text scan instead of choking on ``document.querySelector``.
* ``wait_for_selector`` — must poll a real condition, return a
  structured ``success``/``error`` dict, and never silently sleep
  through the budget when the selector exists immediately.
"""

from __future__ import annotations

import pytest

from skills.impl.browser_use import BrowserController


class TestPlaywrightLifecycle:
    """The Playwright driver started in initialize() must be released
    by close(). Otherwise every brain restart leaks a node subprocess.
    """

    @pytest.mark.asyncio
    async def test_close_stops_playwright_driver(self) -> None:
        ctrl = BrowserController()

        class _FakeDriver:
            def __init__(self) -> None:
                self.stopped = False

            async def stop(self) -> None:
                self.stopped = True

        driver = _FakeDriver()
        ctrl._playwright = driver

        await ctrl.close()

        assert driver.stopped is True
        assert ctrl._playwright is None
        assert ctrl._page is None

    @pytest.mark.asyncio
    async def test_close_clears_browser_handle(self) -> None:
        ctrl = BrowserController()

        class _FakeBrowser:
            def __init__(self) -> None:
                self.closed = False

            async def close(self) -> None:
                self.closed = True

        browser = _FakeBrowser()
        ctrl._browser = browser

        await ctrl.close()

        assert browser.closed is True
        assert ctrl._browser is None


class TestSelectorParsing:
    """``:has-text("X")`` must round-trip through the CDP path."""

    def test_parse_has_text_extracts_tag_and_text(self) -> None:
        tag, text = BrowserController._parse_has_text('button:has-text("Buy now")')
        assert tag == "button"
        assert text == "Buy now"

    def test_parse_has_text_handles_single_quotes(self) -> None:
        tag, text = BrowserController._parse_has_text("a:has-text('Sign in')")
        assert tag == "a"
        assert text == "Sign in"

    def test_parse_has_text_returns_none_for_plain_css(self) -> None:
        tag, text = BrowserController._parse_has_text("#submit")
        assert tag is None
        assert text == ""

    @pytest.mark.asyncio
    async def test_resolve_aria_selectors_records_text_match(self) -> None:
        """When ``:has-text("...")`` is the best we can do, the impl
        also records ``text_match`` so the CDP-only path doesn't have
        to re-parse the pseudo-selector at action time."""
        ctrl = BrowserController()
        ctrl._aria_refs["ax0"] = {
            "backend_id": 99,
            "name": "Continue",
            "selector": "",
        }

        class _FakeCDP:
            async def send_command(self, method, params=None, timeout=30.0):
                return {
                    "node": {
                        "localName": "button",
                        "attributes": [],
                    }
                }

        ctrl._cdp = _FakeCDP()  # type: ignore[assignment]
        await ctrl._resolve_aria_selectors()
        info = ctrl._aria_refs["ax0"]
        assert info["selector"] == 'button:has-text("Continue")'
        assert info["text_match"] == {"tag": "button", "text": "Continue"}


class TestWaitForSelector:
    """``wait_for_selector`` must poll real DOM, not just sleep."""

    @pytest.mark.asyncio
    async def test_wait_for_selector_succeeds_immediately_via_cdp(self) -> None:
        ctrl = BrowserController()
        # No Playwright page -> CDP-only path.
        ctrl._page = None
        ctrl._cdp._connected = True

        async def _send_command(method, params=None, timeout=30.0):
            assert method == "Runtime.evaluate"
            return {"result": {"value": True}}

        ctrl._cdp.send_command = _send_command  # type: ignore[assignment]

        result = await ctrl.wait_for_selector("#submit", timeout_ms=200, poll_ms=20)
        assert result["success"] is True
        assert result["selector"] == "#submit"
        assert result["via"] == "cdp"

    @pytest.mark.asyncio
    async def test_wait_for_selector_times_out_with_real_error(self) -> None:
        ctrl = BrowserController()
        ctrl._page = None
        ctrl._cdp._connected = True

        async def _send_command(method, params=None, timeout=30.0):
            return {"result": {"value": False}}

        ctrl._cdp.send_command = _send_command  # type: ignore[assignment]

        result = await ctrl.wait_for_selector(
            "#never-appears", timeout_ms=120, poll_ms=20,
        )
        assert result["success"] is False
        assert "never-appears" in result["error"]
        assert result["via"] == "cdp"

    @pytest.mark.asyncio
    async def test_wait_for_selector_uses_playwright_when_available(self) -> None:
        ctrl = BrowserController()

        captured = {}

        class _FakePage:
            url = "about:blank"

            async def wait_for_selector(self, selector, timeout, state):
                captured["selector"] = selector
                captured["timeout"] = timeout
                captured["state"] = state
                return object()

        ctrl._page = _FakePage()  # type: ignore[assignment]

        result = await ctrl.wait_for_selector(
            "button.cta", timeout_ms=750, state="attached",
        )
        assert result["success"] is True
        assert result["via"] == "playwright"
        assert captured == {
            "selector": "button.cta",
            "timeout": 750,
            "state": "attached",
        }


class TestBrowserManifestExposesNewEndpoints:
    def test_wait_for_selector_listed(self) -> None:
        from skills.impl.browser_use import get_browser_skill_manifest

        endpoint_ids = {e["id"] for e in get_browser_skill_manifest()["endpoints"]}
        assert "wait_for_selector" in endpoint_ids
