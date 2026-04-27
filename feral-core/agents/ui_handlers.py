from __future__ import annotations

import logging
from typing import Any, Optional

from models.protocol import FeralMessage, SDUIPayload

logger = logging.getLogger("feral.orchestrator")


async def handle_ui_event(
    orchestrator,
    session_id: str,
    action_id: str,
    event: str,
    value: Any = None,
    app_id: Optional[str] = None,
    screen_id: Optional[str] = None,
):
    """Dispatch a UI event to the right handler.

    When ``app_id`` is present, the event is scoped to a third-party
    GenUI app: we resolve the surface from ``screen_id`` (which has
    the shape ``<app_id>:<surface_id>:<session>`` assigned at
    ``AppRegistry.open_surface`` time), validate the action against
    the declared ``action_contract``, and route per the action's
    handler (navigate / patch / skill_call / app_event / close).
    Malformed app events are rejected with a short text reply so a
    compromised client can't invoke arbitrary skill endpoints by
    guessing action ids.
    """
    logger.info(
        "[%s] UI: %s -> %s = %r (app_id=%s)",
        session_id[:8], event, action_id, value, app_id or "",
    )

    if app_id:
        await _handle_app_action(
            orchestrator,
            session_id=session_id,
            app_id=app_id,
            action_id=action_id,
            event=event,
            value=value,
            screen_id=screen_id,
        )
        return

    if action_id.startswith("call_"):
        tool_ref = action_id[5:]
        await orchestrator._execute_tool_call(session_id, {"name": tool_ref, "args": {}}, [])
    elif action_id.startswith("confirm_"):
        confirmation_id = action_id[8:]
        pending = orchestrator._pending_confirmations.pop(confirmation_id, None)
        if pending:
            logger.info(f"User confirmed action: {confirmation_id}")
            await orchestrator._execute_tool_call(session_id, pending["tool_call"], pending.get("skills", []))
    elif action_id.startswith("reject_"):
        confirmation_id = action_id[7:]
        pending = orchestrator._pending_confirmations.pop(confirmation_id, None)
        if pending:
            logger.info(f"User rejected action: {confirmation_id}")
            await orchestrator._send_text(session_id, "Cancelled. I won't run that action.")
    elif action_id.startswith("perm_grant_"):
        await handle_permission_response(orchestrator, session_id, action_id[11:], granted=True, value=value)
    elif action_id.startswith("perm_deny_"):
        await handle_permission_response(orchestrator, session_id, action_id[10:], granted=False, value=value)
    else:
        await orchestrator.handle_command(
            session_id,
            f"The user interacted with '{action_id}' (event: {event}, value: {value}). What should happen next?",
        )


async def _handle_app_action(
    orchestrator,
    *,
    session_id: str,
    app_id: str,
    action_id: str,
    event: str,
    value: Any,
    screen_id: Optional[str],
) -> None:
    """Dispatch a ui_event that belongs to a third-party GenUI app.

    Flow:
    1. Lookup AppRegistry on ``state`` — bail out with a polite text
       reply if the subsystem isn't initialised (boot race / tests).
    2. Resolve the surface_id from ``screen_id``. If the client didn't
       send an app-scoped screen_id we use the app's ``entry_surface_id``
       so the action still has a valid surface context.
    3. Validate the action against the surface's ``action_contract``.
       Unknown action ids are refused; the handler never falls through
       to ``handle_command`` on an app path.
    4. Dispatch per the action's declared handler.
    """
    try:
        from api.state import state as _state
    except Exception:
        _state = None
    registry = getattr(_state, "app_registry", None) if _state else None
    if registry is None:
        await orchestrator._send_text(
            session_id,
            "The app registry isn't available right now. Please retry shortly.",
        )
        return

    app = registry.get(app_id)
    if app is None:
        await orchestrator._send_text(
            session_id,
            f"App '{app_id}' is not installed on this brain.",
        )
        return

    surface_id = None
    if screen_id:
        resolved = registry.resolve_app_and_surface(screen_id)
        if resolved and resolved[0] == app_id:
            surface_id = resolved[1]
    if not surface_id:
        surface_id = app.manifest.entry_surface_id

    try:
        action_spec = registry.validate_action(app_id, surface_id, action_id)
    except Exception as exc:
        logger.warning(
            "Rejecting unsigned app action: app=%s surface=%s action=%s (%s)",
            app_id, surface_id, action_id, exc,
        )
        await orchestrator._send_text(
            session_id,
            f"That action isn't in {app_id}'s surface contract.",
        )
        return

    handler = action_spec.handler

    if handler == "navigate":
        target = action_spec.target or ""
        if not target:
            await orchestrator._send_text(session_id, "App navigation had no target surface.")
            return
        result = await registry.open_surface(
            app_id=app_id,
            surface_id=target,
            session_id=session_id,
            data=value if isinstance(value, dict) else {},
        )
        await orchestrator.send(
            session_id,
            FeralMessage(
                session_id=session_id,
                hop="brain",
                type="sdui",
                payload=SDUIPayload(
                    screen_id=result["screen_id"],
                    root=result["root"],
                ).model_dump(),
            ),
        )
        return

    if handler == "close":
        await orchestrator._send_text(session_id, f"Closed {app_id}/{surface_id}.")
        return

    if handler == "skill_call":
        if not action_spec.target:
            await orchestrator._send_text(
                session_id,
                f"App {app_id} declared a skill_call but no target endpoint.",
            )
            return
        tool_call = {"name": action_spec.target, "args": value if isinstance(value, dict) else {}}
        try:
            await orchestrator._execute_tool_call(session_id, tool_call, [])
        except Exception as exc:
            logger.warning("App skill_call failed: %s", exc)
            await orchestrator._send_text(session_id, f"The app's tool call failed: {exc}")
        return

    if handler == "patch":
        # Patch handler is reserved — the publisher's app backend is
        # expected to push sdui_patch envelopes directly in a follow-up
        # commit. For now we acknowledge so the client isn't stuck.
        logger.info(
            "App %s/%s emitted a patch-handler action %s; no patch backend wired yet",
            app_id, surface_id, action_id,
        )
        return

    # Default handler: "app_event" — the brain forwards the tuple to
    # the orchestrator as an LLM-visible event so the agent can decide
    # what to do next (e.g. log the action, surface a confirmation,
    # or call an unrelated skill). Keeps publishers productive even
    # before they wire a dedicated backend.
    await orchestrator.handle_command(
        session_id,
        (
            f"App '{app_id}' surface '{surface_id}' emitted action '{action_id}' "
            f"(event: {event}, value: {value}). What should happen next?"
        ),
    )


async def send_permission_request(orchestrator, session_id: str, path: str, operation: str, reason: str = "") -> None:
    from uuid import uuid4 as _uuid4

    req_id = str(_uuid4())[:8]
    orchestrator._pending_permission_requests[req_id] = {
        "session_id": session_id,
        "path": path,
        "operation": operation,
    }
    await orchestrator.send(
        session_id,
        FeralMessage(
            session_id=session_id,
            hop="brain",
            type="permission_request",
            payload={
                "request_id": req_id,
                "path": path,
                "operation": operation,
                "reason": reason or f"The agent needs {operation} access to {path}",
            },
        ),
    )


async def handle_permission_response(orchestrator, session_id: str, req_id: str, granted: bool, value=None) -> None:
    _ = value
    pending = orchestrator._pending_permission_requests.pop(req_id, None)
    if not pending:
        return
    path = pending["path"]
    operation = pending["operation"]
    if granted:
        from security.sandbox_policy import SandboxPolicy

        policy = SandboxPolicy.load_default()
        mode = "readwrite" if operation == "write" else "read"
        policy.grant_folder(path, mode=mode)
        await orchestrator._send_text(session_id, f"Access granted to `{path}` ({mode}). I can now work with files there.")
    else:
        await orchestrator._send_text(session_id, f"Access to `{path}` was denied. I won't access that path.")


async def handle_daemon_result(orchestrator, node_id: str, result: dict, session_id: str = None):
    request_id = result.get("request_id", "")
    success = result.get("success", False)
    data = result.get("data", {})
    output = data.get("output", "") if isinstance(data, dict) else str(data)
    error = data.get("error", "") if isinstance(data, dict) else ""
    if not output:
        output = result.get("stdout", "")
    if not error:
        error = result.get("stderr", result.get("error", ""))
    status = "success" if success else result.get("status", "error")
    logger.info(f"Daemon {node_id} -> {status}: {str(output)[:200]}")

    ack_payload = {
        "success": bool(success),
        "status_code": 200 if success else 500,
        "data": {"output": output} if output else (data if isinstance(data, dict) else None),
        "error": error or None,
    }
    try:
        orchestrator.tool_runner.resolve_daemon_ack(request_id, ack_payload)
    except Exception:
        pass

    daemon_session_map = orchestrator.tool_runner._daemon_session_map
    if not session_id:
        if request_id and request_id in daemon_session_map:
            session_id = daemon_session_map.pop(request_id)
        else:
            for req_id, sid in list(daemon_session_map.items()):
                session_id = sid
                del daemon_session_map[req_id]
                break

    if session_id:
        if status == "success":
            sdui = {
                "type": "VStack",
                "spacing": 12,
                "padding": 20,
                "children": [
                    {
                        "type": "HStack",
                        "spacing": 10,
                        "children": [
                            {"type": "Icon", "name": "checkmark.circle.fill", "size": 24, "color": "#00b894"},
                            {"type": "Text", "value": "Command Executed", "style": "headline", "color": "#00b894"},
                        ],
                    },
                    {"type": "Divider"},
                    {"type": "Text", "value": str(output)[:500] if output else "Done.", "style": "body"},
                ],
            }
        elif status == "denied":
            sdui = {
                "type": "VStack",
                "spacing": 12,
                "padding": 20,
                "children": [
                    {
                        "type": "HStack",
                        "spacing": 10,
                        "children": [
                            {"type": "Icon", "name": "xmark.shield.fill", "size": 24, "color": "#e17055"},
                            {"type": "Text", "value": "Command Denied", "style": "headline", "color": "#e17055"},
                        ],
                    },
                    {"type": "Divider"},
                    {
                        "type": "Text",
                        "value": error or "Blocked by security policy",
                        "style": "body",
                        "color": "#e17055",
                    },
                ],
            }
        else:
            sdui = {
                "type": "VStack",
                "spacing": 12,
                "padding": 20,
                "children": [
                    {
                        "type": "HStack",
                        "spacing": 10,
                        "children": [
                            {
                                "type": "Icon",
                                "name": "exclamationmark.triangle.fill",
                                "size": 24,
                                "color": "#fdcb6e",
                            },
                            {"type": "Text", "value": "Command Error", "style": "headline", "color": "#fdcb6e"},
                        ],
                    },
                    {"type": "Divider"},
                    {"type": "Text", "value": error or str(output) or "Unknown error", "style": "body"},
                ],
            }

        await orchestrator.send(
            session_id,
            FeralMessage(
                session_id=session_id,
                hop="brain",
                type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ),
        )
