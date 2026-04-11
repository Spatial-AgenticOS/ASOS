"""
FERAL Voice Personality — SOUL.md + USER.md injection for voice
=================================================================
Loads the agent's identity files and generates contextual voice
instructions that are prepended to the OpenAI Realtime system prompt.
Also provides natural filler phrases for interruptions and thinking
pauses so the voice experience feels human.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

logger = logging.getLogger("feral.voice.personality")

_INTERRUPT_RESPONSES = [
    "Oh, go ahead!",
    "Sure, what's up?",
    "Yeah?",
    "Go ahead, I'm listening.",
    "Of course — what do you need?",
]

_THINKING_FILLERS = [
    "Hmm, let me check on that…",
    "One moment…",
    "Let me look into that…",
    "Just a sec…",
    "Thinking…",
    "Working on it…",
    "Bear with me a moment…",
]

_TOD_GREETINGS = {
    "morning": "Good morning",
    "afternoon": "Good afternoon",
    "evening": "Good evening",
    "night": "It's late",
}


class VoicePersonality:
    """Builds personality-aware voice instructions from SOUL.md + USER.md."""

    def __init__(self, identity_workspace=None):
        self._workspace = identity_workspace
        self._soul_cache: Optional[str] = None
        self._user_cache: Optional[str] = None
        self._cache_ts: float = 0
        self._cache_ttl: float = 60.0

    def _refresh_cache(self):
        now = time.time()
        if self._soul_cache is not None and (now - self._cache_ts) < self._cache_ttl:
            return
        if self._workspace is None:
            self._try_load_workspace()
        if self._workspace is not None:
            try:
                self._soul_cache = self._workspace.read_soul() or ""
                self._user_cache = self._workspace.read_user() or ""
            except Exception as exc:
                logger.warning("Failed to read identity files: %s", exc)
                self._soul_cache = self._soul_cache or ""
                self._user_cache = self._user_cache or ""
        else:
            self._soul_cache = self._soul_cache or ""
            self._user_cache = self._user_cache or ""
        self._cache_ts = now

    def _try_load_workspace(self):
        """Late-import IdentityWorkspace to avoid circular deps at module level."""
        try:
            from identity.workspace import IdentityWorkspace
            self._workspace = IdentityWorkspace()
        except Exception:
            pass

    def get_voice_instructions(
        self,
        time_of_day: str = "",
        user_name: str = "",
        recent_context: str = "",
    ) -> str:
        """
        Build a contextual system prompt fragment for the voice channel.

        The returned string is meant to be *prepended* to the existing
        Realtime session instructions so the agent's personality comes
        through in spoken responses.
        """
        self._refresh_cache()

        parts: list[str] = []

        parts.append(
            "You are FERAL — a personal AI operating system that speaks naturally. "
            "Keep voice responses concise and warm. Avoid markdown formatting in "
            "spoken output; use plain conversational English."
        )

        if self._soul_cache:
            parts.append(f"\n## Personality (SOUL)\n{self._soul_cache}")

        if self._user_cache:
            parts.append(f"\n## About the User\n{self._user_cache}")

        ctx_parts: list[str] = []
        if time_of_day:
            greeting = _TOD_GREETINGS.get(time_of_day.lower(), "")
            if greeting and user_name:
                ctx_parts.append(f"{greeting}, {user_name}.")
            elif greeting:
                ctx_parts.append(f"{greeting}.")
        elif user_name:
            ctx_parts.append(f"The user's name is {user_name}.")

        if recent_context:
            ctx_parts.append(f"Recent context: {recent_context}")

        if ctx_parts:
            parts.append("\n## Session Context\n" + " ".join(ctx_parts))

        parts.append(
            "\n## Voice Behaviour\n"
            "- Speak in short, natural sentences.\n"
            "- If the user interrupts, yield immediately and listen.\n"
            "- While processing a tool call, give a brief filler like "
            '"Hmm, let me check on that…" so there\'s no awkward silence.\n'
            "- Never read out raw JSON, code blocks, or URLs in full.\n"
            "- Summarise tool results in friendly language."
        )

        return "\n".join(parts)

    @staticmethod
    def get_interrupt_response() -> str:
        """Return a natural filler for when the user interrupts."""
        return random.choice(_INTERRUPT_RESPONSES)

    @staticmethod
    def get_thinking_filler() -> str:
        """Return a spoken filler for processing pauses."""
        return random.choice(_THINKING_FILLERS)

    @staticmethod
    def current_time_of_day() -> str:
        """Utility: determine time-of-day bucket from the local clock."""
        hour = time.localtime().tm_hour
        if 5 <= hour < 12:
            return "morning"
        if 12 <= hour < 17:
            return "afternoon"
        if 17 <= hour < 21:
            return "evening"
        return "night"
