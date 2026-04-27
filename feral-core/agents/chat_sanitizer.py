"""
Outbound chat text sanitizer.

Strips control-token residue and mimicked tool syntax from assistant
text before it reaches the WebSocket. Shared by the streaming path,
the non-stream failover path, and any caller that forwards model text
directly to the UI. Kept deliberately narrow: this is a display-layer
scrubber, not a parser — we preserve ordinary prose untouched.

Targets drawn from A1 audit of leaked artifacts:
  * ``<|eom|>`` and other ``<|...|>`` sentinels (Llama-family, OpenAI
    chat markup that occasionally escapes the SSE boundary).
  * XML-ish tool envelopes: ``<tool_calls>...</tool_calls>``,
    ``<function_call>...</function_call>``, ``<tool_use>...</tool_use>``,
    ``<tool_result>...</tool_result>``.
  * Dangling closing tags (``</tool_calls>`` etc.) without an opener
    — models often emit only the tail when the stream is chunked.
  * ``invoke[...]`` blobs Claude-format mimics sometimes print.
  * Trailing ``FUNCTION`` / ``TOOLS`` marker lines from instruction-
    tuned local models.
"""

from __future__ import annotations

import re

_SENTINEL_RE = re.compile(r"<\|[^|>\s][^|>]*\|>")

_TOOL_TAG_NAMES = (
    "tool_calls",
    "tool_call",
    "function_call",
    "function_calls",
    "tool_use",
    "tool_result",
    "tools",
)

_TOOL_BLOCK_RE = re.compile(
    r"<\s*(?P<tag>" + "|".join(_TOOL_TAG_NAMES) + r")\b[^>]*>.*?</\s*(?P=tag)\s*>",
    re.DOTALL | re.IGNORECASE,
)

_ORPHAN_CLOSE_RE = re.compile(
    r"</\s*(?:" + "|".join(_TOOL_TAG_NAMES) + r")\s*>",
    re.IGNORECASE,
)

_ORPHAN_OPEN_RE = re.compile(
    r"<\s*(?:" + "|".join(_TOOL_TAG_NAMES) + r")\b[^>]*/?>",
    re.IGNORECASE,
)

_INVOKE_BLOCK_RE = re.compile(
    r"\binvoke\s*\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]",
    re.IGNORECASE | re.DOTALL,
)

_TRAILING_MARKER_RE = re.compile(
    r"(?:^|\s)(?:FUNCTION|FUNCTIONS|TOOL|TOOLS)\s*$",
)


def sanitize_assistant_display_text(text: str) -> str:
    """Remove control-token residue and mimicked tool syntax from *text*.

    Safe for streaming chunks: run it on every text_delta piece. We
    never invent new content, only strip recognized residue. If the
    text contains nothing but residue the return value is ``""`` and
    callers should skip sending an empty delta.
    """
    if not text:
        return text

    cleaned = _TOOL_BLOCK_RE.sub("", text)
    cleaned = _INVOKE_BLOCK_RE.sub("", cleaned)
    cleaned = _ORPHAN_CLOSE_RE.sub("", cleaned)
    cleaned = _ORPHAN_OPEN_RE.sub("", cleaned)
    cleaned = _SENTINEL_RE.sub("", cleaned)
    cleaned = _TRAILING_MARKER_RE.sub("", cleaned)

    return cleaned


__all__ = ["sanitize_assistant_display_text"]
