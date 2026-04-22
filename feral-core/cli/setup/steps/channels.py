"""Optional messaging channels — Telegram / Discord / Slack / WhatsApp."""

from __future__ import annotations

from ..helpers import ask_text, confirm, get_console, _RICH_AVAILABLE
from ..state import WizardState


_CHANNEL_FIELDS = {
    "telegram": [("FERAL_TELEGRAM_BOT_TOKEN", "Bot token", True)],
    "discord": [("FERAL_DISCORD_BOT_TOKEN", "Bot token", True)],
    "slack": [
        ("FERAL_SLACK_BOT_TOKEN", "Bot token (xoxb-...)", True),
        ("FERAL_SLACK_APP_TOKEN", "App token (xapp-...)", True),
    ],
    "whatsapp": [
        ("FERAL_WHATSAPP_PHONE_NUMBER_ID", "Phone number ID", False),
        ("FERAL_WHATSAPP_ACCESS_TOKEN", "Access token", True),
    ],
}


def run(state: WizardState) -> None:
    console = get_console()
    console.print()
    console.print("[bold]Step 6 · Messaging channels[/]" if _RICH_AVAILABLE else "Step 6 · Messaging channels")

    if not confirm("  Connect any messaging channels? (skip to add later)", default=False):
        return

    configured: list[str] = list(state.get_setting("channels", "configured", []) or [])
    for channel, fields in _CHANNEL_FIELDS.items():
        if not confirm(f"  Configure {channel}?", default=False):
            continue
        for env_key, label, secret in fields:
            existing = state.credentials.get(env_key, "")
            if existing and not confirm(f"    Replace existing {env_key}?", default=False):
                continue
            value = ask_text(f"    {label}", default="", allow_empty=False, secret=secret)
            state.set_credential(env_key, value)
        if channel not in configured:
            configured.append(channel)

    state.set_setting("channels", "configured", configured)
