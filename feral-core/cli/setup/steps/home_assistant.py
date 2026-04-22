"""Optional Home Assistant step — URL + long-lived token."""

from __future__ import annotations

from ..helpers import ask_text, confirm, get_console
from ..state import WizardState


def run(state: WizardState) -> None:
    console = get_console()
    console.print()
    console.print("[bold]Step 5 · Home Assistant[/]" if _rich() else "Step 5 · Home Assistant")

    if not confirm("  Connect a Home Assistant instance?", default=False):
        return

    default_url = state.get_setting("home_assistant", "url", "http://homeassistant.local:8123")
    url = ask_text("  Home Assistant URL", default=default_url, allow_empty=False)
    token = ask_text("  Long-lived access token", default="", allow_empty=False, secret=True)

    state.set_setting("home_assistant", "enabled", True)
    state.set_setting("home_assistant", "url", url)
    state.set_credential("HOME_ASSISTANT_URL", url)
    state.set_credential("HOME_ASSISTANT_TOKEN", token)


def _rich() -> bool:
    from ..helpers import _RICH_AVAILABLE
    return _RICH_AVAILABLE
