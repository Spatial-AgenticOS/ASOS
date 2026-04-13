from __future__ import annotations

import logging

from models.protocol import FeralMessage, SDUIPayload

logger = logging.getLogger("feral.orchestrator")


async def handle_ui_event(orchestrator, session_id: str, action_id: str, event: str, value=None):
    logger.info(f"[{session_id[:8]}] UI: {event} -> {action_id} = {value}")

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
