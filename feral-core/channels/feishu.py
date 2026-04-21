"""FERAL Feishu / Lark channel (Track A stub).

Bidirectional bridge for Feishu (Lark outside mainland China). The bot
registers with ``open.feishu.cn`` / ``open.larksuite.com`` and receives
``im.message.receive_v1`` webhook events, then replies via the
``chat_id`` the event carried.

Ships the shape so later contributors have a concrete target. It
deliberately does **not** fake a connection: without an app_id +
app_secret + tenant access token, it reports honestly that it is
disabled.

Ship-ready checklist (follow-up PR — see `TRACK_A_CHANNELS_PROVIDERS.md`):
1. Add ``lark-oapi>=1.4`` (official SDK) to a new ``[channel-feishu]``
   extra in ``feral-core/pyproject.toml``.
2. Implement ``start``: fetch the tenant_access_token, mount the
   event-callback webhook under ``/channels/feishu/webhook`` + verify
   Feishu's encrypted challenge handshake.
3. Implement ``send``: use ``/im/v1/messages`` with
   ``receive_id_type=chat_id``, posting a ``text`` or ``interactive``
   (button-bearing) card.
4. Test gated behind ``FERAL_LIVE_FEISHU_TEST=1``.
5. Publish a ``kind=channel`` registry seed.

Pattern reference: the Slack / Discord path already in
``feral-core/channels/base.py`` is the closest shape — both use
callback-based event delivery over HTTPS + a REST send path.
"""

from __future__ import annotations

import logging
from typing import Optional

from channels.base import Channel, ChannelResponse

logger = logging.getLogger("feral.channels.feishu")


class FeishuChannel(Channel):
    """Feishu / Lark bridge — stub."""

    @property
    def channel_type(self) -> str:
        return "feishu"

    async def start(self) -> None:
        app_id = self.config.get("app_id")
        app_secret = self.config.get("app_secret")
        encrypt_key = self.config.get("encrypt_key")
        verification_token = self.config.get("verification_token")

        if not (app_id and app_secret and verification_token):
            logger.warning(
                "Feishu channel not started: app_id / app_secret / "
                "verification_token missing. Register an app at "
                "open.feishu.cn or open.larksuite.com first, then set "
                "credentials in ~/.feral/vault."
            )
            self._connected = False
            self._running = False
            return

        logger.info(
            "Feishu channel (encrypt_key=%s) is at stub-level in this build. "
            "Full implementation lands with the Track A Feishu PR — see "
            "TRACK_A_CHANNELS_PROVIDERS.md.",
            "set" if encrypt_key else "unset",
        )
        self._connected = False
        self._running = False

    async def stop(self) -> None:
        self._running = False

    async def send(self, channel_id: str, response: ChannelResponse) -> None:
        logger.warning(
            "FeishuChannel.send called while stub is active — dropping "
            "message to chat_id=%s (text=%r).",
            channel_id,
            (response.text or "")[:60],
        )

    async def resolve_username(self, handle: str) -> Optional[dict]:
        # Feishu users are resolvable by email, mobile, or open_id. Real
        # impl calls /contact/v3/users/batch_get_id.
        return None
