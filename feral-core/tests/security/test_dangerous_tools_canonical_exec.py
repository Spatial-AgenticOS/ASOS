"""PR2: canonical-execution surface deny additions.

The dangerous_tools registry must classify and deny the new alias and
escape-hatch tool ids that were silent before:

* ``coding_tools__bash`` / ``coding_tools__write_file`` /
  ``coding_tools__edit_file`` — alias of computer_use; previously a
  bypass of the http_api deny list.
* ``agentic_computer_use__execute_task`` — VLM loop entry point that
  emits ``shell`` actions; must refuse on http_api so a remote surface
  can't kick off a desktop-vision agent without operator presence.

These tests deliberately mirror the existing deny-list test style so a
later refactor that drops one of these entries is caught loudly.
"""

from __future__ import annotations

import pytest

from security.dangerous_tools import (
    DangerLevel,
    SURFACE_DENY_LISTS,
    get_danger_level,
    is_tool_allowed,
)


CRITICAL_NEW_HTTP_DENIES = (
    "coding_tools__bash",
    "agentic_computer_use__execute_task",
)

WARN_NEW_TOOLS = (
    "coding_tools__write_file",
    "coding_tools__edit_file",
)


@pytest.mark.parametrize("tool_name", CRITICAL_NEW_HTTP_DENIES + WARN_NEW_TOOLS)
def test_new_tools_denied_on_http_api(tool_name: str) -> None:
    assert is_tool_allowed(tool_name, "http_api") is False, (
        f"deny-list FAILED: {tool_name!r} must be denied on http_api"
    )


@pytest.mark.parametrize("tool_name", CRITICAL_NEW_HTTP_DENIES)
def test_new_critical_tools_classified_critical(tool_name: str) -> None:
    assert get_danger_level(tool_name) == DangerLevel.CRITICAL


@pytest.mark.parametrize("tool_name", WARN_NEW_TOOLS)
def test_new_filesystem_tools_classified_warn(tool_name: str) -> None:
    assert get_danger_level(tool_name) == DangerLevel.WARN


def test_websocket_surface_unchanged_for_new_tools() -> None:
    """The interactive operator channel intentionally lets these
    through (per-tool consent gates them); verify the websocket deny
    list still treats them as allowed so we don't silently regress
    the operator-driven flow."""
    for tool_name in CRITICAL_NEW_HTTP_DENIES + WARN_NEW_TOOLS:
        assert is_tool_allowed(tool_name, "websocket") is True


def test_local_cli_surface_unchanged() -> None:
    """``feral grant``-driven CLI flow stays unrestricted by surface deny."""
    assert SURFACE_DENY_LISTS["local_cli"] == set()
