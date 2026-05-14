"""Phase 11 (audit-r10 overhaul) — system permissions REST surface.

Exposes the macOS TCC permission state of the brain process so
clients (iOS BrainNetworkSection, web devices pane, future setup
wizards) can render a structured \u201cgrant / denied / unknown\u201d row per
permission instead of guessing.

Wire shape::

    GET /api/system/permissions
    {
      "platform": "darwin" | "linux" | ...,
      "permissions": [
        {"permission", "status", "api", "setup_step", "error"?}
      ]
    }

Read-only, LAN-public — same posture as ``/api/capabilities``.
"""
from __future__ import annotations

import logging
import platform

from fastapi import APIRouter

from security.macos_permissions import all_desktop_control_permission_statuses

logger = logging.getLogger("feral.api.system_permissions")

router = APIRouter(tags=["system"])


@router.get("/api/system/permissions")
async def get_system_permissions():
    statuses = all_desktop_control_permission_statuses()
    return {
        "platform": platform.system().lower(),
        "permissions": [s.to_dict() for s in statuses],
    }
