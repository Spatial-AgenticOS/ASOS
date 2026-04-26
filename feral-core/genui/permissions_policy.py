"""Permission policy + CSP derivation for FERAL GenUI app surfaces.

Two responsibilities:

1. Validate the ``permissions`` block on an installed manifest at
   install time. The wildcard network grant (``permissions.network ==
   ["*"]``) is the highest-blast-radius permission an app can ask
   for, so we make the publisher *and* the user opt in explicitly:

      * the publisher must supply ``permissions.justification`` (a
        non-empty human-readable string),
      * the installer must pass ``user_high_trust=True`` AND
        ``allow_unsigned=False`` (i.e. the manifest is signed),
      * otherwise we raise :class:`PolicyViolation`.

2. Derive the Content-Security-Policy header that the AppSurface
   iframe ships in its ``srcdoc``. The CSP ``connect-src`` directive
   is built from the manifest's ``permissions.network`` allowlist —
   no allowlist means no outbound network from the surface.

The manifest's existing ``permissions: list[str]`` field stays
backward-compatible; this module also accepts the richer
``{"network": [...], "justification": "..."}`` shape so a publisher
can opt into the new model without breaking older bundles.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional


__all__ = [
    "PolicyViolation",
    "extract_permissions_block",
    "network_allowlist",
    "justification",
    "is_wildcard_network",
    "enforce_install_policy",
    "build_csp_header",
]


class PolicyViolation(ValueError):
    """Raised when an install request violates the permission policy."""


# ----------------------------------------------------------------------
# Manifest parsing helpers
# ----------------------------------------------------------------------


def extract_permissions_block(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the manifest's permissions block as a normalised dict.

    Accepts either:
      * ``permissions: ["calendar:read", "network:*"]``  (legacy list)
      * ``permissions: {"network": ["*"], "justification": "..."}``

    The legacy list shape is mapped to a dict with empty ``network``
    so the rest of the module always sees the same structure.
    """
    raw = manifest.get("permissions")
    if raw is None:
        return {"network": [], "justification": ""}
    if isinstance(raw, dict):
        net = raw.get("network") or []
        if not isinstance(net, list):
            raise PolicyViolation(
                "permissions.network must be a list of origins or ['*']"
            )
        net = [str(x) for x in net]
        just = str(raw.get("justification") or "")
        return {"network": net, "justification": just, **{
            k: v for k, v in raw.items() if k not in ("network", "justification")
        }}
    if isinstance(raw, list):
        # Legacy form: opaque tags, no structured network grant.
        return {"network": [], "justification": "", "tags": [str(t) for t in raw]}
    raise PolicyViolation(
        f"permissions must be a dict or list, got {type(raw).__name__}"
    )


def network_allowlist(manifest: dict[str, Any]) -> list[str]:
    """Return the per-origin network allowlist (may include '*')."""
    return list(extract_permissions_block(manifest).get("network") or [])


def justification(manifest: dict[str, Any]) -> str:
    return str(extract_permissions_block(manifest).get("justification") or "")


def is_wildcard_network(manifest: dict[str, Any]) -> bool:
    return network_allowlist(manifest) == ["*"]


# ----------------------------------------------------------------------
# Install-time policy gate
# ----------------------------------------------------------------------


def enforce_install_policy(
    manifest: dict[str, Any],
    *,
    allow_unsigned: bool,
    user_high_trust: bool,
) -> None:
    """Raise :class:`PolicyViolation` if *manifest* must not be installed.

    Today there is exactly one rule, but this is the natural seam to
    bolt on more (filesystem grants, intra-app skill calls, etc.):

    * Wildcard ``permissions.network == ["*"]`` requires
      ``allow_unsigned=False`` (i.e. signed manifest verified upstream)
      AND ``user_high_trust=True`` AND a non-empty
      ``permissions.justification``. Default behaviour: refuse.
    """
    if is_wildcard_network(manifest):
        reasons: list[str] = []
        if allow_unsigned:
            reasons.append("manifest must be signed (allow_unsigned=False)")
        if not user_high_trust:
            reasons.append("user_high_trust flag must be true on install")
        if not justification(manifest):
            reasons.append("permissions.justification must be a non-empty string")
        if reasons:
            raise PolicyViolation(
                "wildcard network permission refused: " + "; ".join(reasons)
            )


# ----------------------------------------------------------------------
# CSP derivation
# ----------------------------------------------------------------------


_ORIGIN_RE = re.compile(
    r"^(?:https?://)?[a-zA-Z0-9.\-:*]+(?::\d+)?(?:/.*)?$"
)


def _coerce_csp_source(origin: str) -> Optional[str]:
    """Map a permissions.network entry to a CSP source string.

    Returns ``None`` for entries we refuse to emit (so the caller can
    drop them silently rather than embedding a hostile origin).
    """
    o = (origin or "").strip()
    if not o:
        return None
    if o == "*":
        return "*"
    if o.startswith(("http://", "https://", "wss://", "ws://")):
        return o
    if _ORIGIN_RE.match(o):
        return f"https://{o}"
    return None


def build_csp_header(
    manifest: dict[str, Any],
    *,
    extra_connect_src: Iterable[str] = (),
) -> str:
    """Return the CSP string for the AppSurface iframe srcdoc.

    Fixed baseline (the parts that don't come from the manifest):

      * ``default-src 'none'`` — deny everything by default.
      * ``script-src 'unsafe-inline'`` — the iframe's bootstrap
        script lives in the srcdoc, so it has to be inline. Sandbox
        flags (``allow-scripts``, *not* ``allow-same-origin``) make
        this safe: script can't reach into the parent frame.
      * ``style-src 'unsafe-inline'`` — same reason for inline CSS.
      * ``img-src``, ``media-src``, ``font-src`` — ``data:`` only by
        default, plus whatever the publisher allowlists.
      * ``frame-ancestors 'self'`` — only the FERAL host page may
        embed the surface.
      * ``base-uri 'none'`` — block ``<base>`` rebasing tricks.
      * ``form-action 'none'`` — surface posts go via postMessage,
        not form submit.

    Variable parts:

      * ``connect-src`` is the manifest's ``permissions.network``
        allowlist, plus anything in ``extra_connect_src`` (used by
        the host to add its own message bridge if needed).
    """
    perms_net = network_allowlist(manifest)
    connect_sources: list[str] = []
    for origin in perms_net:
        coerced = _coerce_csp_source(origin)
        if coerced:
            connect_sources.append(coerced)
    for extra in extra_connect_src:
        coerced = _coerce_csp_source(extra)
        if coerced and coerced not in connect_sources:
            connect_sources.append(coerced)

    if not connect_sources:
        connect_directive = "connect-src 'none'"
    else:
        connect_directive = "connect-src " + " ".join(connect_sources)

    directives = [
        "default-src 'none'",
        "script-src 'unsafe-inline'",
        "style-src 'unsafe-inline'",
        "img-src 'self' data: https:",
        "media-src 'self' data:",
        "font-src 'self' data:",
        connect_directive,
        "frame-ancestors 'self'",
        "base-uri 'none'",
        "form-action 'none'",
    ]
    return "; ".join(directives)
