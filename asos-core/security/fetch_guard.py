"""
THEORA Fetch Guard
Prevents SSRF by blocking requests to private/internal networks.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]
ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_RESPONSE_SIZE = 10 * 1024 * 1024


def _ip_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(addr.version == n.version and addr in n for n in BLOCKED_IP_RANGES)


def validate_url(url: str) -> tuple[bool, str]:
    try:
        p = urlparse(url)
    except Exception as e:  # noqa: BLE001
        return False, f"Invalid URL: {e}"
    if p.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"URL scheme not allowed (got {p.scheme!r})"
    host = p.hostname
    if not host:
        return False, "URL has no host"
    hl = host.lower()
    if hl == "localhost" or hl.endswith(".local"):
        return False, "Hostname is not allowed"
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    if not infos:
        return False, "Could not resolve host"
    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _ip_blocked(ip_obj):
            return False, f"Host resolves to a blocked address: {ip_obj}"
    return True, ""


def html_to_markdown(html: str) -> str:
    try:
        import html2text

        h = html2text.HTML2Text()
        h.ignore_links = False
        h.body_width = 0
        return h.handle(html)
    except ImportError:
        t = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        t = re.sub(r"<style[^>]*>.*?</style>", "", t, flags=re.DOTALL | re.IGNORECASE)
        t = re.sub(r"<[^>]+>", " ", t)
        return re.sub(r"\s+", " ", t).strip()


def _fail(
    err: str,
    *,
    code: int = 0,
    ctype: str = "",
) -> dict[str, Any]:
    return {"success": False, "content": "", "content_type": ctype, "status_code": code, "error": err}


async def safe_fetch(
    url: str,
    timeout: float = 15.0,
    max_size: int = MAX_RESPONSE_SIZE,
) -> dict[str, Any]:
    headers = {"User-Agent": "THEORA/1.0"}
    current = url
    for _ in range(6):
        ok, reason = validate_url(current)
        if not ok:
            return _fail(reason)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
                async with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            return _fail("Redirect without Location header", code=resp.status_code)
                        await resp.aread()
                        current = urljoin(current, loc)
                        continue
                    if resp.status_code >= 400:
                        body = (await resp.aread())[:2048]
                        return _fail(
                            body.decode(errors="replace")[:500],
                            code=resp.status_code,
                            ctype=resp.headers.get("content-type", ""),
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_size:
                            return _fail(
                                f"Response exceeds max size ({max_size} bytes)",
                                code=resp.status_code,
                                ctype=resp.headers.get("content-type", ""),
                            )
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    ct = resp.headers.get("content-type", "")
                    return {
                        "success": True,
                        "content": raw.decode(errors="replace"),
                        "content_type": ct,
                        "status_code": resp.status_code,
                        "error": "",
                    }
        except httpx.RequestError as e:
            return _fail(str(e))
    return _fail("Too many redirects")
