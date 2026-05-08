"""Pin the contract that ``ProviderCatalog.default_model_for`` never
returns a non-chat model id.

Operator report (2026-05-08): the catalog handed
``gpt-4o-mini-transcribe-2025-12-15`` out as the OpenAI default
model. ``LLMProvider`` then sent every chat completion to
``/v1/chat/completions`` with that model id and got back ``HTTP 404
— invalid_request_error: "This is not a chat model and thus not
supported in the v1/chat/completions endpoint"``. The bug was a
classifier hole: the dated-snapshot transcribe / tts / realtime
suffixes (``-2025-12-15`` etc.) didn't match the anchored regexes
in ``providers/model_classes.py``, so they fell through to the
chat catch-all ``^gpt-4o(-.+)?$`` and ranked first in the
chat-class shortlist.

This test pins the end-to-end contract: feed the catalog the
real OpenAI ``/v1/models`` fixture and assert the picked default
classifies as ``chat`` or ``reasoning`` (a strict subset of chat
for routing purposes). A regression of the classifier OR the
catalog's filter ordering OR the recommended shortlist would all
fail this test.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from providers.catalog import CachedModelList, get_shared_catalog
from providers.model_classes import classify


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "openai_models.json"


def _seed_openai_catalog(model_ids: list[str]) -> None:
    cat = get_shared_catalog()
    cat._models["openai"] = CachedModelList(
        models=model_ids,
        last_refresh=time.time(),
        source="live",
    )


def _all_openai_ids() -> list[str]:
    payload = json.loads(_FIXTURE.read_text())
    return [m["id"] for m in payload["data"]]


def test_default_openai_model_is_chat_or_reasoning() -> None:
    """The catalog's default for OpenAI must be usable on /chat/completions."""
    ids = _all_openai_ids()
    _seed_openai_catalog(ids)
    cat = get_shared_catalog()
    pick = cat.default_model_for("openai")
    assert pick, "catalog returned an empty default model id for openai"
    cls = classify("openai", pick)
    assert cls in {"chat", "reasoning"}, (
        f"ProviderCatalog.default_model_for('openai') picked {pick!r} "
        f"which classifies as {cls!r}. Sending that to "
        f"/v1/chat/completions returns HTTP 404 invalid_request_error. "
        "Likely a classifier regression in providers/model_classes.py "
        "(check the dated-snapshot tail on transcribe/tts/realtime "
        "regexes) or a recommended-list ordering regression in "
        "providers/recommended.py."
    )


def test_dated_transcribe_alongside_chat_does_not_outrank_chat() -> None:
    """When both dated transcribe AND chat models exist, chat wins.

    This is the realistic regression case: OpenAI's live ``/v1/models``
    response always contains both. Before the 2026-05-08 classifier
    fix, ``gpt-4o-mini-transcribe-2025-12-15`` was misclassified as
    ``chat`` and could outrank real chat models in the
    ``filter_models(model_class="chat")`` ordering. With the fix, the
    transcribe ids are correctly ``audio`` and never appear in
    ``chat_only``.
    """
    mixed = [
        # Dated transcribe / tts ids (must NOT be chat)
        "gpt-4o-mini-transcribe-2025-12-15",
        "gpt-4o-transcribe-diarize-2025-12-15",
        "gpt-4o-mini-tts-2025-12-15",
        # Real chat ids
        "gpt-4o",
        "gpt-4.1",
        # Real reasoning ids
        "gpt-5",
        "gpt-5.5",
    ]
    _seed_openai_catalog(mixed)
    cat = get_shared_catalog()
    pick = cat.default_model_for("openai")
    cls = classify("openai", pick)
    assert cls in {"chat", "reasoning"}, (
        f"Mixed fixture (chat + dated transcribe) defaulted to "
        f"{pick!r} ({cls!r}). The chat-class filter should outrank "
        f"audio/realtime variants. Either the classifier or "
        f"recommended_for ordering regressed."
    )


def test_dated_realtime_does_not_default_for_chat() -> None:
    """The realtime preview ids must be classified as ``realtime``, not ``chat``."""
    realtime_ids = [
        "gpt-realtime",
        "gpt-realtime-1.5",
        "gpt-4o-realtime-preview",
        "gpt-4o-realtime-preview-2024-12-17",
    ]
    for mid in realtime_ids:
        cls = classify("openai", mid)
        assert cls == "realtime", (
            f"{mid!r} classified as {cls!r} instead of 'realtime'. "
            "Dated-snapshot tail likely missing from the realtime regex "
            "in providers/model_classes.py."
        )
