"""First-time pairing helpers for HUP v1 daemons.

Implements the client side of the 6-digit-code flow described in
`HUP_SPEC.md` §4.1: generate a code, poll the brain's pair-status endpoint
until the user types the code, then persist the returned API key to
``~/.feral/node-keys/<node_id>.key`` with mode 0600.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import ssl
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("feral_node_sdk.pairing")

KEYS_DIR = Path.home() / ".feral" / "node-keys"


def _key_path(node_id: str) -> Path:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in node_id if c.isalnum() or c in "._-:")
    return KEYS_DIR / f"{safe}.key"


def load_key(node_id: str) -> Optional[str]:
    p = _key_path(node_id)
    if not p.exists():
        return None
    return p.read_text().strip() or None


def save_key(node_id: str, api_key: str) -> Path:
    p = _key_path(node_id)
    p.write_text(api_key.strip() + "\n")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def generate_code() -> str:
    """Generate a cryptographically-random 6-digit pairing code (leading zeros preserved)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _http_base(brain_url: str) -> str:
    u = brain_url
    if u.startswith("wss://"):
        u = "https://" + u[len("wss://"):]
    elif u.startswith("ws://"):
        u = "http://" + u[len("ws://"):]
    if "/v1/node" in u:
        u = u.split("/v1/node", 1)[0]
    return u.rstrip("/")


async def pair(
    node_id: str,
    brain_url: str,
    *,
    name: str = "",
    code: Optional[str] = None,
    poll_interval_s: float = 2.0,
    timeout_s: float = 300.0,
    verify_tls: bool = True,
) -> str:
    """Run the interactive 6-digit pairing flow and return the API key.

    Prints the pairing code to stdout so the user can type it into
    the FERAL UI. Blocks until the brain confirms or `timeout_s` elapses.
    """
    code = code or generate_code()
    base = _http_base(brain_url)
    print(f"\n  FERAL pairing code: {code[:3]} {code[3:]}\n")
    print("  → Open FERAL → Settings → Devices → Pair and enter the code.")
    print(f"  (Will wait up to {int(timeout_s)}s against {base}…)\n")

    ctx: Optional[ssl.SSLContext] = None
    if base.startswith("https://") and not verify_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s

    def _poll() -> Optional[str]:
        url = f"{base}/api/devices/pair/status?code={code}&node_id={node_id}"
        try:
            with urllib.request.urlopen(url, timeout=5, context=ctx) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "paired" and data.get("token"):
                    return str(data["token"])
        except Exception as exc:
            logger.debug("pair-status poll failed: %s", exc)
        return None

    def _announce() -> None:
        url = f"{base}/api/devices/pair/announce"
        body = json.dumps({"code": code, "node_id": node_id, "name": name or node_id}).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5, context=ctx).read()
        except Exception as exc:
            logger.debug("pair-announce failed (non-fatal): %s", exc)

    await loop.run_in_executor(None, _announce)

    while loop.time() < deadline:
        token = await loop.run_in_executor(None, _poll)
        if token:
            save_key(node_id, token)
            print(f"  ✓ Paired. API key saved to {_key_path(node_id)}")
            return token
        await asyncio.sleep(poll_interval_s)

    raise TimeoutError("Pairing timed out; ask the user to try again.")
