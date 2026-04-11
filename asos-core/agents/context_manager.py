"""
Context window management for the THEORA orchestrator.

Handles conversation history compaction and message truncation
to keep the LLM context within token budgets.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("theora.orchestrator.context")


class ContextManager:
    """Manages conversation history size and compaction."""

    def __init__(self, max_messages: int = 15):
        self.max_messages = max_messages

    def compact(self, history: list[dict]) -> list[dict]:
        """Trim history to the most recent *max_messages* entries."""
        if len(history) <= self.max_messages:
            return history
        logger.info(
            "Compacting context window from %d to %d",
            len(history),
            self.max_messages,
        )
        return history[-self.max_messages:]
