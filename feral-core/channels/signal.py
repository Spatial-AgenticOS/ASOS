"""FERAL Signal channel (Track A stub).

Ships the shape of a Signal bridge so later contributors have a concrete
target. It deliberately does **not** fake a working connection: without
a ``signald`` or ``signal-cli`` endpoint configured, it reports honestly
that it is disabled.

Ship-ready checklist (follow-up PR):
1. Decide on the backend: ``signald`` JSON-socket daemon (cleaner
   surface, harder to deploy) or ``signal-cli`` (subprocess, easier).
   Add the chosen dep to a new ``[channel-signal]`` extra in
   ``feral-core/pyproject.toml``.
2. Implement ``start``: open the socket / spawn the CLI, subscribe to
   inbound envelopes, register the phone number.
3. Implement ``send``: map ``ChannelResponse.text`` (+ buttons / image
   attachments) to the chosen backend's outbound RPC.
4. Add ``feral-core/tests/test_channel_signal.py`` with a live test
   gated behind ``FERAL_LIVE_SIGNAL_TEST=1``.
5. Publish a ``kind=channel`` registry seed.

Pattern reference: ``TelegramChannel`` (line 182 of
``feral-core/channels/base.py``) — follow its ``_poll_loop`` /
``_emit_comms_event`` pattern, swapping HTTP polling for signald's
JSON-lines socket.
"""

from __future__ import annotations

import logging
from typing import Optional

from channels.base import Channel, ChannelResponse

logger = logging.getLogger("feral.channels.signal")


class SignalChannel(Channel):
    """Signal bridge — stub. See module docstring for ship-ready checklist."""

    @property
    def channel_type(self) -> str:
        return "signal"

    async def start(self) -> None:
        backend = self.config.get("backend", "signald")  # "signald" | "signal-cli"
        phone = self.config.get("phone_number")
        endpoint = self.config.get("endpoint")  # unix socket or TCP host:port

        if not phone or not endpoint:
            logger.warning(
                "Signal channel not started: phone_number/endpoint missing. "
                "Register with signald or signal-cli first, then set them in "
                "~/.feral/vault or the settings UI."
            )
            self._connected = False
            self._running = False
            return

        logger.info(
            "Signal channel (%s) is at stub-level in this build. Full "
            "implementation lands in a follow-up PR — see the module "
            "docstring for the ship-ready checklist.",
            backend,
        )
        self._connected = False
        self._running = False

    async def stop(self) -> None:
        self._running = False

    async def send(self, channel_id: str, response: ChannelResponse) -> None:
        logger.warning(
            "SignalChannel.send called while stub is active — dropping "
            "message to %s (text=%r).",
            channel_id,
            (response.text or "")[:60],
        )

    async def resolve_username(self, handle: str) -> Optional[dict]:
        # Signal recipients are E.164 phone numbers. Real impl normalises
        # "+1-415-555-0100" / "415-555-0100" / "alice" into a canonical
        # phone number via the configured address book.
        return None
