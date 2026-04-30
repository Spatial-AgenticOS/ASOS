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
    s = (stderr or "").strip()
    if not s:
        return None
    low = s.lower()
    if (
        "no such file or directory" in low
        and ("tailscaled.sock" in low or "/var/run/tailscale" in low or "tailscaled" in low)
    ):
        return TailscaleDaemonUnreachable(s)
    if "logged out" in low or "not logged in" in low or "not authenticated" in low:
        return TailscaleNotLoggedIn(s)
    # Tailscale 1.66+ emits this exact phrasing with the per-node enable URL:
    #     "Funnel is not enabled on your tailnet.
    #      To enable, visit: https://login.tailscale.com/f/funnel?node=…"
    # We surface the per-node URL when present (it's a one-click enable
    # specific to this tailnet); otherwise we fall back to the admin
    # settings page.
    if "funnel is not enabled" in low or (
        "funnel" in low
        and ("disable" in low or "not enabled" in low or "not allowed" in low)
    ):
        # Try to extract the activation URL the CLI printed.
        import re
        m = re.search(r"https://login\.tailscale\.com/f/funnel\?node=\S+", s)
        if m:
            return TailscaleFunnelDisabledInTailnet(
                "Funnel is not enabled on your tailnet. "
                f"Click this one-time enable link: {m.group(0)} "
                "(it's free; takes 5 seconds), then retry."
            )
        return TailscaleFunnelDisabledInTailnet(
            "Funnel is not enabled on your tailnet. "
            "Run `tailscale funnel <port>` once interactively to get the "
            "per-tailnet enable URL, or visit "
            "https://login.tailscale.com/admin/settings/features and "
            "turn on Funnel."
        )
    if "permission denied" in low or "must be run as root" in low or (
        "not in" in low and "group" in low
    ):
        return TailscalePermissionDenied(s)
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
    """Enable Tailscale Funnel for ``port`` (background, HTTPS on 443).

    Tailscale 1.66+ replaced the old ``funnel <port> on`` UX with
    ``funnel --bg <port>`` (background) and ``funnel reset`` (off).
    We try the modern form first and fall back to the legacy form
    for very old daemons (<1.50). If both fail with a classified
    error (e.g. Funnel-not-enabled-in-tailnet), we re-raise so the
    caller surfaces a remediation URL.

    Returns ``{enabled: bool, url: str, port: int}`` on success.
    """
    if port <= 0 or port > 65535:
        raise ValueError(f"port must be 1..65535 (got {port})")

    # Modern syntax (1.66+): `tailscale funnel --bg <port>`. The
    # `--bg` flag returns immediately after persisting the serve
    # config; without it the CLI blocks foreground forever (which is
    # what trapped the live test).
    proc = _run(["funnel", "--bg", str(port)], timeout=20.0)
    if proc.returncode != 0:
        classified = _classify_stderr(proc.stderr)
        if classified is not None:
            raise classified
        # Legacy fallback for <1.50 daemons that still accept
        # `funnel <port> on`. Newer CLIs reject this syntax with a
        # message about "the CLI for serve and funnel has changed",
        # which we'll classify back to a clean error.
        proc2 = _run(["funnel", str(port), "on"], timeout=15.0)
        if proc2.returncode != 0:
            classified2 = _classify_stderr(proc2.stderr)
            if classified2 is not None:
                raise classified2
            raise TailscaleSubprocessFailure(
                f"tailscale funnel could not be enabled on port {port}.\n"
                f"  modern syntax (`funnel --bg {port}`) stderr: "
                f"{proc.stderr.strip()[:300]}\n"
                f"  legacy syntax (`funnel {port} on`) stderr: "
                f"{proc2.stderr.strip()[:300]}\n"
                f"Run `tailscale funnel --help` to inspect your CLI's "
                f"current syntax."
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
    """Disable Funnel.

    Tailscale 1.66+ uses ``funnel reset`` (clears ALL forwards) — there
    is no per-port off in the modern CLI. We accept ``port`` as an
    argument for symmetry with ``funnel_enable`` but it isn't passed
    through. For older daemons we fall back to ``funnel <port> off``.

    Idempotent: running this when Funnel is already off is a no-op.
    """
    if port <= 0 or port > 65535:
        raise ValueError(f"port must be 1..65535 (got {port})")

    proc = _run(["funnel", "reset"], timeout=10.0)
    if proc.returncode == 0:
        return {"enabled": False, "port": port}

    # Modern reset failed — try legacy "off" form for ancient daemons.
    classified = _classify_stderr(proc.stderr)
    proc2 = _run(["funnel", str(port), "off"], timeout=10.0)
    if proc2.returncode == 0:
        return {"enabled": False, "port": port}

    # Both failed. If either looks like "Funnel was already off" (no
    # serve config), treat as success — disabling something that's
    # already disabled is the desired post-condition.
    combined = (proc.stderr + " " + proc2.stderr).lower()
    if (
        "no serve config" in combined
        or ("no" in combined and "funnel" in combined and "active" in combined)
    ):
        return {"enabled": False, "port": port}

    if classified is not None:
        raise classified
    classified2 = _classify_stderr(proc2.stderr)
    if classified2 is not None:
        raise classified2
    raise TailscaleSubprocessFailure(
        f"tailscale funnel could not be disabled.\n"
        f"  modern syntax (`funnel reset`) stderr: "
        f"{proc.stderr.strip()[:300]}\n"
        f"  legacy syntax (`funnel {port} off`) stderr: "
        f"{proc2.stderr.strip()[:300]}"
    )


def funnel_status() -> dict:
    """Read ``tailscale funnel status --json`` and parse active forwards.

    Returns ``{"active": bool, "ports": [int, ...]}``.

    Tailscale 1.66+ supports ``--json`` so we don't have to parse the
    prose output (which has changed shape several times). The JSON
    shape is::

        {
          "TCP": {"443": {"HTTPS": true}},
          "Web": {"<host>:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9090"}}}},
          "AllowFunnel": {"<host>:443": true}
        }

    We extract the local proxy port from the ``Web.<host>.Handlers``
    map. Empty ``{}`` JSON means "no serve config" → not active.
    """
    proc = _run(["funnel", "status", "--json"])
    if proc.returncode != 0:
        classified = _classify_stderr(proc.stderr)
        if classified is not None:
            raise classified
        return {"active": False, "ports": []}
    out = (proc.stdout or "").strip()
    if not out:
        return {"active": False, "ports": []}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"active": False, "ports": []}
    if not data:
        return {"active": False, "ports": []}

    ports: set[int] = set()
    web = data.get("Web") or {}
    for _host, conf in web.items():
        handlers = (conf or {}).get("Handlers") or {}
        for _path, h in handlers.items():
            proxy = (h or {}).get("Proxy") or ""
            # Proxy looks like "http://127.0.0.1:9090" or
            # "http+insecure://localhost:8443".
            if ":" in proxy:
                tail = proxy.rsplit(":", 1)[-1].split("/")[0]
                digits = "".join(ch for ch in tail if ch.isdigit())
                if digits:
                    try:
                        ports.add(int(digits))
                    except ValueError:
                        pass
    return {"active": bool(ports), "ports": sorted(ports)}


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
