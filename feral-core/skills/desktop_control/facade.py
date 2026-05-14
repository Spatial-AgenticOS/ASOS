"""Phase 11 (audit-r10 overhaul) — desktop_control facade.

High-level brain-host actions that map to the operator's complaints:

* ``desktop.facetime.start``  — close operator complaint #8 ("call my
  friend on my Mac and use FaceTime") on the Mac side; the iOS half
  is `CallKitSkill` from Phase 4a.
* ``desktop.music.play`` / ``desktop.music.pause`` — symmetric
  surface with Phase 4b ``MusicKitSkill`` so the brain can pick
  whichever device is currently playing audio.
* ``desktop.messages.send`` — iMessage via Messages.app + AppleScript.
* ``desktop.notes.create`` — append a note to Apple Notes without
  resorting to the iOS NotesSkill workaround.
* ``desktop.url.open``     — open any URL in the default browser.
* ``desktop.app.launch`` / ``desktop.app.activate`` / ``desktop.app.list``.
* ``desktop.notify``       — system notification banner.

Each action carries a `target_bundle` so the AppleScript runner can
mint a structured `tcc_denied:automation:<bundle>` token if macOS
hasn't granted Automation access to that target yet. The orchestrator
turns that token into a ``tcc_card`` SDUI element via
``agents/tcc_card.py``.

The dispatcher is intentionally pure-function: it doesn't depend on
``BrainState``, the orchestrator, or any client connection. The
caller (``ToolRunner.execute_capability_action`` for brain_host
handlers) hands in the action name + params and gets back a
standard tool envelope.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from typing import Any

from .applescript import (
    AppleScriptResult,
    AppleScriptUnsupportedPlatform,
    run_applescript,
)

logger = logging.getLogger("feral.desktop_control.facade")


# ─── Manifests (consumed by CapabilityRegistry as brain-host skills) ─


BRAIN_HOST_MANIFESTS: list[dict] = [
    {
        "id": "desktop_facetime",
        "name": "Mac FaceTime",
        "description": (
            "Place FaceTime audio/video calls from the operator's "
            "Mac via the FaceTime app. Symmetric with the iPhone "
            "CallKit skill — the brain picks whichever surface is "
            "currently the operator's primary."
        ),
        "actions": [
            {
                "name": "desktop.facetime.start",
                "summary": (
                    "Place a FaceTime call. Params: { contact: string "
                    "(phone/email/AppleID), video?: bool }."
                ),
                "requires_permission": "automation:com.apple.FaceTime",
            },
        ],
    },
    {
        "id": "desktop_music",
        "name": "Mac Music",
        "description": "Control Music.app on the Mac via AppleScript.",
        "actions": [
            {
                "name": "desktop.music.play",
                "summary": "Search Apple Music library/catalog and play. Params: { query?: string }.",
                "requires_permission": "automation:com.apple.Music",
            },
            {
                "name": "desktop.music.pause",
                "summary": "Pause Music.app playback.",
                "requires_permission": "automation:com.apple.Music",
            },
        ],
    },
    {
        "id": "desktop_messages",
        "name": "Mac Messages",
        "description": "Send iMessage / SMS from Messages.app.",
        "actions": [
            {
                "name": "desktop.messages.send",
                "summary": (
                    "Send a message. Params: { to: string "
                    "(phone or email), body: string }."
                ),
                "requires_permission": "automation:com.apple.MobileSMS",
            },
        ],
    },
    {
        "id": "desktop_notes",
        "name": "Mac Notes",
        "description": "Create or append to a note in Apple Notes.",
        "actions": [
            {
                "name": "desktop.notes.create",
                "summary": (
                    "Create a note. Params: { title: string, body?: string, "
                    "folder?: string }."
                ),
                "requires_permission": "automation:com.apple.Notes",
            },
        ],
    },
    {
        "id": "desktop_url",
        "name": "Open URL",
        "description": "Open a URL in the system default browser.",
        "actions": [
            {
                "name": "desktop.url.open",
                "summary": "Open a URL. Params: { url: string }.",
                "requires_permission": None,
            },
        ],
    },
    {
        "id": "desktop_app",
        "name": "Mac Apps",
        "description": "Launch, activate, or list running apps.",
        "actions": [
            {
                "name": "desktop.app.launch",
                "summary": "Open an app by name. Params: { name: string }.",
                "requires_permission": None,
            },
            {
                "name": "desktop.app.activate",
                "summary": "Bring an app to the front. Params: { name: string }.",
                "requires_permission": "automation:com.apple.systemevents",
            },
            {
                "name": "desktop.app.list",
                "summary": "List currently running app names.",
                "requires_permission": "automation:com.apple.systemevents",
            },
        ],
    },
    {
        "id": "desktop_notify",
        "name": "Mac Notify",
        "description": "Display a system notification banner.",
        "actions": [
            {
                "name": "desktop.notify",
                "summary": "Show a banner. Params: { title: string, body?: string, subtitle?: string }.",
                "requires_permission": None,
            },
        ],
    },
]


# ─── Dispatcher ──────────────────────────────────────────────────


def dispatch_desktop_action(name: str, params: dict[str, Any] | None) -> dict:
    """Route an ``desktop.*`` action to its facade implementation and
    return a standard tool envelope.

    Caller (``ToolRunner.execute_capability_action``) invokes this
    when the capability registry's ``find_handler`` returns a
    brain-host handler. Returns dicts shaped like:

        {"success": bool, "status_code": int,
         "error": str (optional), "data": dict (optional)}
    """
    params = params or {}
    try:
        if name == "desktop.facetime.start":
            return _facetime_start(params)
        if name == "desktop.music.play":
            return _music_play(params)
        if name == "desktop.music.pause":
            return _music_pause()
        if name == "desktop.messages.send":
            return _messages_send(params)
        if name == "desktop.notes.create":
            return _notes_create(params)
        if name == "desktop.url.open":
            return _url_open(params)
        if name == "desktop.app.launch":
            return _app_launch(params)
        if name == "desktop.app.activate":
            return _app_activate(params)
        if name == "desktop.app.list":
            return _app_list()
        if name == "desktop.notify":
            return _notify(params)
    except AppleScriptUnsupportedPlatform as exc:
        return {
            "success": False,
            "status_code": 503,
            "error": f"desktop_control not available: {exc}",
        }
    except Exception as exc:  # noqa: BLE001 — never let the orchestrator crash
        logger.exception("desktop_control action %s raised", name)
        return {
            "success": False,
            "status_code": 500,
            "error": f"desktop_control {name} raised: {exc}",
        }
    return {
        "success": False,
        "status_code": 404,
        "error": f"unknown desktop_control action: {name}",
    }


def _require(params: dict, key: str) -> str:
    v = params.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"`{key}` is required and must be a non-empty string")
    return v.strip()


def _applescript_literal(value: str) -> str:
    """Escape a Python string for embedding inside AppleScript double quotes."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _facetime_start(params: dict) -> dict:
    contact = _require(params, "contact")
    video = bool(params.get("video", False))
    # AppleScript's `tell FaceTime` lacks a direct dial command on
    # modern macOS; the reliable surface is the `facetime://` /
    # `facetime-audio://` URL scheme handled by FaceTime.app. Using
    # `open` instead of AppleScript here also sidesteps the
    # Automation TCC requirement entirely.
    scheme = "facetime" if video else "facetime-audio"
    url = f"{scheme}://{contact}"
    try:
        completed = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False, "status_code": 504,
            "error": "FaceTime open timed out",
        }
    if completed.returncode != 0:
        return {
            "success": False,
            "status_code": 500,
            "error": (completed.stderr or "open").strip(),
        }
    return {
        "success": True, "status_code": 200,
        "data": {"contact": contact, "scheme": scheme},
    }


def _music_play(params: dict) -> dict:
    query = (params.get("query") or "").strip()
    if query:
        # Play the first track matching the query.
        escaped = _applescript_literal(query)
        script = f'''
        tell application "Music"
            activate
            set theTracks to (every track of library playlist 1 whose name contains "{escaped}" or artist contains "{escaped}")
            if (count of theTracks) > 0 then
                play item 1 of theTracks
                return ("playing " & name of item 1 of theTracks)
            else
                return "no library match for {escaped}"
            end if
        end tell
        '''
    else:
        script = '''
        tell application "Music"
            activate
            play
            return ("playing " & name of current track)
        end tell
        '''
    return run_applescript(
        script,
        target_bundle="com.apple.Music",
    ).to_envelope(action="desktop.music.play")


def _music_pause() -> dict:
    script = 'tell application "Music" to pause'
    return run_applescript(
        script,
        target_bundle="com.apple.Music",
    ).to_envelope(action="desktop.music.pause")


def _messages_send(params: dict) -> dict:
    to = _require(params, "to")
    body = _require(params, "body")
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{_applescript_literal(to)}" of targetService
        send "{_applescript_literal(body)}" to targetBuddy
    end tell
    '''
    return run_applescript(
        script,
        target_bundle="com.apple.MobileSMS",
    ).to_envelope(action="desktop.messages.send")


def _notes_create(params: dict) -> dict:
    title = _require(params, "title")
    body = params.get("body", "")
    folder = params.get("folder", "")
    if folder:
        script = f'''
        tell application "Notes"
            tell folder "{_applescript_literal(folder)}"
                make new note with properties {{name: "{_applescript_literal(title)}", body: "{_applescript_literal(body)}"}}
            end tell
        end tell
        '''
    else:
        script = f'''
        tell application "Notes"
            make new note with properties {{name: "{_applescript_literal(title)}", body: "{_applescript_literal(body)}"}}
        end tell
        '''
    return run_applescript(
        script,
        target_bundle="com.apple.Notes",
    ).to_envelope(action="desktop.notes.create")


def _url_open(params: dict) -> dict:
    url = _require(params, "url")
    try:
        completed = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "status_code": 504, "error": "open timed out"}
    if completed.returncode != 0:
        return {
            "success": False,
            "status_code": 500,
            "error": (completed.stderr or "open").strip(),
        }
    return {"success": True, "status_code": 200, "data": {"url": url}}


def _app_launch(params: dict) -> dict:
    name = _require(params, "name")
    # `open -a` works without Automation TCC — it's a launchd path.
    try:
        completed = subprocess.run(
            ["open", "-a", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "status_code": 504, "error": "open -a timed out"}
    if completed.returncode != 0:
        return {
            "success": False,
            "status_code": 500,
            "error": (completed.stderr or f"could not launch '{name}'").strip(),
        }
    return {"success": True, "status_code": 200, "data": {"name": name}}


def _app_activate(params: dict) -> dict:
    name = _require(params, "name")
    script = f'tell application "{_applescript_literal(name)}" to activate'
    return run_applescript(
        script,
        target_bundle="com.apple.systemevents",
    ).to_envelope(action="desktop.app.activate")


def _app_list() -> dict:
    script = '''
    tell application "System Events"
        set appNames to name of every process whose background only is false
    end tell
    return appNames
    '''
    res = run_applescript(script, target_bundle="com.apple.systemevents")
    env = res.to_envelope(action="desktop.app.list")
    if env.get("success") and isinstance(env.get("data"), dict):
        # osascript returns CSV-ish "App1, App2, App3" — split for callers.
        text = env["data"].get("stdout", "")
        names = [n.strip() for n in text.split(",") if n.strip()]
        env["data"]["apps"] = names
    return env


def _notify(params: dict) -> dict:
    title = _require(params, "title")
    body = params.get("body", "")
    subtitle = params.get("subtitle", "")
    parts = [f'display notification "{_applescript_literal(body)}"',
             f'with title "{_applescript_literal(title)}"']
    if subtitle:
        parts.append(f'subtitle "{_applescript_literal(subtitle)}"')
    script = " ".join(parts)
    # Notifications don't tell another app to do anything; no TCC
    # target bundle. macOS may show its own permission prompt for
    # notification delivery the first time, which is handled by the
    # standard Notifications privacy pane and is out of scope here.
    return run_applescript(script).to_envelope(action="desktop.notify")


# Keep linter happy about the imported `shlex` reference; even though
# the dispatcher uses `subprocess.run` with list-form args (no shell
# interpretation), `shlex` is reserved for future use when we add
# `desktop.shell.run` in Phase 11b.
_ = shlex


__all__ = [
    "BRAIN_HOST_MANIFESTS",
    "dispatch_desktop_action",
]
