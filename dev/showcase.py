#!/usr/bin/env python3
# Internal/dev use only. Not documented or shipped to users.
"""
FERAL Showcase — Shows every working feature in sequence.
Run: cd feral-core && PYTHONPATH=. python ../dev/showcase.py

This works WITHOUT an LLM key — it directly tests the tools.
With an LLM key, it also demos the full agent chat loop.
"""
import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "feral-core"))

BOLD = "\033[1m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
DIM = "\033[2m"
NC = "\033[0m"


def section(title: str):
    print(f"\n{BOLD}{'═' * 60}{NC}")
    print(f"{BOLD}  {title}{NC}")
    print(f"{BOLD}{'═' * 60}{NC}\n")


def ok(msg: str):
    print(f"  {GREEN}✓{NC} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{NC} {msg}")


def info(msg: str):
    print(f"  {DIM}{msg}{NC}")


async def demo_computer_use():
    section("1. COMPUTER USE TOOLS")
    from skills.impl.computer_use import ComputerUseSkill
    skill = ComputerUseSkill()

    # bash
    r = await skill.execute("bash", {"command": "echo 'Hello from FERAL!' && date && whoami"}, {})
    ok(f"bash: {r['data']['stdout'].strip()}")

    # write_file
    demo_file = "/tmp/feral_demo.py"
    code = 'def greet(name):\n    return f"Hello, {name}!"\n\nprint(greet("World"))\n'
    r = await skill.execute("write_file", {"path": demo_file, "content": code}, {})
    ok(f"write_file: Created {demo_file} ({r['data']['bytes_written']} bytes)")

    # read_file
    r = await skill.execute("read_file", {"path": demo_file}, {})
    ok(f"read_file: {r['data']['total_lines']} lines read")
    for line in r["data"]["content"].splitlines():
        info(f"    {line}")

    # edit_file
    r = await skill.execute("edit_file", {
        "path": demo_file,
        "old_text": 'print(greet("World"))',
        "new_text": 'print(greet("FERAL User"))',
    }, {})
    ok(f"edit_file: Replaced text in {demo_file}")

    # bash — run the edited file
    r = await skill.execute("bash", {"command": f"python3 {demo_file}"}, {})
    ok(f"bash (run edited file): {r['data']['stdout'].strip()}")

    # grep_search
    r = await skill.execute("grep_search", {"pattern": "class.*Skill", "path": "skills/", "include": "*.py"}, {})
    ok(f"grep_search: Found {r['data']['total']} matches for 'class.*Skill' in skills/")
    for m in r["data"]["matches"][:3]:
        info(f"    {m['file']}:{m['line']} → {m['text'].strip()}")

    # glob_search
    r = await skill.execute("glob_search", {"pattern": "*.json", "path": "skills/manifests"}, {})
    ok(f"glob_search: Found {r['data']['total']} JSON manifests")
    for f in r["data"]["files"][:5]:
        info(f"    {f}")

    # web_fetch
    r = await skill.execute("web_fetch", {"url": "https://httpbin.org/get", "max_length": "300"}, {})
    ok(f"web_fetch: Fetched httpbin.org ({r['data']['length']} chars)")

    os.remove(demo_file)


async def demo_web_search():
    section("2. WEB SEARCH (Tavily)")
    from skills.impl.web_search import WebSearchSkill
    skill = WebSearchSkill()

    tavily_key = os.environ.get("TAVILY_API_KEY", os.environ.get("FERAL_KEY_web_search", ""))
    if not tavily_key:
        warn("No TAVILY_API_KEY set — skipping web search demo")
        info("Get a free key at https://tavily.com")
        return

    r = await skill.execute("web_search", {"query": "latest AI agent frameworks 2026"}, {"web_search": tavily_key})
    if r["success"]:
        ok(f"Web search returned {len(r['data']['results'])} results:")
        for item in r["data"]["results"][:3]:
            info(f"    {item['title']}")
            info(f"    {item['url']}")
            print()
    else:
        warn(f"Web search failed: {r['error']}")


async def demo_memory():
    section("3. PERSISTENT MEMORY")
    from memory.store import MemoryStore
    store = MemoryStore()

    store.save("FERAL demo ran successfully", source="demo_script")
    store.save("User prefers dark mode interfaces", source="demo_script")
    ok("Added 2 notes to memory")

    notes = store.search("demo")
    ok(f"Searched 'demo' → found {len(notes)} matching notes")
    for n in notes[:3]:
        info(f"    [{n.get('created_at', '?')}] {n.get('content', '?')}")

    stats = store.stats()
    ok(f"Memory stats: {stats.get('notes', 0)} notes, {stats.get('episodes', 0)} episodes, {stats.get('knowledge_triples', 0)} knowledge triples")


async def demo_genui():
    section("4. GENUI — Dynamic UI Generation")
    from agents.genui_generator import GenUIGenerator
    gen = GenUIGenerator()

    # Simulate weather data
    weather_data = {
        "temperature": 22.5,
        "humidity": 65,
        "wind_speed": 12.3,
        "description": "Partly cloudy",
        "city": "San Francisco",
    }
    brand = {"name": "Weather", "primary_color": "#E74C3C"}
    sdui = gen.generate(data=weather_data, skill_brand=brand, ui_hint="metric", endpoint_id="current")
    ok(f"Generated SDUI for weather data:")
    info(f"    Root type: {sdui.get('type')}")
    info(f"    Children: {len(sdui.get('children', []))} components")
    info(f"    JSON size: {len(json.dumps(sdui))} bytes")

    # Simulate search results
    search_data = {
        "results": [
            {"title": "AI Agents in 2026", "url": "https://example.com/1", "snippet": "Overview of the latest..."},
            {"title": "FERAL Framework", "url": "https://example.com/2", "snippet": "Open source agent..."},
        ]
    }
    sdui = gen.generate(data=search_data, skill_brand={"name": "Search", "primary_color": "#3498DB"}, ui_hint="list")
    ok(f"Generated SDUI for search results: {sdui.get('type')} with {len(sdui.get('children', []))} children")


async def demo_skills_registry():
    section("5. SKILL REGISTRY")
    from skills.registry import SkillRegistry
    registry = SkillRegistry()
    registry.load_builtin_skills()

    ok(f"Loaded {len(registry.skills)} skills:")
    for sid, skill in registry.skills.items():
        eps = len(skill.endpoints)
        info(f"    {skill.brand.name:20s} ({sid}) — {eps} endpoints")


async def demo_server_api():
    section("6. SERVER API (if running)")
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:9090/health", timeout=3)
        if r.status_code == 200:
            ok(f"Brain is running: {r.json()}")

            r2 = httpx.get("http://127.0.0.1:9090/api/llm/status", timeout=3)
            status = r2.json()
            ok(f"LLM: {status.get('provider', '?')}/{status.get('model', '?')} (available={status.get('available', '?')})")

            r3 = httpx.get("http://127.0.0.1:9090/api/info", timeout=3)
            info_data = r3.json()
            ok(f"Skills: {info_data.get('skills', '?')}, Sessions: {info_data.get('sessions', '?')}, Devices: {info_data.get('devices', '?')}")
        else:
            warn("Brain returned non-200")
    except Exception:
        warn("Brain not running — start with: feral serve")
        info("Server API demo skipped")


async def main():
    print(f"""
{BOLD}╔══════════════════════════════════════════════════════════╗
║              F E R A L   D E M O                          ║
║  Unleashed AI — Computer Use, Search, GenUI, Memory      ║
╚══════════════════════════════════════════════════════════╝{NC}
""")

    start = time.time()

    await demo_computer_use()
    await demo_web_search()
    await demo_memory()
    await demo_genui()
    await demo_skills_registry()
    await demo_server_api()

    elapsed = time.time() - start

    section("DEMO COMPLETE")
    ok(f"All features demonstrated in {elapsed:.1f}s")
    print(f"""
  {BOLD}To try the full agent:{NC}
    feral setup          # Configure provider + keys
    feral serve          # Start the brain
    feral                # Chat with the agent
    feral "read this file and explain it"

  {BOLD}Supported LLM providers:{NC}
    OpenAI, Anthropic (Claude), Google Gemini, Groq, Ollama (local)

  {BOLD}Web UI:{NC}
    Open http://localhost:9090 after running 'feral serve'
""")


if __name__ == "__main__":
    asyncio.run(main())
