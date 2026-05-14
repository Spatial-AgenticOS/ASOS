"""Phase 6 (audit-r10 overhaul) — permission_card SDUI flow.

When a Phase 4 iOS skill (or any future node skill) reports a denied
iOS permission, it returns the error string ``permission_denied:<NSKey>``
over HUP. This module turns that string into a structured
``permission_card`` SDUI element the web + iOS clients can render
with a deeplink to the iOS Settings app.

Why a structured card instead of prose:

The operator's complaint was that the brain hallucinates "go to
Settings and grant permission" text that doesn't deeplink anywhere
and frequently names a path that doesn't exist on iOS. A card with
an ``app-settings:`` URL drops the user one tap from the right
screen, and the description is sourced from this module, not the
LLM, so it can't drift.

Wire shape (one entry in the chat stream as a
``FeralMessage(type="sdui", payload={"root": {...}})``)::

    {
      "type": "permission_card",
      "permission_key": "NSContactsUsageDescription",
      "title": "FERAL needs access to Contacts",
      "description": "...",
      "ios_deeplink": "app-settings:",
      "ios_deeplink_label": "Open Settings",
      "skill_id": "contacts",
      "action": "phone.contact.lookup",
      "retryable": true
    }
"""
from __future__ import annotations

from typing import Optional

# ─── Static catalogue ────────────────────────────────────────────

# Every NSKey the Phase 4 + 4b skills can return. Keys here are the
# iOS Info.plist usage description identifiers. iOS does NOT expose a
# public deeplink that lands directly on a specific permission row;
# `app-settings:` opens this app's row in Settings, from which the
# permission lives one tap deeper. That's the best we can do today —
# Apple Intelligence (iOS 18+) may surface deeper targets later, at
# which point this map is the single seam to update.
PERMISSION_CATALOG: dict[str, dict] = {
    "NSContactsUsageDescription": {
        "title": "FERAL needs access to Contacts",
        "description": (
            "Looking up people by name (so the brain can route "
            "\"call John\" to a real phone number) requires "
            "permission to read your iOS Contacts."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSAppleMusicUsageDescription": {
        "title": "FERAL needs access to Apple Music",
        "description": (
            "Playing songs by title requires permission to use "
            "Apple Music. An active subscription is needed for "
            "full catalog playback."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSCalendarsFullAccessUsageDescription": {
        "title": "FERAL needs full access to Calendar",
        "description": (
            "Reading upcoming events and creating new ones requires "
            "full Calendar access. Write-only access is not enough — "
            "the brain wouldn't be able to answer \"what's on my "
            "schedule?\""
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSCalendarsUsageDescription": {  # legacy / pre-iOS 17 fallback
        "title": "FERAL needs access to Calendar",
        "description": (
            "Reading and creating events requires permission to use "
            "your iOS Calendar."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSRemindersFullAccessUsageDescription": {
        "title": "FERAL needs full access to Reminders",
        "description": (
            "Reading and creating reminders requires full access to "
            "the iOS Reminders database."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSPhotoLibraryUsageDescription": {
        "title": "FERAL needs access to Photos",
        "description": (
            "Searching and sharing photos with the brain requires "
            "permission to read your iOS photo library."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSLocationWhenInUseUsageDescription": {
        "title": "FERAL needs access to Location",
        "description": (
            "Location-aware answers (\"where's the nearest…\", "
            "\"how long is my commute\") require permission to read "
            "your iPhone's location while FERAL is in use."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSCameraUsageDescription": {
        "title": "FERAL needs access to the Camera",
        "description": (
            "Capturing a still from the phone camera requires "
            "permission to use the camera."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSMicrophoneUsageDescription": {
        "title": "FERAL needs access to the Microphone",
        "description": (
            "Voice commands and audio capture require permission "
            "to use the microphone."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
    "NSHealthShareUsageDescription": {
        "title": "FERAL needs access to Health",
        "description": (
            "Reading metrics like heart rate and steps from Apple "
            "Health requires explicit per-type permission. Open "
            "Settings → Health → Data Access to grant it."
        ),
        "ios_deeplink": "x-apple-health://",
        "ios_deeplink_label": "Open Health",
    },
    "NSBluetoothAlwaysUsageDescription": {
        "title": "FERAL needs access to Bluetooth",
        "description": (
            "Connecting to FERAL-compatible glasses and wristbands "
            "requires Bluetooth permission."
        ),
        "ios_deeplink": "app-settings:",
        "ios_deeplink_label": "Open Settings",
    },
}

# Generic fallback when the skill names a key we don't know about
# yet (e.g. Phase 4c adds a new framework whose key we haven't
# catalogued). The brain still produces a useful card — it just
# can't name the human-readable surface as crisply.
_FALLBACK = {
    "title": "FERAL needs an iOS permission",
    "description": (
        "An iOS framework reported that FERAL doesn't have the "
        "permission needed to complete this action. Open Settings "
        "and grant the requested access, then ask again."
    ),
    "ios_deeplink": "app-settings:",
    "ios_deeplink_label": "Open Settings",
}


# ─── Helpers ─────────────────────────────────────────────────────


_PREFIX = "permission_denied:"


def parse_permission_error(error: str | None) -> Optional[str]:
    """Return the NSKey from a ``permission_denied:<NSKey>`` error
    string, or ``None`` if the error doesn't match the contract.

    The match is exact-prefix; the rest of the string is the NSKey.
    Whitespace is trimmed because skills written in a hurry sometimes
    return ``"permission_denied: NSFoo"`` with a stray space.
    """
    if not error or not isinstance(error, str):
        return None
    if not error.startswith(_PREFIX):
        return None
    key = error[len(_PREFIX):].strip()
    return key or None


def build_permission_card(
    permission_key: str,
    *,
    skill_id: str = "",
    action: str = "",
    original_error: str = "",
    retryable: bool = True,
) -> dict:
    """Construct a permission_card SDUI dict.

    The returned dict is shaped so it can be handed straight to
    ``response_delivery.try_send_sdui`` — it carries the ``type``
    field that ``try_send_sdui`` keys on to wrap it as an SDUI
    envelope. ``original_error`` is preserved for diagnostics so the
    chat history retains the wire-level truth even after the card
    renders.
    """
    catalog_entry = PERMISSION_CATALOG.get(permission_key, _FALLBACK)
    card = {
        "type": "permission_card",
        "permission_key": permission_key,
        "title": catalog_entry["title"],
        "description": catalog_entry["description"],
        "ios_deeplink": catalog_entry["ios_deeplink"],
        "ios_deeplink_label": catalog_entry["ios_deeplink_label"],
        "retryable": bool(retryable),
    }
    if skill_id:
        card["skill_id"] = skill_id
    if action:
        card["action"] = action
    if original_error:
        card["_original_error"] = original_error
    return card


def card_for_action_result(
    result: dict,
    *,
    skill_id: str = "",
    action: str = "",
) -> Optional[dict]:
    """Inspect a HUP action result envelope; return a permission_card
    dict iff the envelope carries a ``permission_denied:`` error.

    Returns ``None`` otherwise — callers fall back to the normal
    error rendering path. Designed so ``execute_capability_action``
    and ``handle_daemon_result`` can plug it in with a single line.
    """
    if not isinstance(result, dict):
        return None
    if result.get("success") is True:
        return None
    err = result.get("error")
    key = parse_permission_error(err)
    if key is None:
        return None
    return build_permission_card(
        key,
        skill_id=skill_id,
        action=action,
        original_error=err or "",
    )
