"""Welcome banner — first-run greeting."""

from __future__ import annotations

from ..helpers import get_console, _RICH_AVAILABLE

from ..state import WizardState


def run(state: WizardState) -> None:
    console = get_console()
    if _RICH_AVAILABLE:
        from rich.panel import Panel
        console.print(Panel.fit(
            "[bold]Welcome to FERAL.[/]\n\n"
            "This wizard sets up your local brain:\n"
            "  1. LLM provider + model (any cloud or local)\n"
            "  2. Speech in / out (cloud or fully local)\n"
            "  3. Who you are (for the agent's memory)\n"
            "  4. Optional: Home Assistant, messaging channels\n\n"
            "Type [bold]back[/] at any prompt to return to the previous step.\n"
            "Type [bold]quit[/] to stop and keep what you've entered so far.",
            title="feral setup",
            border_style="cyan",
        ))
    else:
        console.print("=" * 60)
        console.print("Welcome to FERAL.")
        console.print("This wizard sets up your local brain.")
        console.print("=" * 60)
