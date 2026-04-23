"""Summary + 'what's next' banner."""

from __future__ import annotations

from ..helpers import get_console, _RICH_AVAILABLE
from ..state import WizardState


def run(state: WizardState) -> None:
    console = get_console()
    llm = state.settings.get("llm", {}) or {}
    audio = state.settings.get("audio", {}) or {}
    ha_on = bool((state.settings.get("home_assistant") or {}).get("enabled"))
    channels = (state.settings.get("channels") or {}).get("configured") or []

    summary_lines = [
        "[bold]You're set up.[/]" if _RICH_AVAILABLE else "You're set up.",
        "",
        f"  LLM:     {llm.get('provider', '?')} · {llm.get('model', '?')}",
        f"  STT:     {audio.get('stt_provider', 'openai')} · {audio.get('stt_model', '?')}",
        f"  TTS:     {audio.get('tts_provider', 'openai')} · {audio.get('tts_model', '?')}"
        + (f" · voice {audio.get('tts_voice', '?')}" if audio.get('tts_voice') else ""),
    ]
    if ha_on:
        summary_lines.append("  HA:      enabled")
    if channels:
        summary_lines.append(f"  Channels: {', '.join(channels)}")
    summary_lines += [
        "",
        "Next:",
        "  `feral start`        launches the brain + chat.",
        "  `feral setup`        re-run this wizard anytime.",
        "  http://localhost:9090/settings  web-based settings.",
    ]
    for line in summary_lines:
        console.print(line)
