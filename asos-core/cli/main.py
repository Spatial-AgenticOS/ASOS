#!/usr/bin/env python3
"""
THEORA CLI — Interactive Terminal Agent
========================================
Connects to the THEORA Brain via the same WebSocket used by the web client.

Usage:
    theora                          # Interactive REPL
    theora "search the web for X"   # One-shot command
    theora status                   # System health
    theora devices                  # List connected hardware
    theora skills                   # List loaded skills
    theora identity                 # Show/edit agent identity
"""

import argparse
import asyncio
import json
import os
import sys

try:
    import websockets
except ImportError:
    print("websockets package required. Install: pip install websockets")
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None

BRAIN_HOST = os.environ.get("THEORA_BRAIN_HOST", "localhost")
BRAIN_PORT = os.environ.get("THEORA_BRAIN_PORT", "9090")
WS_URL = f"ws://{BRAIN_HOST}:{BRAIN_PORT}/v1/session"
HTTP_BASE = f"http://{BRAIN_HOST}:{BRAIN_PORT}"

BANNER = """
╔══════════════════════════════════════╗
║          T H E O R A  CLI            ║
║   Local-First Agentic OS  v1.0.0    ║
╚══════════════════════════════════════╝
  Type a message to chat. Commands:
    /status   — system health
    /devices  — connected hardware
    /skills   — loaded skills
    /identity — agent identity
    /quit     — exit
"""


def _http_get(path: str) -> dict:
    """Quick synchronous HTTP GET to the Brain REST API."""
    if httpx:
        try:
            r = httpx.get(f"{HTTP_BASE}{path}", timeout=5)
            return r.json()
        except Exception as e:
            return {"error": str(e)}
    try:
        import urllib.request
        req = urllib.request.Request(f"{HTTP_BASE}{path}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def cmd_status():
    data = _http_get("/api/dashboard")
    if "error" in data:
        print(f"  Error: {data['error']}")
        return
    print(f"  Sessions:   {data.get('session_count', '?')}")
    print(f"  Devices:    {data.get('device_count', '?')}")
    print(f"  Skills:     {data.get('skills_count', '?')}")
    print(f"  LLM:        {'ready' if data.get('llm_available') else 'not connected'}")
    print(f"  Audio:      {'ready' if data.get('audio_available') else 'off'}")
    print(f"  WASM:       {'ready' if data.get('wasm_available') else 'disabled'}")
    print(f"  Wake Word:  {'on' if data.get('wake_word_enabled') else 'off'}")
    sync = data.get("sync", {})
    print(f"  Sync:       {'running' if sync.get('running') else 'off'} ({sync.get('peer_count', 0)} peers)")
    mem = data.get("memory", {})
    print(f"  Memory:     {mem.get('notes', 0)} notes, {mem.get('episodes', 0)} episodes, {mem.get('knowledge_triples', 0)} knowledge")


def cmd_devices():
    data = _http_get("/api/devices")
    devices = data.get("devices", [])
    if not devices:
        print("  No devices connected.")
        return
    for d in devices:
        status = "connected" if d.get("connected") else "disconnected"
        print(f"  [{status}] {d.get('node_id', '?')} — {d.get('type', 'unknown')}")


def cmd_skills():
    data = _http_get("/skills")
    if isinstance(data, list):
        if not data:
            print("  No skills loaded.")
            return
        for s in data:
            print(f"  {s['name']} ({s['skill_id']}) — {s.get('endpoints', 0)} endpoints")
    else:
        print(f"  Error: {data.get('error', 'unknown')}")


def cmd_identity():
    data = _http_get("/api/identity")
    if "error" in data:
        print(f"  Error: {data['error']}")
        return
    print(f"  Name:        {data.get('name', '?')}")
    print(f"  Tagline:     {data.get('tagline', '?')}")
    print(f"  Personality: {data.get('personality', '?')}")
    rules = data.get("rules", [])
    if rules:
        print(f"  Rules:")
        for r in rules:
            print(f"    - {r}")
    style = data.get("communication_style", {})
    if style:
        print(f"  Style:       tone={style.get('tone', '?')}, verbosity={style.get('verbosity', '?')}")


async def repl():
    """Interactive REPL that chats with the Brain."""
    print(BANNER)
    uri = WS_URL
    try:
        async with websockets.connect(uri) as ws:
            greeting = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(greeting)
            if msg.get("payload", {}).get("text"):
                print(f"  THEORA: {msg['payload']['text']}\n")

            while True:
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(None, lambda: input("you > "))
                except (EOFError, KeyboardInterrupt):
                    print("\n  Goodbye!")
                    break

                text = user_input.strip()
                if not text:
                    continue

                if text.startswith("/"):
                    cmd = text.lower().split()[0]
                    if cmd in ("/quit", "/exit", "/q"):
                        print("  Goodbye!")
                        break
                    elif cmd == "/status":
                        cmd_status()
                    elif cmd == "/devices":
                        cmd_devices()
                    elif cmd == "/skills":
                        cmd_skills()
                    elif cmd == "/identity":
                        cmd_identity()
                    else:
                        print(f"  Unknown command: {cmd}")
                    continue

                await ws.send(json.dumps({
                    "type": "text_command",
                    "payload": {"text": text},
                }))

                full_response = ""
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        if full_response:
                            break
                        print("  (timeout waiting for response)")
                        break

                    msg = json.loads(raw)
                    mtype = msg.get("type", "")

                    if mtype == "stream_delta":
                        delta = msg.get("payload", {}).get("delta", "")
                        print(delta, end="", flush=True)
                        full_response += delta
                    elif mtype == "stream_end":
                        if full_response:
                            print()
                        break
                    elif mtype == "text_response":
                        text_resp = msg.get("payload", {}).get("text", "")
                        if text_resp:
                            print(f"  THEORA: {text_resp}")
                        break
                    elif mtype == "sdui":
                        print(f"  [UI Component: {msg.get('payload', {}).get('component', '?')}]")
                        break
                    elif mtype == "error":
                        print(f"  Error: {msg.get('payload', {}).get('message', '?')}")
                        break

                print()

    except ConnectionRefusedError:
        print(f"  Cannot connect to THEORA Brain at {uri}")
        print(f"  Make sure the Brain is running: python api/server.py")
        sys.exit(1)
    except Exception as e:
        print(f"  Connection error: {e}")
        sys.exit(1)


async def one_shot(text: str):
    """Send a single command and print the response."""
    try:
        async with websockets.connect(WS_URL) as ws:
            _ = await asyncio.wait_for(ws.recv(), timeout=5)

            await ws.send(json.dumps({
                "type": "text_command",
                "payload": {"text": text},
            }))

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    break

                msg = json.loads(raw)
                mtype = msg.get("type", "")

                if mtype == "stream_delta":
                    print(msg.get("payload", {}).get("delta", ""), end="", flush=True)
                elif mtype == "stream_end":
                    print()
                    break
                elif mtype == "text_response":
                    print(msg.get("payload", {}).get("text", ""))
                    break
                elif mtype == "error":
                    print(f"Error: {msg.get('payload', {}).get('message', '?')}", file=sys.stderr)
                    break

    except ConnectionRefusedError:
        print(f"Cannot connect to THEORA Brain at {WS_URL}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="THEORA CLI — Terminal interface for the THEORA Brain",
        usage="theora [command] [message]",
    )
    parser.add_argument("command", nargs="?", default=None,
                        help="Built-in command (status, devices, skills, identity) or message to send")
    parser.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--host", default=None, help="Brain hostname")
    parser.add_argument("--port", default=None, help="Brain port")

    args = parser.parse_args()

    global WS_URL, HTTP_BASE
    if args.host:
        host = args.host
        port = args.port or BRAIN_PORT
        WS_URL = f"ws://{host}:{port}/v1/session"
        HTTP_BASE = f"http://{host}:{port}"
    elif args.port:
        port = args.port
        WS_URL = f"ws://{BRAIN_HOST}:{port}/v1/session"
        HTTP_BASE = f"http://{BRAIN_HOST}:{port}"

    if args.command is None:
        asyncio.run(repl())
    elif args.command == "status":
        cmd_status()
    elif args.command == "devices":
        cmd_devices()
    elif args.command == "skills":
        cmd_skills()
    elif args.command == "identity":
        cmd_identity()
    else:
        full_text = args.command
        if args.rest:
            full_text += " " + " ".join(args.rest)
        asyncio.run(one_shot(full_text))


if __name__ == "__main__":
    main()
