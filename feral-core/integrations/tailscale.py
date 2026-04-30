"""Tailscale CLI integration for FERAL Mode C (remote pairing).

Provides a thin wrapper around the ``tailscale`` CLI so the brain can:

  * detect whether Tailscale is installed and the daemon is reachable
  * read the local node's tailnet name + IPs (``tailscale status --json``)
  * enable Tailscale Funnel on the brain port (``tailscale funnel <port> on``)
  * disable Funnel (``tailscale funnel <port> off``)

This is the implementation of the ``feral access remote-up`` flow
described in ``A4-pairing-redesign.md`` §2 Mode C onboarding step.

Honesty
-------
1. We only support the userspace-networking socket layout when the
   binary path *isn't* on the standard daemon socket. Tailscale's
   userspace mode runs at ``/tmp/tailscaled-userspace.sock`` (the
   pattern used by the FERAL desktop wrapper today). If both sockets
   are missing, the integration returns ``not_running``.
2. Funnel must be enabled in the operator's tailnet at
   https://login.tailscale.com/admin/settings/features. If it isn't,
   ``funnel_enable`` returns a structured error with the remediation
   URL — we do not try to silently configure ACLs.
3. We do not attempt to install Tailscale automatically. We detect
   absence and surface the install URL; the operator runs
   ``brew install --cask tailscale`` (macOS) or
   ``curl -fsSL https://tailscale.com/install.sh | sh`` (Linux) and
   re-runs the command.

All error paths raise the typed exceptions in this module so callers
(REST routes + CLI) can map them to status codes / exit codes
respectively.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("feral.integrations.tailscale")


# ── Exceptions ────────────────────────────────────────────────────


class TailscaleError(Exception):
    """Base class for Tailscale integration failures."""


class TailscaleNotInstalled(TailscaleError):
    """``tailscale`` binary not on PATH."""


class TailscaleDaemonUnreachable(TailscaleError):
    """``tailscaled`` not running or socket missing."""


class TailscaleNotLoggedIn(TailscaleError):
    """Tailscale daemon is up but the operator hasn't authenticated."""


class TailscaleFunnelDisabledInTailnet(TailscaleError):
    """Funnel is not enabled in the operator's tailnet ACLs.

    The remediation is at the URL in the message.
    """


class TailscalePermissionDenied(TailscaleError):
    """The user can't run ``tailscale funnel`` without elevated rights.

    On Linux this typically means the user isn't in the ``tailscale``
    group. The remediation is in the message.
    """


class TailscaleSubprocessFailure(TailscaleError):
    """The CLI returned a non-zero exit and the error wasn't classified
    above. Carries stdout + stderr for the operator to inspect."""


# ── Status data class ─────────────────────────────────────────────


@dataclass(frozen=True)
class TailscaleStatus:
    installed: bool
    running: bool
    logged_in: bool
    dns_name: str = ""
    ipv4: str = ""
    ipv6: str = ""
    tailnet_name: str = ""
    funnel_url: str = ""
    funnel_active: bool = False
    error: str = ""


# ── Internals ─────────────────────────────────────────────────────


def _socket_arg() -> list[str]:
    """If userspace tailscaled is running with the FERAL desktop's
    socket, prefer that socket; otherwise rely on the system default."""
    candidate = "/tmp/tailscaled-userspace.sock"
    if os.path.exists(candidate):
        return ["--socket", candidate]
    return []


def _run(args: list[str], *, timeout: float = 8.0) -> subprocess.CompletedProcess:
    """Run a tailscale CLI command and return the completed process.

    Does not raise on non-zero exit — callers classify the failure.
    """
    if not shutil.which("tailscale"):
        raise TailscaleNotInstalled(
            "`tailscale` binary not on PATH. Install with "
            "`brew install --cask tailscale` (macOS) or "
            "`curl -fsSL https://tailscale.com/install.sh | sh` (Linux), "
            "then re-run."
        )
    cmd = ["tailscale", *_socket_arg(), *args]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise TailscaleNotInstalled(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise TailscaleSubprocessFailure(
            f"tailscale {' '.join(args)} timed out after {timeout}s"
        ) from exc


def _classify_stderr(stderr: str) -> Optional[TailscaleError]:
    """Map common stderr patterns to typed exceptions."""
    s = (stderr or "").strip().lower()
    if not s:
        return None
    if (
        "no such file or directory" in s
        and ("tailscaled.sock" in s or "/var/run/tailscale" in s or "tailscaled" in s)
    ):
        return TailscaleDaemonUnreachable(stderr.strip())
    if "logged out" in s or "not logged in" in s or "not authenticated" in s:
        return TailscaleNotLoggedIn(stderr.strip())
    if "funnel" in s and ("disable" in s or "not enabled" in s or "not allowed" in s):
        return TailscaleFunnelDisabledInTailnet(
            "Funnel is not enabled in your tailnet. "
            "Visit https://login.tailscale.com/admin/settings/features "
            "and turn on Funnel, then retry."
        )
    if "permission denied" in s or "must be run as root" in s or "not in" in s and "group" in s:
        return TailscalePermissionDenied(stderr.strip())
    return None


# ── Public API ────────────────────────────────────────────────────


def is_installed() -> bool:
    return shutil.which("tailscale") is not None


def status_json() -> dict:
    """Return ``tailscale status --json`` parsed.

    Raises ``TailscaleNotInstalled`` if the binary is absent and
    ``TailscaleDaemonUnreachable`` if the daemon socket is missing.
    """
    proc = _run(["status", "--json"])
    if proc.returncode != 0:
        classified = _classify_stderr(proc.stderr)
        if classified is not None:
            raise classified
        raise TailscaleSubprocessFailure(
            f"tailscale status --json failed: rc={proc.returncode} "
            f"stderr={proc.stderr.strip()[:300]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise TailscaleSubprocessFailure(
            f"tailscale status --json returned non-JSON: {exc}"
        ) from exc


def status() -> TailscaleStatus:
    """Idempotent status snapshot used by ``feral access status`` and
    by the dashboard's Settings → Access panel.

    Returns a ``TailscaleStatus`` with ``error`` populated when the
    underlying state is partial (not-installed / not-running / not-
    logged-in). Never raises — callers can render the panel even when
    Tailscale is broken.
    """
    if not is_installed():
        return TailscaleStatus(
            installed=False,
            running=False,
            logged_in=False,
            error="tailscale_not_installed",
        )
    try:
        data = status_json()
    except TailscaleDaemonUnreachable:
        return TailscaleStatus(
            installed=True, running=False, logged_in=False,
            error="daemon_unreachable",
        )
    except TailscaleNotLoggedIn:
        return TailscaleStatus(
            installed=True, running=True, logged_in=False,
            error="not_logged_in",
        )
    except TailscaleError as exc:
        return TailscaleStatus(
            installed=True, running=False, logged_in=False,
            error=f"unknown:{exc.__class__.__name__}",
        )

    self_node = data.get("Self") or {}
    dns_name = (self_node.get("DNSName") or "").rstrip(".")
    ips = self_node.get("TailscaleIPs") or []
    ipv4 = next((ip for ip in ips if ":" not in ip), "")
    ipv6 = next((ip for ip in ips if ":" in ip), "")
    # CurrentTailnet is sometimes missing when only one tailnet is in
    # play; fall back to the last 2 dot-segments of the DNSName.
    tailnet_name = (data.get("CurrentTailnet") or {}).get("Name", "") or (
        ".".join(dns_name.split(".")[-3:-1]) if dns_name else ""
    )

    return TailscaleStatus(
        installed=True,
        running=True,
        logged_in=True,
        dns_name=dns_name,
        ipv4=ipv4,
        ipv6=ipv6,
        tailnet_name=tailnet_name,
    )


def funnel_url(port: int, *, dns_name: Optional[str] = None) -> str:
    """Compose the public Funnel URL for the given brain port.

    Tailscale Funnel terminates HTTPS at the tailnet edge and forwards
    to the local port. The URL is always ``https://<dns-name>``
    (Funnel doesn't advertise non-default ports — incoming requests
    on 443 forward to whatever ``tailscale funnel`` was last
    configured for).
    """
    if dns_name is None:
        snap = status()
        dns_name = snap.dns_name
    if not dns_name:
        return ""
    return f"https://{dns_name}"


def funnel_enable(port: int) -> dict:
    """Run ``tailscale funnel <port> on``. Idempotent — if Funnel is
    already serving the port we return a success result without
    reconfiguring.

    Returns ``{enabled: bool, url: str, port: int}`` on success.
    Raises typed exceptions on classified failures.
    """
    if port <= 0 or port > 65535:
        raise ValueError(f"port must be 1..65535 (got {port})")

    # Some `tailscale funnel` versions take "<port> on", others take
    # "on --port=<port>". The "<port> on" form is widely supported on
    # macOS and Linux 1.50+. Try it first; fall back if the binary
    # rejects the syntax.
    proc = _run(["funnel", str(port), "on"], timeout=15.0)
    if proc.returncode != 0:
        classified = _classify_stderr(proc.stderr)
        if classified is not None:
            raise classified
        # Try the alternate syntax.
        proc2 = _run(["funnel", "--bg", "on", "--port", str(port)], timeout=15.0)
        if proc2.returncode != 0:
            classified2 = _classify_stderr(proc2.stderr)
            if classified2 is not None:
                raise classified2
            raise TailscaleSubprocessFailure(
                f"tailscale funnel {port} on failed:\n"
                f"  primary stderr: {proc.stderr.strip()[:300]}\n"
                f"  fallback stderr: {proc2.stderr.strip()[:300]}"
            )

    snap = status()
    return {
        "enabled": True,
        "url": funnel_url(port, dns_name=snap.dns_name),
        "port": port,
        "tailnet": snap.tailnet_name,
        "dns_name": snap.dns_name,
    }


def funnel_disable(port: int) -> dict:
    """Run ``tailscale funnel <port> off``. Idempotent."""
    if port <= 0 or port > 65535:
        raise ValueError(f"port must be 1..65535 (got {port})")
    proc = _run(["funnel", str(port), "off"], timeout=10.0)
    if proc.returncode != 0:
        classified = _classify_stderr(proc.stderr)
        if classified is not None:
            raise classified
        # Most "off" failures mean Funnel was already off; treat as success.
        if "no" in (proc.stderr or "").lower() and "funnel" in (proc.stderr or "").lower():
            return {"enabled": False, "port": port}
        raise TailscaleSubprocessFailure(
            f"tailscale funnel {port} off failed: rc={proc.returncode} "
            f"stderr={proc.stderr.strip()[:300]}"
        )
    return {"enabled": False, "port": port}


def funnel_status() -> dict:
    """Read ``tailscale funnel status`` and parse the active forwards.

    Returns ``{"active": bool, "ports": [int, ...]}``. We don't need
    the per-port details right now; the brain only ever exposes one
    port (the brain port).
    """
    proc = _run(["funnel", "status"])
    if proc.returncode != 0:
        classified = _classify_stderr(proc.stderr)
        if classified is not None:
            raise classified
        # tailscale funnel status returns non-zero if Funnel is fully
        # off; treat that as "no active ports" rather than an error.
        return {"active": False, "ports": []}
    out = (proc.stdout or "").strip()
    if not out or "no funnels" in out.lower():
        return {"active": False, "ports": []}
    # Extremely lightweight parser: any line containing ":443" implies
    # Funnel is forwarding 443 → some local port. Pull the local port.
    ports: list[int] = []
    for line in out.splitlines():
        line = line.strip().lower()
        if "127.0.0.1:" in line or "localhost:" in line:
            # find last :digits substring
            tail = line.rsplit(":", 1)[-1]
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                try:
                    ports.append(int(digits))
                except ValueError:
                    pass
    return {"active": bool(ports), "ports": ports}


__all__ = [
    "TailscaleError",
    "TailscaleNotInstalled",
    "TailscaleDaemonUnreachable",
    "TailscaleNotLoggedIn",
    "TailscaleFunnelDisabledInTailnet",
    "TailscalePermissionDenied",
    "TailscaleSubprocessFailure",
    "TailscaleStatus",
    "is_installed",
    "status",
    "status_json",
    "funnel_enable",
    "funnel_disable",
    "funnel_status",
    "funnel_url",
]
