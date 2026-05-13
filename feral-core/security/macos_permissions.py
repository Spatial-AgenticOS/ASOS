"""
macOS TCC permission probes for FERAL's GUI / vision computer-use stack.

Two privacy-protected entitlements gate everything FERAL needs to drive
a Mac:

* **Accessibility** — required by ``pyautogui`` (and any synthetic
  click/keystroke) so the OS will accept input events from a
  non-Apple-signed process. Apple's API: ``AXIsProcessTrustedWithOptions``.
* **Screen Recording** — required by ``screencapture`` and ``CGWindowList``
  to see anything beyond the menu bar wallpaper. Apple's API:
  ``CGPreflightScreenCaptureAccess``.

We deliberately do NOT call ``tccutil``: that tool resets the privacy
database from the command line and does not reliably *read* the current
grant state for an arbitrary process. The only honest readout is via
the ApplicationServices / Quartz APIs themselves, gated behind PyObjC.

If PyObjC isn't installed, we say so in ``status="unknown"`` and surface
the exact remediation step (``pip install pyobjc-framework-ApplicationServices
pyobjc-framework-Quartz``) — never a green checkmark masquerading as
real availability.

This module is import-safe on every platform: on non-Darwin hosts the
probe returns ``status="not_applicable"`` immediately so callers don't
need to branch.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Optional


@dataclass
class TCCStatus:
    """Result of a single TCC probe.

    * ``permission`` — short name (``accessibility`` | ``screen_recording``).
    * ``status`` — one of:
        - ``granted`` — Apple's API confirmed access.
        - ``denied`` — API returned False/0 (no access).
        - ``unknown`` — PyObjC missing or the API raised; we cannot tell.
        - ``not_applicable`` — not running on macOS.
    * ``api`` — the underlying API used (e.g. ``AXIsProcessTrustedWithOptions``).
    * ``setup_step`` — exact human/CLI instruction to remediate.
    * ``error`` — diagnostic detail when ``status`` is ``unknown``.
    """

    permission: str
    status: str
    api: str
    setup_step: str
    error: Optional[str] = None

    def to_dict(self) -> dict:
        out = {
            "permission": self.permission,
            "status": self.status,
            "api": self.api,
            "setup_step": self.setup_step,
        }
        if self.error:
            out["error"] = self.error
        return out


_ACCESSIBILITY_REMEDIATION = (
    "Open System Settings -> Privacy & Security -> Accessibility, "
    "click the lock to unlock, and enable the FERAL host process "
    "(usually 'Terminal', 'iTerm', or your launching app). Restart "
    "FERAL afterwards so the new grant takes effect for the running "
    "process."
)

_SCREEN_RECORDING_REMEDIATION = (
    "Open System Settings -> Privacy & Security -> Screen Recording, "
    "click the lock to unlock, and enable the FERAL host process. "
    "macOS forces a quit-and-relaunch of the granted app the first "
    "time you enable Screen Recording — restart FERAL after toggling."
)

_PYOBJC_REMEDIATION_AX = (
    "Install PyObjC ApplicationServices bindings to enable an honest "
    "Accessibility readout: pip install pyobjc-framework-ApplicationServices"
)

_PYOBJC_REMEDIATION_SR = (
    "Install PyObjC Quartz bindings to enable an honest Screen Recording "
    "readout: pip install pyobjc-framework-Quartz"
)


def _not_applicable(name: str, api: str) -> TCCStatus:
    return TCCStatus(
        permission=name,
        status="not_applicable",
        api=api,
        setup_step="Skipped: macOS-only permission",
    )


def check_accessibility() -> TCCStatus:
    """Probe Accessibility (synthetic input) entitlement.

    Uses ``AXIsProcessTrustedWithOptions`` with the prompt option
    explicitly disabled — we never want a doctor probe to silently
    pop a system permission dialog.
    """
    if platform.system() != "Darwin":
        return _not_applicable("accessibility", "AXIsProcessTrustedWithOptions")

    try:
        # `HIServices` is the public umbrella for AX in modern macOS;
        # the legacy import path lives under `ApplicationServices`.
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        from CoreFoundation import (  # type: ignore[import-not-found]
            CFDictionaryCreate,
            kCFTypeDictionaryKeyCallBacks,
            kCFTypeDictionaryValueCallBacks,
            kCFBooleanFalse,
        )
    except ImportError as exc:
        return TCCStatus(
            permission="accessibility",
            status="unknown",
            api="AXIsProcessTrustedWithOptions",
            setup_step=_PYOBJC_REMEDIATION_AX,
            error=f"PyObjC ApplicationServices not importable: {exc}",
        )

    try:
        options = CFDictionaryCreate(
            None,
            (kAXTrustedCheckOptionPrompt,),
            (kCFBooleanFalse,),
            1,
            kCFTypeDictionaryKeyCallBacks,
            kCFTypeDictionaryValueCallBacks,
        )
        granted = bool(AXIsProcessTrustedWithOptions(options))
    except Exception as exc:  # PyObjC sometimes raises on framework issues
        return TCCStatus(
            permission="accessibility",
            status="unknown",
            api="AXIsProcessTrustedWithOptions",
            setup_step=_ACCESSIBILITY_REMEDIATION,
            error=f"AX probe raised: {exc}",
        )

    if granted:
        return TCCStatus(
            permission="accessibility",
            status="granted",
            api="AXIsProcessTrustedWithOptions",
            setup_step="(no action needed)",
        )
    return TCCStatus(
        permission="accessibility",
        status="denied",
        api="AXIsProcessTrustedWithOptions",
        setup_step=_ACCESSIBILITY_REMEDIATION,
    )


def check_screen_recording() -> TCCStatus:
    """Probe Screen Recording entitlement.

    Uses ``CGPreflightScreenCaptureAccess`` from Quartz: this returns a
    boolean without prompting the user, which is exactly what a doctor
    needs.
    """
    if platform.system() != "Darwin":
        return _not_applicable("screen_recording", "CGPreflightScreenCaptureAccess")

    try:
        from Quartz import (  # type: ignore[import-not-found]
            CGPreflightScreenCaptureAccess,
        )
    except ImportError as exc:
        return TCCStatus(
            permission="screen_recording",
            status="unknown",
            api="CGPreflightScreenCaptureAccess",
            setup_step=_PYOBJC_REMEDIATION_SR,
            error=f"PyObjC Quartz not importable: {exc}",
        )

    try:
        granted = bool(CGPreflightScreenCaptureAccess())
    except Exception as exc:
        return TCCStatus(
            permission="screen_recording",
            status="unknown",
            api="CGPreflightScreenCaptureAccess",
            setup_step=_SCREEN_RECORDING_REMEDIATION,
            error=f"CG probe raised: {exc}",
        )

    if granted:
        return TCCStatus(
            permission="screen_recording",
            status="granted",
            api="CGPreflightScreenCaptureAccess",
            setup_step="(no action needed)",
        )
    return TCCStatus(
        permission="screen_recording",
        status="denied",
        api="CGPreflightScreenCaptureAccess",
        setup_step=_SCREEN_RECORDING_REMEDIATION,
    )


def all_gui_permission_statuses() -> list[TCCStatus]:
    """Convenience wrapper that returns every GUI-relevant TCC probe."""
    return [check_accessibility(), check_screen_recording()]


__all__ = [
    "TCCStatus",
    "check_accessibility",
    "check_screen_recording",
    "all_gui_permission_statuses",
]
