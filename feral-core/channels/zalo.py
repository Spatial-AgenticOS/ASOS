"""FERAL Zalo channel (Track A stub).

Bidirectional bridge for the Zalo Official Account (OA) platform,
covering the Vietnamese market.

Ships the shape so later contributors have a concrete target. It
deliberately does **not** fake a connection: without an OA access
token, it reports honestly that it is disabled.

Ship-ready checklist (follow-up PR — see `TRACK_A_CHANNELS_PROVIDERS.md`):
1. Add ``httpx`` is already a dep; the Zalo REST API is plain HTTPS so
   no SDK bump is required. Add a ``[channel-zalo]`` extra only if a
   webhook framework is needed beyond the Brain's existing router.
2. Implement ``start``: verify the OA access token against
   ``openapi.zalo.me``, mount the webhook under
   ``/channels/zalo/webhook``.
3. Implement ``send``: use ``oa.message`` to post text + quick_reply
   buttons back to the user.
4. Test gated behind ``FERAL_LIVE_ZALO_TEST=1``.
5. Publish a ``kind=channel`` registry seed.

Pattern reference: the WhatsApp Business path in
``feral-core/channels/base.py`` — both use REST send with an access
token and callback-based inbound delivery.
"""

from __future__ import annotations

import logging
from typing import Optional

from channels.base import Channel, ChannelResponse

logger = logging.getLogger("feral.channels.zalo")


class ZaloChannel(Channel):
    """Zalo OA bridge — stub."""

    @property
    def channel_type(self) -> str:
        return "zalo"

    async def start(self) -> None:
        oa_access_token = self.config.get("oa_access_token")
        app_secret = self.config.get("app_secret")

        if not oa_access_token:
            logger.warning(
                "Zalo channel not started: oa_access_token missing. "
                "Obtain one from the Zalo OA admin console and store "
                "it in ~/.feral/vault."
            )
            self._connected = False
            self._running = False
            return

        logger.info(
            "Zalo channel (app_secret=%s) is at stub-level in this build. "
            "Full implementation lands with the Track A Zalo PR — see "
            "TRACK_A_CHANNELS_PROVIDERS.md.",
            "set" if app_secret else "unset",
        )
        self._connected = False
        self._running = False

    async def stop(self) -> None:
        self._running = False

    async def send(self, channel_id: str, response: ChannelResponse) -> None:
        logger.warning(
            "ZaloChannel.send called while stub is active — dropping "
            "message to user_id=%s (text=%r).",
            channel_id,
            (response.text or "")[:60],
        )

    async def resolve_username(self, handle: str) -> Optional[dict]:
        # Zalo recipients are user_ids issued by the platform; no
        # @-handle resolution exists on the public API.
        return None
