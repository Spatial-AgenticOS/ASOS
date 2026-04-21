"""Amazon Bedrock provider adapter (Track A stub).

AWS Bedrock multiplexes many upstream model families (Anthropic Claude,
Meta Llama, Mistral, Cohere, Amazon Titan, Stability) through a single
IAM-authenticated API. It does **not** expose a public ``/v1/models``
endpoint — model IDs ship hand-curated from
``providers/bedrock_models.json`` and are refreshed via ``boto3``'s
``bedrock.list_foundation_models`` call when credentials are present.

Track A status: the shape is production-ready but the live path needs
an AWS account with Bedrock access + the specific model IDs enabled in
the target region. Follow-up PR wires the live path once those are
provisioned.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("feral.providers.bedrock")

_CATALOG_FILE = Path(__file__).with_name("bedrock_models.json")


def _load_static_catalog() -> list[str]:
    try:
        return json.loads(_CATALOG_FILE.read_text()).get("models", [])
    except Exception as exc:
        logger.debug("bedrock static catalog missing: %s", exc)
        return []


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
    _capabilities = {"tool_calling"}

    def __init__(
        self,
        *,
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
    ) -> None:
        self._region = region or "us-east-1"
        self._access_key = aws_access_key_id
        self._secret_key = aws_secret_access_key
        self._session_token = aws_session_token

    def _boto_client(self, service: str):
        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "bedrock provider requires boto3 — install via "
                "`pip install feral-ai[bedrock]` before using it."
            ) from exc
        return boto3.client(
            service,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            aws_session_token=self._session_token,
        )

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
        raise RuntimeError(
            "bedrock provider is at stub level — follow-up PR wires "
            "bedrock-runtime.converse once an AWS account with Bedrock "
            "access is configured. See TRACK_A_CHANNELS_PROVIDERS.md."
        )

    async def refresh_models(self) -> list[str]:
        if not self._access_key:
            return list(self._models)
        try:
            client = self._boto_client("bedrock")
            resp = client.list_foundation_models()
            ids = [m["modelId"] for m in resp.get("modelSummaries", []) if "modelId" in m]
            if ids:
                self._models = sorted(ids)
        except Exception as exc:
            logger.debug("bedrock refresh_models failed: %s", exc)
        return list(self._models)
