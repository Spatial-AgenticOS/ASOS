"""REST routes for third-party GenUI apps (see agents/app_registry.py).

Every endpoint is shallow — the real logic lives in AppRegistry +
HybridGenerator. The routes are intentionally small so both a v2
client and an external `feral app` CLI talk to the same surface.

Routes
------
GET    /api/apps                              — list installed apps
GET    /api/apps/{app_id}/manifest            — fetch the stored manifest
POST   /api/apps/install                      — install from local dir / git URL / registry id
DELETE /api/apps/{app_id}                     — uninstall
POST   /api/apps/{app_id}/open                — render a surface + push sdui
POST   /api/apps/{app_id}/surfaces/{id}/render — render without pushing
POST   /api/apps/{app_id}/dispatch            — validate + execute an action (REST parity with ui_event)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.state import state

logger = logging.getLogger("feral.api.apps")

router = APIRouter(tags=["apps"])


def _require_registry():
    registry = getattr(state, "app_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="AppRegistry not initialised")
    return registry


def _manifest_summary(app) -> dict:
    m = app.manifest
    return {
        "app_id": m.app_id,
        "version": m.version,
        "author": m.author,
        "description": m.description,
        "brand": m.brand.model_dump(),
        "entry_surface_id": m.entry_surface_id,
        "surfaces": [s.surface_id for s in m.surfaces],
        "permissions": list(m.permissions),
        "install_dir": str(app.install_dir),
        "installed_at": app.installed_at,
    }


@router.get("/api/apps")
async def list_apps():
    registry = _require_registry()
    apps = registry.list()
    return {
        "count": len(apps),
        "apps": [_manifest_summary(a) for a in apps],
    }


@router.get("/api/apps/{app_id}/manifest")
async def get_manifest(app_id: str):
    registry = _require_registry()
    app = registry.get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"app {app_id!r} not installed")
    return {
        "app_id": app.app_id,
        "version": app.version,
        "manifest": app.manifest.model_dump(),
        "install_dir": str(app.install_dir),
    }


class InstallRequest(BaseModel):
    # Exactly one of these should be set; the handler validates.
    path: Optional[str] = None
    git_url: Optional[str] = None
    registry_id: Optional[str] = None
    overwrite: bool = True


@router.post("/api/apps/install")
async def install_app(req: InstallRequest):
    registry = _require_registry()
    sources_set = sum(1 for v in (req.path, req.git_url, req.registry_id) if v)
    if sources_set == 0:
        raise HTTPException(status_code=400, detail="provide one of: path, git_url, registry_id")
    if sources_set > 1:
        raise HTTPException(status_code=400, detail="provide exactly one of: path, git_url, registry_id")

    if req.path:
        try:
            app = registry.install_from_dir(req.path, overwrite=req.overwrite)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "app": _manifest_summary(app)}

    if req.git_url:
        tmp = Path(tempfile.mkdtemp(prefix="feral-app-clone-"))
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", req.git_url, str(tmp)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"git clone failed: {result.stderr.strip()[:400]}",
                )
            try:
                app = registry.install_from_dir(tmp, overwrite=req.overwrite)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            return {"success": True, "app": _manifest_summary(app)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if req.registry_id:
        # Registry install lands in commit 6 once the CLI + Kind.app
        # publish flow exists. Report honestly until then so callers
        # can branch on the status code.
        raise HTTPException(
            status_code=501,
            detail="registry_id install requires registry.feral.sh Kind.app; ship feral-registry commit 6 first",
        )


@router.delete("/api/apps/{app_id}")
async def uninstall_app(app_id: str):
    registry = _require_registry()
    removed = registry.uninstall(app_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"app {app_id!r} not installed")
    return {"success": True}


class OpenSurfaceRequest(BaseModel):
    surface_id: Optional[str] = None
    data: dict = Field(default_factory=dict)
    session_id: str = ""
    user_fingerprint: str = "default"
    regenerate: bool = False


@router.post("/api/apps/{app_id}/open")
async def open_app(app_id: str, req: OpenSurfaceRequest):
    """Render a surface AND push it over the active session WebSocket.

    If the caller supplies a ``session_id`` that matches a live v2
    session, the brain emits an ``sdui`` message so the UI mounts the
    tree inline. Otherwise the payload is returned in the response
    body for the caller to render itself.
    """
    registry = _require_registry()
    app = registry.get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"app {app_id!r} not installed")
    surface_id = req.surface_id or app.manifest.entry_surface_id
    try:
        result = await registry.open_surface(
            app_id=app_id,
            surface_id=surface_id,
            session_id=req.session_id,
            data=req.data,
            user_fingerprint=req.user_fingerprint,
            regenerate=req.regenerate,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Optional push over the active WebSocket.
    if req.session_id and state.sessions and req.session_id in state.sessions:
        try:
            from models.protocol import FeralMessage, SDUIPayload
            await state.send_to_session(
                req.session_id,
                FeralMessage(
                    session_id=req.session_id,
                    hop="brain",
                    type="sdui",
                    payload=SDUIPayload(
                        screen_id=result["screen_id"],
                        root=result["root"],
                    ).model_dump(),
                ),
            )
        except Exception as exc:
            logger.debug("Push to session failed silently: %s", exc)

    return {"success": True, **result}


class RenderSurfaceRequest(BaseModel):
    data: dict = Field(default_factory=dict)
    user_fingerprint: str = "default"
    regenerate: bool = False


@router.post("/api/apps/{app_id}/surfaces/{surface_id}/render")
async def render_surface(app_id: str, surface_id: str, req: RenderSurfaceRequest):
    registry = _require_registry()
    app = registry.get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"app {app_id!r} not installed")
    try:
        result = await registry.open_surface(
            app_id=app_id,
            surface_id=surface_id,
            session_id="",
            data=req.data,
            user_fingerprint=req.user_fingerprint,
            regenerate=req.regenerate,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, **result}


class DispatchRequest(BaseModel):
    surface_id: str
    action_id: str
    value: Any = None
    event: str = "tap"
    session_id: str = ""


@router.post("/api/apps/{app_id}/dispatch")
async def dispatch_action(app_id: str, req: DispatchRequest):
    """Dispatch a ui_event via REST (parity with WebSocket ui_event).

    Validates the action against the surface contract, returns 400 on
    drift, then forwards to the orchestrator exactly the same way the
    WS path does. Used by external CLIs / tests that don't want to
    keep a live WebSocket open.
    """
    registry = _require_registry()
    try:
        spec = registry.validate_action(app_id, req.surface_id, req.action_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if state.orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not available")

    screen_id = f"{app_id}:{req.surface_id}:{req.session_id or 'default'}"
    try:
        await state.orchestrator.handle_ui_event(
            session_id=req.session_id or "rest-dispatch",
            action_id=req.action_id,
            event=req.event,
            value=req.value,
            app_id=app_id,
            screen_id=screen_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "success": True,
        "handler": spec.handler,
        "target": spec.target,
        "screen_id": screen_id,
    }
