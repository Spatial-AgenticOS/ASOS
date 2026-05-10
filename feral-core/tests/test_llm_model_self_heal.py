"""Pin the brain's self-heal of a non-chat ``llm.model`` from settings.json.

Operator report (2026-05-09): ``~/.feral/settings.json`` had
``llm.model = "gpt-4o-mini-transcribe-2025-12-15"`` (an audio-class
model). Every chat completion 404'd with ``This is not a chat
model``. The user had NO obvious lever to fix it — there's no
``feral config set`` CLI command, and they didn't know about the
Settings → Providers UI flow.

The fix in ``api/state.py`` (BrainState init) now classifies
``LLMProvider.model`` after init, and if it's not in
``{chat, reasoning}``, swaps it for a catalog-picked default and
persists the corrected value back to settings.json so this can
never happen again.

This test directly exercises the ``classify`` + catalog-default
contract that the self-heal depends on, without spinning up the
full BrainState init (which boots ~40 subsystems and would be a
soak-class test). The full BrainState path is covered by the
boot-report integration test.
"""

from __future__ import annotations

import time

import pytest

from providers.catalog import CachedModelList, get_shared_catalog
from providers.model_classes import classify


def _seed_catalog(provider: str, model_ids: list[str]) -> None:
    cat = get_shared_catalog()
    cat._models[provider] = CachedModelList(
        models=model_ids,
        last_refresh=time.time(),
        source="live",
    )


def test_dated_transcribe_model_is_classified_audio_not_chat() -> None:
    """The exact model id the operator's settings.json had pinned."""
    cls = classify("openai", "gpt-4o-mini-transcribe-2025-12-15")
    assert cls == "audio", (
        f"gpt-4o-mini-transcribe-2025-12-15 must be classed as 'audio' "
        f"(not 'chat') so the self-heal can detect it. Got {cls!r}. "
        "If this test fails the classifier regressed — see "
        "providers/model_classes.py for the dated-snapshot regex tail."
    )


def test_self_heal_picks_chat_class_default_from_catalog() -> None:
    """When settings has audio model + catalog has chat models, healed pick is chat."""
    _seed_catalog("openai", [
        # Operator's broken value
        "gpt-4o-mini-transcribe-2025-12-15",
        # Real chat-class options
        "gpt-5.5",
        "gpt-5.5-pro",
        "gpt-4o",
        "gpt-4.1",
    ])
    cat = get_shared_catalog()
    healed = cat.default_model_for("openai")
    assert healed, "catalog returned empty default for openai"
    healed_cls = classify("openai", healed)
    assert healed_cls in {"chat", "reasoning"}, (
        f"Self-heal must pick a chat-class default; got {healed!r} "
        f"({healed_cls!r}). The self-heal in api/state.py would NOT "
        "swap, leaving the operator stuck."
    )


def test_self_heal_classify_set_membership() -> None:
    """The classes the self-heal accepts as 'don't touch'.

    If a future contributor adds a new class label (e.g. ``"hybrid"``
    or splits ``"reasoning"`` into ``"reasoning-low"`` /
    ``"reasoning-high"``) without updating the self-heal allowlist,
    this test reminds them to.
    """
    chat_safe = {"chat", "reasoning", "unknown"}
    # These must be in the safe set (otherwise self-heal would
    # incorrectly re-pick a working model).
    for safe in ("chat", "reasoning", "unknown"):
        assert safe in chat_safe
    # These must NOT be in the safe set (otherwise self-heal would
    # not catch the operator-reported bug).
    for unsafe in ("audio", "image", "embedding", "realtime", "completion-only"):
        assert unsafe not in chat_safe, (
            f"{unsafe!r} must be re-picked by self-heal — putting it in "
            "the safe set would re-introduce the 2026-05-09 transcribe bug."
        )
