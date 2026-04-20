"""
FERAL Matrix channel (Track A exemplar — stub).

This file ships the *shape* of a Matrix bridge so later contributors have
a concrete target. It deliberately does **not** fake a working
connection: without a homeserver URL + access token it reports honestly
that it is disabled, and without the ``matrix-nio`` dependency installed
it refuses to start.

Ship-ready checklist (follow-up PR — see `TRACK_A_CHANNELS_PROVIDERS.md`):
1. Add `matrix-nio>=0.24.0` to `feral-core/pyproject.toml` under a new
   ``[channel-matrix]`` extra.
2. Replace the stub ``start`` / ``send`` methods with the real
   ``nio.AsyncClient`` sync-loop + room send pattern.
3. Implement ``resolve_username`` so ``@alice:matrix.org`` resolves to a
   canonical user_id.
4. Add ``feral-core/tests/test_channel_matrix.py`` with a unit test for
   config parsing + a live round-trip test gated behind
   ``FERAL_LIVE_MATRIX_TEST=1``.
5. Publish a ``kind=channel`` registry seed via
   ``feral-registry/scripts/seed_matrix.py``.

Pattern reference: ``TelegramChannel`` (line 182 of
`feral-core/channels/base.py`) — follow its ``_poll_loop`` / event
handler / ``_emit_comms_event`` pattern, just swap HTTP polling for the
``matrix-nio`` sync stream.
"""

from __future__ import annotations

import logging
from typing import Optional

from channels.base import Channel, ChannelResponse

logger = logging.getLogger("feral.channels.matrix")


class MatrixChannel(Channel):
    """Matrix bridge — stub. See module docstring for ship-ready checklist.

    Expected config keys:
        homeserver    Full URL, e.g. "https://matrix.org".
        user_id       "@feral:matrix.org".
        access_token  Obtained via the Element / nio login flow.
        rooms         Optional list of room IDs to auto-join.
    """

    @property
    def channel_type(self) -> str:
        return "matrix"

    async def start(self) -> None:
        homeserver = self.config.get("homeserver")
        user_id = self.config.get("user_id")
        token = self.config.get("access_token")

        if not (homeserver and user_id and token):
            logger.warning(
                "Matrix channel not started: homeserver/user_id/access_token missing. "
                "Set them in ~/.feral/vault or the settings UI."
            )
            self._connected = False
            self._running = False
            return

        try:
            # Deferred import: keeps the optional dependency optional.
            import nio  # type: ignore  # noqa: F401
        except ImportError:
            logger.warning(
                "Matrix channel requires 'matrix-nio' — install via "
                "'pip install feral-ai[channel-matrix]'. Channel remains disabled."
            )
            self._connected = False
            self._running = False
            return

        # Full implementation deferred to the follow-up PR in TRACK_A.
        logger.info(
            "Matrix channel is at stub-level in this build. Full "
            "implementation lands with the Track A Matrix PR — see "
            "TRACK_A_CHANNELS_PROVIDERS.md."
        )
        self._connected = False
        self._running = False

    async def stop(self) -> None:
        self._running = False

    async def send(self, channel_id: str, response: ChannelResponse) -> None:
        logger.warning(
            "MatrixChannel.send called while stub is active — dropping "
            "message to %s (text=%r).",
            channel_id,
            (response.text or "")[:60],
        )

    async def resolve_username(self, handle: str) -> Optional[dict]:
        # Matrix handles are room-scoped user_ids. Real impl resolves via
        # /_matrix/client/v3/profile/{user_id}.
        return None
