"""Speech in / out step — the missing piece from the old wizard.

Renders two side-by-side tables (STT + TTS) with their ready-state,
lets the user pick a provider + model + voice, writes the choice
into settings.json.audio so AudioPipeline actually honours it at
runtime.

No more hand-editing ``settings.json`` to go fully-local.
"""

from __future__ import annotations

from perception.audio_pipeline import detect_local_audio_capabilities

from ..helpers import (
    STATUS_NEEDS_KEY,
    STATUS_READY,
    STATUS_UNAVAILABLE,
    Option,
    ask_choice,
    ask_text,
    confirm,
    get_console,
    render_provider_table,
    _RICH_AVAILABLE,
)
from ..state import WizardState


_STT_PROVIDERS = (
    {
        "id": "openai",
        "label": "OpenAI Whisper (cloud)",
        "needs_key": True,
        "env": "OPENAI_API_KEY",
        "is_local": False,
        "aliases": ("openai", "whisper", "whisper-cloud"),
        "default_model": "whisper-1",
        "available_models": ["whisper-1"],
    },
    {
        "id": "faster-whisper",
        "label": "faster-whisper (local)",
        "needs_key": False,
        "env": "",
        "is_local": True,
        "aliases": ("local", "whisper-local", "local-whisper", "faster_whisper"),
        "default_model": "base",
        "available_models": ["tiny", "base", "small", "medium", "large"],
    },
)


_TTS_PROVIDERS = (
    {
        "id": "openai",
        "label": "OpenAI TTS (cloud)",
        "needs_key": True,
        "env": "OPENAI_API_KEY",
        "is_local": False,
        "aliases": ("openai", "openai-tts"),
        "default_model": "tts-1",
        "default_voice": "nova",
        "available_models": ["tts-1", "tts-1-hd"],
        "available_voices": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
    },
    {
        "id": "piper",
        "label": "Piper (local)",
        "needs_key": False,
        "env": "",
        "is_local": True,
        "aliases": ("local", "piper-local"),
        "default_model": "piper",
        "default_voice": "en_US-lessac-medium",
        "available_models": ["piper"],
        "available_voices": [
            "en_US-lessac-medium", "en_US-amy-low", "en_GB-alan-medium",
        ],
    },
)


async def run(state: WizardState) -> None:
    console = get_console()
    caps = detect_local_audio_capabilities()
    has_local_stt = bool(caps.get("local_stt"))
    has_local_tts = bool(caps.get("local_tts"))
    has_openai_key = bool(
        state.credentials.get("OPENAI_API_KEY")
        or state.has_credential("OPENAI_API_KEY")
    )

    if _RICH_AVAILABLE:
        console.print()
        console.print("[bold]Step 3 · Speech in / out (optional)[/]")
        console.print(
            "Pick how FERAL should listen + speak. Skip if you only use text chat."
        )

    if not confirm("  Configure voice now?", default=False):
        state.set_setting("audio", "stt_provider", state.get_setting("audio", "stt_provider", "openai"))
        state.set_setting("audio", "tts_provider", state.get_setting("audio", "tts_provider", "openai"))
        return

    if confirm("  Prefer fully-local voice? (no cloud, no keys)", default=has_local_stt and has_local_tts):
        _configure_local(state, has_local_stt, has_local_tts, console)
        return

    _configure_provider(state, "stt", _STT_PROVIDERS, has_local_stt, has_openai_key, caps, console)
    _configure_provider(state, "tts", _TTS_PROVIDERS, has_local_tts, has_openai_key, caps, console)


def _configure_local(state: WizardState, has_stt: bool, has_tts: bool, console) -> None:
    if has_stt:
        state.set_setting("audio", "stt_provider", "faster-whisper")
        state.set_setting("audio", "stt_model", "base")
    else:
        state.set_setting("audio", "stt_provider", "faster-whisper")
        state.set_setting("audio", "stt_model", "base")
        console.print(
            "  [yellow]faster-whisper isn't installed.[/] Run "
            "`pip install feral-ai[stt]` and voice input will auto-enable."
            if _RICH_AVAILABLE else
            "  faster-whisper isn't installed. Run: pip install feral-ai[stt]"
        )
    if has_tts:
        state.set_setting("audio", "tts_provider", "piper")
        state.set_setting("audio", "tts_voice", "en_US-lessac-medium")
    else:
        state.set_setting("audio", "tts_provider", "piper")
        state.set_setting("audio", "tts_voice", "en_US-lessac-medium")
        console.print(
            "  [yellow]piper isn't installed.[/] Run `pip install feral-ai[tts]`."
            if _RICH_AVAILABLE else
            "  piper isn't installed. Run: pip install feral-ai[tts]"
        )


def _configure_provider(
    state: WizardState,
    kind: str,
    providers: tuple[dict, ...],
    local_available: bool,
    has_openai_key: bool,
    caps: dict,
    console,
) -> None:
    options = []
    for prov in providers:
        if prov["is_local"]:
            status = STATUS_READY if local_available else STATUS_UNAVAILABLE
            hint = "ready" if local_available else f"install feral-ai[{'stt' if kind == 'stt' else 'tts'}]"
        else:
            status = STATUS_READY if has_openai_key else STATUS_NEEDS_KEY
            hint = prov["env"]
        options.append(
            Option(id=prov["id"], label=prov["label"], aliases=prov["aliases"], status=status, hint=hint)
        )

    title = "Speech-to-text" if kind == "stt" else "Text-to-speech"
    render_provider_table(title, options)
    default = state.get_setting("audio", f"{kind}_provider", "openai")
    chosen = ask_choice(f"Choose {title} provider", options, default=default)
    state.set_setting("audio", f"{kind}_provider", chosen.id)

    # Model + voice
    prov_def = next(p for p in providers if p["id"] == chosen.id)
    models = list(prov_def["available_models"])
    if chosen.id == "faster-whisper":
        models = list(caps.get("stt_models") or models)
    if models:
        console.print("  Models: " + ", ".join(models))
    default_model = state.get_setting("audio", f"{kind}_model", prov_def["default_model"])
    model = ask_text("  Model", default=default_model, allow_empty=False)
    state.set_setting("audio", f"{kind}_model", model)

    if kind == "tts":
        voices = list(prov_def.get("available_voices") or [])
        if chosen.id == "piper":
            voices = list(caps.get("tts_voices") or voices)
        if voices:
            console.print("  Voices: " + ", ".join(voices))
        default_voice = state.get_setting("audio", "tts_voice", prov_def.get("default_voice", ""))
        voice = ask_text("  Voice", default=default_voice or (voices[0] if voices else ""), allow_empty=False)
        state.set_setting("audio", "tts_voice", voice)
