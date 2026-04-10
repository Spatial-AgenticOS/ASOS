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
import shutil
import sys
from importlib import metadata as importlib_metadata
from urllib.parse import urlparse

try:
    import websockets
except ImportError:
    print("websockets package required. Install: pip install websockets")
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None

from config.loader import theora_home
from config.runtime import (
    brain_bind_host,
    brain_port,
    brain_public_base_url,
    brain_public_host,
    brain_public_port,
    brain_public_scheme,
)


def _runtime_http_base() -> str:
    return brain_public_base_url().rstrip("/")


def _runtime_ws_url() -> str:
    parsed = urlparse(_runtime_http_base())
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{ws_scheme}://{parsed.hostname}{port}/v1/session"


WS_URL = _runtime_ws_url()
HTTP_BASE = _runtime_http_base()

BANNER = """
╔══════════════════════════════════════╗
║          T H E O R A                 ║
║   Spatial Agentic OS  v1.2.0        ║
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


def _installed_pkg_info() -> tuple[str, str]:
    """Return installed package version and location."""
    try:
        version = importlib_metadata.version("theora-asos")
        dist = importlib_metadata.distribution("theora-asos")
        location = str(dist.locate_file(""))
        return version, location
    except Exception:
        return "unknown", "unknown"


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
        print("  Rules:")
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
        print("  Make sure the Brain is running: python api/server.py")
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


def cmd_serve(host: str | None = None, port: int | None = None):
    """Start the THEORA Brain server."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: pip install 'theora-asos[all]'")
        sys.exit(1)

    core_root = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if core_root not in sys.path:
        sys.path.insert(0, core_root)

    host = host or brain_bind_host()
    port = int(port or brain_port())
    public_base = os.getenv("THEORA_PUBLIC_BASE_URL", f"http://localhost:{port}")
    print(f"\n  Starting THEORA Brain on {host}:{port} ...")
    print(f"  Dashboard: {public_base}")
    print(f"  API docs:  {public_base}/docs\n")

    uvicorn.run("api.server:app", host=host, port=port, reload=False, log_level="info")


def _is_first_run() -> bool:
    """Check if this is the first time running THEORA."""
    home_path = theora_home()
    creds_path = home_path / "credentials.json"
    has_creds = creds_path.exists()
    has_env_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
                       or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GROQ_API_KEY"))

    if has_env_key:
        return False

    if has_creds:
        try:
            creds = json.loads(creds_path.read_text())
            if any(v for v in creds.values() if v):
                return False
        except Exception:
            pass

    return True


def cmd_start(port: int | None = None, no_browser: bool = False):
    """
    One command to rule them all.
    Starts the brain, checks health, opens browser, and drops into chat.
    If first run, launches setup wizard first.
    """
    import time
    import threading

    try:
        import uvicorn
    except ImportError:
        print("  Missing dependencies. Run: pip install 'theora-asos[llm]'")
        sys.exit(1)

    port = int(port or brain_port())

    # First run detection — auto-launch setup
    if _is_first_run():
        print()
        print("  First time running THEORA? Let's set you up.\n")
        cmd_setup()
        print()

    # Check if already running
    try:
        health_url = os.getenv("THEORA_HEALTH_URL", f"http://127.0.0.1:{port}/health")
        if httpx:
            r = httpx.get(health_url, timeout=2)
            if r.status_code == 200:
                print(f"  THEORA is already running on port {port}")
                if not no_browser:
                    _open_browser(port)
                asyncio.run(repl())
                return
    except Exception:
        pass

    print(f"""
  ╔══════════════════════════════════════╗
  ║          T H E O R A                 ║
  ║   Starting agent on port {port}       ║
  ╚══════════════════════════════════════╝
""")

    # Start server in background thread
    server_ready = threading.Event()

    def _run_server():
        import uvicorn
        config = uvicorn.Config(
            "api.server:app", host=brain_bind_host(), port=port,
            log_level="warning", access_log=False,
        )
        server = uvicorn.Server(config)
        server_ready.set()
        server.run()

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Wait for server to be healthy
    print("  Starting brain...", end="", flush=True)
    health_url = os.getenv("THEORA_HEALTH_URL", f"http://127.0.0.1:{port}/health")
    for i in range(30):
        time.sleep(1)
        try:
            if httpx:
                r = httpx.get(health_url, timeout=2)
                if r.status_code == 200:
                    break
            else:
                import urllib.request
                urllib.request.urlopen(health_url, timeout=2)
                break
        except Exception:
            print(".", end="", flush=True)
    else:
        print("\n  Failed to start. Check logs or run: theora serve --verbose")
        sys.exit(1)

    # Print status
    data = _http_get("/api/dashboard")
    skills_count = data.get("skills_count", "?")
    llm_ok = "ready" if data.get("llm_available") else "no key"
    mem = data.get("memory", {})
    print("\n  Brain ready!")
    print(f"  LLM: {llm_ok} | Skills: {skills_count} | Memory: {mem.get('notes', 0)} notes")
    print(f"  Dashboard: {os.getenv('THEORA_PUBLIC_BASE_URL', f'http://localhost:{port}')}")

    if not no_browser:
        _open_browser(port)

    print()
    # Drop into interactive chat
    asyncio.run(repl())


def _open_browser(port: int):
    """Open the THEORA dashboard in the default browser."""
    try:
        import webbrowser
        url = os.getenv("THEORA_PUBLIC_BASE_URL", f"http://localhost:{port}")
        webbrowser.open(url)
    except Exception:
        pass


def cmd_doctor():
    """Run diagnostics and report what's working."""
    print("\n  THEORA Doctor")
    print("  " + "=" * 40)

    # Python
    print(f"  Python:        {sys.version.split()[0]}")
    pkg_version, pkg_location = _installed_pkg_info()
    print(f"  Package:       theora-asos {pkg_version}")
    print(f"  Package path:  {pkg_location}")
    print(f"  Python bin:    {sys.executable}")
    print(f"  THEORA bin:    {shutil.which('theora') or 'not found'}")

    # Brain connection
    data = _http_get("/health")
    if "error" in data:
        print("  Brain:         NOT RUNNING")
        print("                 Start with: theora start")
    else:
        print(f"  Brain:         RUNNING (v{data.get('version', '?')})")

    # API keys — check both env and credentials.json
    keys = {
        "OPENAI_API_KEY": "OpenAI",
        "ANTHROPIC_API_KEY": "Anthropic",
        "GOOGLE_API_KEY": "Gemini",
        "OPENROUTER_API_KEY": "OpenRouter",
        "DEEPSEEK_API_KEY": "DeepSeek",
        "MOONSHOT_API_KEY": "Kimi/Moonshot",
        "DASHSCOPE_API_KEY": "Qwen/Alibaba",
        "GROQ_API_KEY": "Groq",
        "EXA_API_KEY": "EXA Search",
        "TAVILY_API_KEY": "Tavily Search",
        "SERPER_API_KEY": "Serper",
        "BRAVE_API_KEY": "Brave Search",
        "OPENWEATHER_API_KEY": "Weather",
        "GITHUB_TOKEN": "GitHub",
        "SPOTIFY_CLIENT_ID": "Spotify",
    }
    creds_data = {}
    creds = theora_home() / "credentials.json"
    if creds.exists():
        try:
            import json as _json
            creds_data = _json.loads(creds.read_text())
        except Exception:
            pass

    print()
    print("  API Keys:")
    any_key = False
    for env, name in keys.items():
        val = os.environ.get(env, "") or creds_data.get(env, "")
        if val:
            masked = val[:8] + "..." + val[-4:] if len(val) > 12 else "***"
            print(f"    {name:20s} {masked}")
            any_key = True
    if not any_key:
        if creds.exists():
            print(f"    (credentials file found at {creds} but no keys set)")
        else:
            print("    NONE — run: theora setup")

    # Dependencies
    print()
    print("  Core deps:")
    for pkg, desc in [
        ("openai", "OpenAI SDK"),
        ("numpy", "NumPy (embeddings)"),
        ("sqlite_vec", "Vector search index"),
        ("pyautogui", "Desktop automation"),
    ]:
        try:
            __import__(pkg)
            print(f"    {desc:20s} installed")
        except ImportError:
            print(f"    {desc:20s} NOT INSTALLED — pip install theora-asos[llm]")

    print()
    print("  Optional deps:")
    for pkg, desc in [
        ("sentence_transformers", "Local embeddings"),
        ("wasmtime", "WASM sandbox"),
        ("zeroconf", "mDNS discovery"),
        ("duckduckgo_search", "DuckDuckGo search"),
        ("PIL", "Image processing"),
        ("exa", "EXA neural search"),
    ]:
        try:
            __import__(pkg)
            print(f"    {desc:20s} installed")
        except ImportError:
            print(f"    {desc:20s} not installed")

    # Docker
    if shutil.which("docker"):
        print(f"    {'Docker':20s} available")
    else:
        print(f"    {'Docker':20s} not installed (sandboxed exec disabled)")

    # Web UI
    from pathlib import Path as _Path
    _webui = _Path(__file__).parent.parent / "webui"
    if _webui.is_dir() and (_webui / "index.html").exists():
        print(f"    {'Web Dashboard':20s} bundled")
    else:
        print(f"    {'Web Dashboard':20s} NOT BUNDLED — run: make bundle-webui")

    print()


def cmd_setup():
    """Launch the guided setup wizard."""
    try:
        from cli.setup_wizard import run_setup
        run_setup()
    except ImportError:
        print("Setup wizard not available. Make sure cli/setup_wizard.py exists.")
        sys.exit(1)


def cmd_wake_test():
    """Test wake word detection from the microphone for 10 seconds."""
    print("\n  Wake Word Test")
    print("  " + "=" * 40)

    try:
        import openwakeword
    except ImportError:
        print("  openwakeword not installed.")
        print("  Install: pip install 'theora-asos[wake]'")
        print("  (Downloads ~50 MB model on first use)")
        sys.exit(1)

    from perception.wake_word import WakeWordDetector, WakeWordConfig
    detector = WakeWordDetector(WakeWordConfig(enabled=True))
    ml_mode = "ML (openwakeword)" if detector._oww_model else "Energy-based fallback"
    print(f"  Mode:   {ml_mode}")
    print(f"  Phrase: {detector._config.phrase}")
    model_name = os.environ.get("THEORA_WAKE_MODEL", "hey_jarvis_v0.1")
    print(f"  Model:  {model_name}")
    print("\n  Listening for 10 seconds... Say the wake phrase!\n")

    try:
        import pyaudio
    except ImportError:
        print("  pyaudio not installed — needed for mic access.")
        print("  Install: pip install pyaudio")
        sys.exit(1)

    import struct
    import time

    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1280)
    start = time.time()
    detections = 0

    try:
        while time.time() - start < 10:
            pcm = stream.read(1280, exception_on_overflow=False)
            result = asyncio.get_event_loop().run_until_complete(
                detector.process_frame("test", pcm)
            ) if asyncio.get_event_loop().is_running() else asyncio.run(
                detector.process_frame("test", pcm)
            )
            if result and detector.get_state("test").value == "activated":
                detections += 1
                elapsed = time.time() - start
                print(f"  [{elapsed:.1f}s] WAKE WORD DETECTED! (#{detections})")
                detector.force_deactivate("test")
            remaining = 10 - (time.time() - start)
            if int(remaining) % 3 == 0 and remaining > 0:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

    print(f"\n  Done. Detections: {detections}")
    if detections == 0 and not detector._oww_model:
        print("  Tip: Install openwakeword for better detection: pip install openwakeword onnxruntime")


def cmd_marketplace(action: str, query: str):
    """Marketplace CLI commands."""
    if action == "search":
        q = query or "all"
        data = _http_get(f"/api/marketplace/search?q={q}")
        results = data.get("results", [])
        if not results:
            print("  No skills found.")
            return
        for s in results:
            print(f"  {s.get('name', s.get('skill_id', '?'))} — {s.get('description', '')[:60]}")
    elif action == "install":
        if not query:
            print("  Usage: theora marketplace install <skill_id>")
            return
        import urllib.request
        req = urllib.request.Request(
            f"{HTTP_BASE}/api/marketplace/install",
            data=json.dumps({"skill_id": query}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                if result.get("success"):
                    print(f"  Installed: {query}")
                else:
                    print(f"  Failed: {result.get('error', 'unknown')}")
        except Exception as e:
            print(f"  Error: {e}")
    elif action == "list":
        data = _http_get("/api/marketplace/installed")
        skills = data.get("skills", [])
        if not skills:
            print("  No marketplace skills installed.")
            return
        for s in skills:
            print(f"  {s.get('name', s.get('skill_id', '?'))} v{s.get('version', '?')}")


def cmd_sync(action: str, file_path: str):
    """Federated sync CLI commands."""
    if action == "status":
        data = _http_get("/api/sync/status")
        if "error" in data:
            print(f"  Error: {data['error']}")
            return
        print(f"  Enabled:     {data.get('enabled', False)}")
        print(f"  Running:     {data.get('running', False)}")
        print(f"  Node ID:     {data.get('node_id', '?')}")
        print(f"  Peers:       {data.get('peer_count', 0)}")
        vc = data.get("vector_clock", {})
        if vc:
            print(f"  Clock:       {json.dumps(vc, indent=2)}")
    elif action == "peers":
        data = _http_get("/api/sync/status")
        peers = data.get("peers", [])
        if not peers:
            print("  No peers discovered.")
        else:
            for p in peers:
                print(f"  - {p}")
    elif action == "export":
        out = file_path or "theora_memory_export.json"
        data = _http_get("/api/sync/status")
        if data.get("enabled"):
            print(f"  Exporting memory bundle to {out}...")
            import urllib.request
            req = urllib.request.Request(f"{HTTP_BASE}/api/sync/export")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    bundle = resp.read()
                    with open(out, "wb") as f:
                        f.write(bundle)
                    print(f"  Exported to {out}")
            except Exception as e:
                print(f"  Export failed: {e}")
        else:
            print("  Sync engine not running.")
    elif action == "import":
        if not file_path:
            print("  Usage: theora sync import <file.json>")
            return
        print(f"  Importing from {file_path}...")
        try:
            with open(file_path) as f:
                bundle = json.load(f)
            import urllib.request
            req = urllib.request.Request(
                f"{HTTP_BASE}/api/sync/import",
                data=json.dumps(bundle).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                print(f"  Imported {result.get('applied', 0)} operations")
        except Exception as e:
            print(f"  Import failed: {e}")


def _apply_connection_args(args):
    global WS_URL, HTTP_BASE
    host = getattr(args, "host", None) or brain_public_host()
    port = str(getattr(args, "port", None) or brain_public_port())
    http_scheme = "https" if brain_public_scheme() == "https" else "http"
    ws_scheme = "wss" if http_scheme == "https" else "ws"
    origin = f"{host}:{port}"
    WS_URL = f"{ws_scheme}://{origin}/v1/session"
    HTTP_BASE = f"{http_scheme}://{origin}"


def main():
    parser = argparse.ArgumentParser(
        description="THEORA — Open AI agent with computer use, voice, GenUI, and hardware control",
        usage="theora [command] [options]",
    )
    parser.add_argument("--host", default=None, help="Brain hostname")
    parser.add_argument("--port", default=None, help="Brain port")

    sub = parser.add_subparsers(dest="subcommand")

    # theora start (THE main command)
    start_p = sub.add_parser("start", help="Start THEORA — brain + dashboard + chat in one command")
    start_p.add_argument("--serve-port", default=str(brain_port()), help=f"Port (default {brain_port()})")
    start_p.add_argument("--no-browser", action="store_true", help="Don't open browser")

    # theora serve (headless server only)
    serve_p = sub.add_parser("serve", help="Start the brain server (headless, no chat)")
    serve_p.add_argument("--bind", default=brain_bind_host(), help=f"Bind address (default {brain_bind_host()})")
    serve_p.add_argument("--serve-port", default=str(brain_port()), help=f"Port (default {brain_port()})")

    # theora setup
    sub.add_parser("setup", help="Guided setup wizard — configure provider, keys, features")

    # theora doctor
    sub.add_parser("doctor", help="Run diagnostics — check deps, keys, brain health")

    # theora status / devices / skills / identity
    sub.add_parser("status", help="Show system health")
    sub.add_parser("devices", help="List connected hardware")
    sub.add_parser("skills", help="List loaded skills")
    sub.add_parser("identity", help="Show agent identity")

    # theora wake-test
    sub.add_parser("wake-test", help="Test wake word detection from your microphone")

    # theora marketplace
    mp = sub.add_parser("marketplace", help="Skill marketplace commands")
    mp.add_argument("action", nargs="?", default="search", choices=["search", "install", "list"], help="Action")
    mp.add_argument("query", nargs="?", default="", help="Search query or skill ID")

    # theora sync
    sp = sub.add_parser("sync", help="Federated memory sync commands")
    sp.add_argument("action", nargs="?", default="status", choices=["status", "peers", "export", "import"], help="Action")
    sp.add_argument("file", nargs="?", default="", help="File path for export/import")

    # Parse known args — everything else is treated as a message
    args, remaining = parser.parse_known_args()
    _apply_connection_args(args)

    if args.subcommand == "start":
        cmd_start(port=int(args.serve_port), no_browser=args.no_browser)
    elif args.subcommand == "serve":
        cmd_serve(host=args.bind, port=int(args.serve_port))
    elif args.subcommand == "setup":
        cmd_setup()
    elif args.subcommand == "doctor":
        cmd_doctor()
    elif args.subcommand == "status":
        cmd_status()
    elif args.subcommand == "devices":
        cmd_devices()
    elif args.subcommand == "skills":
        cmd_skills()
    elif args.subcommand == "identity":
        cmd_identity()
    elif args.subcommand == "wake-test":
        cmd_wake_test()
    elif args.subcommand == "marketplace":
        cmd_marketplace(args.action, args.query)
    elif args.subcommand == "sync":
        cmd_sync(args.action, getattr(args, "file", ""))
    elif args.subcommand is None and not remaining:
        asyncio.run(repl())
    else:
        full_text = " ".join([args.subcommand or ""] + remaining).strip()
        if full_text:
            asyncio.run(one_shot(full_text))
        else:
            asyncio.run(repl())


if __name__ == "__main__":
    main()
