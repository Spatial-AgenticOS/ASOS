"""mDNS / Zeroconf discovery of FERAL brains on the local network.

Brains advertise `_feral-brain._tcp.local.` with TXT records (see
`HUP_SPEC.md` §4.3). This module returns a ready-to-use `wss://.../v1/node`
URL or `None` if no brain is found within `timeout_s`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("feral_node_sdk.discovery")

SERVICE_TYPE = "_feral-brain._tcp.local."


async def discover_brain(timeout_s: float = 3.0) -> Optional[str]:
    """Resolve the first FERAL brain advertised via mDNS.

    Returns a `wss://host:port/v1/node` URL, or `None` if nothing answered
    within `timeout_s`. Requires the `zeroconf` dependency; falls back to
    `None` gracefully if it cannot be imported.
    """
    try:
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
        from zeroconf import ServiceStateChange
    except Exception as exc:  # pragma: no cover - optional dep path
        logger.debug("zeroconf not available: %s", exc)
        return None

    found: asyncio.Future[Optional[str]] = asyncio.get_event_loop().create_future()

    def _on_change(zc, service_type, name, state_change):
        if state_change != ServiceStateChange.Added:
            return

        async def _resolve():
            info = await zc.async_get_service_info(service_type, name)
            if not info or found.done():
                return
            host = None
            for addr in info.parsed_addresses():
                host = addr
                break
            if not host:
                return
            port = info.port or 9090
            txt = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in (info.properties or {}).items()
            }
            path = txt.get("node_path", "/v1/node") or "/v1/node"
            scheme = "wss" if txt.get("tls", "1") not in ("0", "false") else "ws"
            url = f"{scheme}://{host}:{port}{path}"
            if not found.done():
                found.set_result(url)

        asyncio.ensure_future(_resolve())

    azc = AsyncZeroconf()
    browser = AsyncServiceBrowser(azc.zeroconf, [SERVICE_TYPE], handlers=[_on_change])
    try:
        return await asyncio.wait_for(found, timeout=timeout_s)
    except asyncio.TimeoutError:
        return None
    finally:
        await browser.async_cancel()
        await azc.async_close()
