"""FERAL Voice-Call channel (Track A stub).

A "channel" whose underlying transport is a phone call, brokered through
Twilio Voice (or a compatible provider like Vonage / Plivo / Telnyx).
Inbound: provider webhook → STT → brain → TTS → TwiML reply.
Outbound: brain pushes text, channel synthesises TTS and dials.

Ships the shape so later contributors have a concrete target. It
deliberately does **not** fake a working call: without a Twilio auth
token + verified number + public webhook URL, it reports honestly that
it is disabled.

Ship-ready checklist (follow-up PR — see `TRACK_A_CHANNELS_PROVIDERS.md`):
1. Add ``twilio>=9.0`` to a ``[channel-voice-call]`` extra in
   ``feral-core/pyproject.toml``.
2. Implement ``start``: boot a small ASGI app that Twilio POSTs to;
   mount at ``/channels/voice_call/webhook`` inside the Brain router.
3. Implement ``send``: use Twilio's REST to place an outbound call with
   a dynamic TwiML URL that speaks the response text.
4. Test gated behind ``FERAL_LIVE_VOICE_CALL_TEST=1`` — uses a pair of
   Twilio test numbers.
5. Publish a ``kind=channel`` registry seed.

Pattern reference: the existing push/webhook wiring in
``feral-core/api/routes/webhooks.py`` for the inbound side; TelegramBot
for outbound-send semantics.
"""

from __future__ import annotations

import logging
from typing import Optional

from channels.base import Channel, ChannelResponse

logger = logging.getLogger("feral.channels.voice_call")


class VoiceCallChannel(Channel):
    """Voice-call bridge — stub. See module docstring for ship-ready checklist."""

    @property
    def channel_type(self) -> str:
        return "voice_call"

    async def start(self) -> None:
        provider = self.config.get("provider", "twilio")
        account_sid = self.config.get("account_sid")
        auth_token = self.config.get("auth_token")
        from_number = self.config.get("from_number")
        webhook_url = self.config.get("webhook_url")

        if not (account_sid and auth_token and from_number and webhook_url):
            logger.warning(
                "Voice-call channel not started: provider credentials "
                "(account_sid/auth_token/from_number/webhook_url) missing. "
                "Set them in ~/.feral/vault or the settings UI."
            )
            self._connected = False
            self._running = False
            return

        logger.info(
            "Voice-call channel (%s) is at stub-level in this build. Full "
            "implementation lands with the Track A Voice-Call PR — see "
            "TRACK_A_CHANNELS_PROVIDERS.md.",
            provider,
        )
        self._connected = False
        self._running = False

    async def stop(self) -> None:
        self._running = False

    async def send(self, channel_id: str, response: ChannelResponse) -> None:
        logger.warning(
            "VoiceCallChannel.send called while stub is active — would "
            "place an outbound call to %s with text=%r.",
            channel_id,
            (response.text or "")[:60],
        )

    async def resolve_username(self, handle: str) -> Optional[dict]:
        # A voice-call recipient is an E.164 phone number.
        return None
