"""Amazon Bedrock provider adapter — live Converse implementation.

AWS Bedrock multiplexes many upstream model families (Anthropic Claude,
Meta Llama, Mistral, Cohere, Amazon Titan, Stability) through a single
IAM-authenticated API. It does **not** expose a public ``/v1/models``
endpoint — model IDs ship hand-curated from
``providers/bedrock_models.json`` and are refreshed via ``boto3``'s
``bedrock.list_foundation_models`` call when credentials are present.

This adapter speaks the **Bedrock Converse API** (``bedrock-runtime``
client, ``converse`` + ``converse_stream``). The Converse API
normalises the request and response shapes across model families so we
do NOT have to hand-craft per-family prompts (the older
``invoke_model`` path required that and is a permanent footgun — see
https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html
for context).

audit-r12 D8 ("Bedrock provider chat() is a stub") is fixed by this
module — :meth:`BedrockProvider.chat` now performs a real Converse
round-trip; :meth:`BedrockProvider.stream_chat` performs a real
``converse_stream``; :meth:`BedrockProvider.validate_credentials` does
a cheap pre-flight so the setup wizard refuses to persist
credentials that don't actually work (mirrors the D4 fail-loud rule).

Embeddings: Bedrock embeddings live on a separate API surface
(``invoke_model`` against ``amazon.titan-embed-*`` or
``cohere.embed-*``). They are not exposed here — embedding providers
ship through :mod:`memory.embeddings` and are an orthogonal axis. The
adapter advertises ``supports("embeddings")`` as ``False`` so the
catalog renders the right capability chip.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("feral.providers.bedrock")

_CATALOG_FILE = Path(__file__).with_name("bedrock_models.json")


def _load_static_catalog() -> list[str]:
    try:
        return json.loads(_CATALOG_FILE.read_text()).get("models", [])
    except Exception as exc:
        logger.debug("bedrock static catalog missing: %s", exc)
        return []


def _messages_to_converse(messages: list[ChatMessage]) -> tuple[list[dict], list[dict]]:
    """Translate FERAL :class:`ChatMessage` objects to the Converse
    request shape.

    Converse separates the system prompt (``system=[{text}]``) from the
    user/assistant conversation (``messages=[{role, content}]``); each
    content block is itself a list so a single message can carry text,
    images, and tool results.

    Returns ``(messages, system_blocks)``.
    """
    converse_messages: list[dict[str, Any]] = []
    system_blocks: list[dict[str, str]] = []
    for msg in messages:
        if msg.role == "system":
            if msg.content:
                system_blocks.append({"text": msg.content})
            continue
        # Converse only knows "user" and "assistant" for the messages
        # array; map "tool" results back to a user-role toolResult
        # content block. This mirrors what the AWS SDK examples do.
        role = "assistant" if msg.role == "assistant" else "user"
        content_blocks: list[dict[str, Any]] = []
        if msg.role == "tool":
            content_blocks.append(
                {
                    "toolResult": {
                        # ``msg.name`` carries the tool_use id by
                        # convention (orchestrator already populates it
                        # for OpenAI/Anthropic).
                        "toolUseId": msg.name or "",
                        "content": [{"text": msg.content}],
                    }
                }
            )
        else:
            if msg.content:
                content_blocks.append({"text": msg.content})
            for tc in msg.tool_calls or []:
                content_blocks.append(
                    {
                        "toolUse": {
                            "toolUseId": tc.get("id") or tc.get("toolUseId") or "",
                            "name": tc.get("name") or tc.get("function", {}).get("name", ""),
                            "input": tc.get("input")
                            or tc.get("arguments")
                            or tc.get("function", {}).get("arguments", {}),
                        }
                    }
                )
        converse_messages.append({"role": role, "content": content_blocks})
    return converse_messages, system_blocks


def _tools_to_converse(tools: Optional[list[dict[str, Any]]]) -> Optional[dict[str, Any]]:
    """Translate the orchestrator's tool-call definitions (OpenAI-style)
    to the Converse ``toolConfig`` shape. Returns ``None`` when no
    tools are supplied so we don't send an empty toolConfig (Bedrock
    400s on that)."""
    if not tools:
        return None
    spec_list: list[dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function") or tool
        name = fn.get("name")
        if not name:
            continue
        spec_list.append(
            {
                "toolSpec": {
                    "name": name,
                    "description": fn.get("description", ""),
                    "inputSchema": {
                        # Converse wraps the JSON schema under a `json`
                        # key per the AWS docs.
                        "json": fn.get("parameters") or fn.get("inputSchema") or {"type": "object"},
                    },
                }
            }
        )
    if not spec_list:
        return None
    return {"tools": spec_list}


def _converse_response_to_chat_response(
    resp: dict[str, Any], *, model: str,
) -> ChatResponse:
    """Translate the Converse JSON response to FERAL's
    :class:`ChatResponse`. Concatenates all text content blocks into
    ``text`` and collects any ``toolUse`` blocks into ``tool_calls``
    so the orchestrator's tool-loop sees the same shape it gets from
    OpenAI/Anthropic."""
    output = resp.get("output") or {}
    message = output.get("message") or {}
    content_blocks: list[dict[str, Any]] = message.get("content") or []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content_blocks:
        if "text" in block:
            text_parts.append(block["text"])
        elif "toolUse" in block:
            tu = block["toolUse"]
            tool_calls.append(
                {
                    "id": tu.get("toolUseId"),
                    "name": tu.get("name"),
                    "input": tu.get("input"),
                }
            )
    usage = resp.get("usage") or {}
    return ChatResponse(
        text="".join(text_parts),
        model=model,
        usage={
            "input_tokens": int(usage.get("inputTokens") or 0),
            "output_tokens": int(usage.get("outputTokens") or 0),
            "total_tokens": int(usage.get("totalTokens") or 0),
        },
        finish_reason=str(resp.get("stopReason") or "stop"),
        tool_calls=tool_calls,
    )


class BedrockProvider(BaseProvider):
    provider_id = "bedrock"
    display_name = "Amazon Bedrock"

    _models: list[str] = _load_static_catalog() or [
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "meta.llama3-1-70b-instruct-v1:0",
        "mistral.mistral-large-2407-v1:0",
        "amazon.titan-text-premier-v1:0",
    ]
    _pricing: dict[str, dict[str, float]] = {}
    # Converse supports tool calling for the model families we ship in
    # the catalog (Anthropic, Meta, Mistral, Cohere). Streaming via
    # ``converse_stream`` is also available across the same set.
    _capabilities = {"tool_calling", "streaming"}

    # audit-r12 D8: chat is now live. The truthfulness hint stays
    # ``True`` so the catalog renders the "ready" chip; the wizard
    # gates persistence on :meth:`validate_credentials` instead.
    chat_ready: bool = True
    stub_reason: str = ""

    def __init__(
        self,
        *,
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
    ) -> None:
        # Honour the standard AWS env vars so an operator with
        # ``~/.aws/credentials`` or an EC2/ECS role gets picked up
        # automatically — explicit kwargs only override.
        self._region = (
            region
            or os.environ.get("BEDROCK_REGION")
            or os.environ.get("AWS_REGION")
            or "us-east-1"
        )
        self._access_key = aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")
        self._secret_key = (
            aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
        )
        self._session_token = (
            aws_session_token or os.environ.get("AWS_SESSION_TOKEN")
        )
        self._runtime_client: Any = None
        self._control_client: Any = None

    # ─────────────────────────────────────────────
    # Internal client construction
    # ─────────────────────────────────────────────

    def _boto_client(self, service: str):
        """Build a boto3 client for ``service``.

        Cached per-service on the instance so a long-running brain
        doesn't pay the ``boto3.client(...)`` construction cost on
        every request (it imports botocore session data lazily; the
        first call is ~100ms, subsequent calls are <1ms).

        Raises ``RuntimeError`` if ``boto3`` is not installed —
        actionable extras hint per the audit-r12 fail-loud rule.
        """
        cached = (
            self._runtime_client if service == "bedrock-runtime"
            else self._control_client if service == "bedrock"
            else None
        )
        if cached is not None:
            return cached
        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "bedrock provider requires boto3 — install via "
                "`pip install feral-ai[bedrock]` before using it."
            ) from exc
        client = boto3.client(
            service,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            aws_session_token=self._session_token,
        )
        if service == "bedrock-runtime":
            self._runtime_client = client
        elif service == "bedrock":
            self._control_client = client
        return client

    # ─────────────────────────────────────────────
    # Live chat / stream / validate
    # ─────────────────────────────────────────────

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Run a single Converse turn against Bedrock and return the
        normalised :class:`ChatResponse`.

        boto3's client is sync; we shell out to a worker thread via
        :func:`asyncio.to_thread` so we don't block the FERAL event
        loop. Failures surface as ``RuntimeError`` (so the orchestrator's
        provider-degrade path catches them and tries a fallback model)
        with the underlying ``boto`` error string in the message.
        """
        converse_messages, system_blocks = _messages_to_converse(messages)
        request: dict[str, Any] = {
            "modelId": model,
            "messages": converse_messages,
        }
        if system_blocks:
            request["system"] = system_blocks
        inference: dict[str, Any] = {}
        if max_tokens is not None:
            inference["maxTokens"] = int(max_tokens)
        if temperature is not None:
            inference["temperature"] = float(temperature)
        if inference:
            request["inferenceConfig"] = inference
        tool_config = _tools_to_converse(tools)
        if tool_config is not None:
            request["toolConfig"] = tool_config

        try:
            client = self._boto_client("bedrock-runtime")
            response = await asyncio.to_thread(client.converse, **request)
        except RuntimeError:
            raise
        except Exception as exc:
            # Surface AWS errors as RuntimeError so the orchestrator's
            # provider-fallback layer can degrade gracefully. The
            # original error stays in the chain for log forensics.
            raise RuntimeError(f"bedrock converse failed: {exc}") from exc

        return _converse_response_to_chat_response(response, model=model)

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Run a streaming Converse turn. Yields text deltas as the
        model produces them; tool-use blocks are aggregated and
        discarded (callers that need tool calls should use
        :meth:`chat` which surfaces them in ``ChatResponse.tool_calls``).

        ``converse_stream`` returns an iterator of events; we shell out
        to a worker thread to consume each event (boto3's event
        iterator is sync). The generator yields after each event so
        the event loop stays responsive.
        """
        converse_messages, system_blocks = _messages_to_converse(messages)
        request: dict[str, Any] = {
            "modelId": model,
            "messages": converse_messages,
        }
        if system_blocks:
            request["system"] = system_blocks
        inference: dict[str, Any] = {}
        if max_tokens is not None:
            inference["maxTokens"] = int(max_tokens)
        if temperature is not None:
            inference["temperature"] = float(temperature)
        if inference:
            request["inferenceConfig"] = inference
        tool_config = _tools_to_converse(tools)
        if tool_config is not None:
            request["toolConfig"] = tool_config

        client = self._boto_client("bedrock-runtime")

        def _open_stream() -> Any:
            return client.converse_stream(**request)

        try:
            response = await asyncio.to_thread(_open_stream)
        except Exception as exc:
            raise RuntimeError(f"bedrock converse_stream failed: {exc}") from exc

        stream = response.get("stream") if isinstance(response, dict) else response

        async def _gen() -> AsyncIterator[str]:
            if stream is None:
                return
            iterator = iter(stream)
            sentinel = object()
            while True:
                event = await asyncio.to_thread(next, iterator, sentinel)
                if event is sentinel:
                    return
                if not isinstance(event, dict):
                    continue
                delta_evt = event.get("contentBlockDelta")
                if delta_evt:
                    delta = delta_evt.get("delta") or {}
                    if "text" in delta:
                        yield delta["text"]

        return _gen()

    async def validate_credentials(self) -> bool:
        """Cheap pre-flight: list a single foundation model.

        Used by the setup wizard (and by anything else that needs a
        loud-fail before persisting credentials, per the audit-r12 D4
        rule). Returns ``True`` if the credentials authenticate AND
        the principal has at least one Bedrock entitlement in the
        configured region; ``False`` otherwise.
        """
        try:
            client = self._boto_client("bedrock")
        except Exception as exc:
            logger.warning("bedrock validate_credentials: client init failed (%s)", exc)
            return False
        try:
            await asyncio.to_thread(client.list_foundation_models)
            return True
        except Exception as exc:
            logger.info("bedrock validate_credentials: list_foundation_models failed (%s)", exc)
            return False

    async def refresh_models(self) -> list[str]:
        if not self._access_key and not os.environ.get("AWS_ACCESS_KEY_ID"):
            return list(self._models)
        try:
            client = self._boto_client("bedrock")
            resp = await asyncio.to_thread(client.list_foundation_models)
            ids = [m["modelId"] for m in resp.get("modelSummaries", []) if "modelId" in m]
            if ids:
                self._models = sorted(ids)
        except Exception as exc:
            logger.debug("bedrock refresh_models failed: %s", exc)
        return list(self._models)
