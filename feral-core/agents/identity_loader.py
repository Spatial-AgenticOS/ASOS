"""
Identity and system-prompt construction for the FERAL orchestrator.

Loads agent personality from ~/.feral/ files (IDENTITY.yaml, USER.md,
SOUL.md, MEMORY.md) and assembles the full system prompt injected into
every LLM conversation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import TYPE_CHECKING

from config.loader import feral_home

if TYPE_CHECKING:
    from memory.store import MemoryStore
    from models.skill_manifest import SkillManifest
    from perception.fusion import PerceptionFrame
    from perception.somatic import SomaticEngine

logger = logging.getLogger("feral.orchestrator.identity")

# Bounded in-memory ring of every `## Memory` block we assembled during a
# session. Small (20 entries) so the /api/memory/context endpoint can prove
# to the user that multi-memory really does fire per turn. We keep this on
# the class (not a global) but flatten it to a module-level ring for quick
# cross-session retrieval by the inspector.
_SNAPSHOT_RING_MAX = 50
_memory_snapshots: deque[dict] = deque(maxlen=_SNAPSHOT_RING_MAX)


def record_memory_snapshot(entry: dict) -> None:
    """Append a rendered memory-context snapshot to the inspector ring."""
    _memory_snapshots.append(entry)


def recent_memory_snapshots(limit: int = 20) -> list[dict]:
    """Return the latest memory-context snapshots, newest first."""
    ordered = list(_memory_snapshots)
    ordered.reverse()
    return ordered[:limit]


def clear_memory_snapshots() -> None:
    """Drop every cached snapshot — used by tests."""
    _memory_snapshots.clear()


class IdentityLoader:
    """Loads agent identity files and builds the LLM system prompt."""

    def __init__(self, memory: "MemoryStore | None" = None, somatic_engine: "SomaticEngine | None" = None):
        self.memory = memory
        self.somatic_engine: SomaticEngine | None = somatic_engine

    def load_identity(self) -> str:
        """Load agent identity from ~/.feral/ files: IDENTITY.yaml, USER.md, SOUL.md, MEMORY.md."""
        home = feral_home()
        parts: list[str] = []

        # 1. IDENTITY.yaml — agent name, personality, rules
        for p in (home / "identity.yaml", home / "identity.yml", home / "IDENTITY.yaml"):
            if p.exists():
                try:
                    import yaml
                    with open(p) as f:
                        data = yaml.safe_load(f) or {}
                    name = data.get("name", "FERAL")
                    tagline = data.get("tagline", "")
                    personality = data.get("personality", "")
                    rules = data.get("rules", [])
                    greeting_style = data.get("greeting_style", "")

                    parts.append(f"You are {name}.")
                    if tagline:
                        parts.append(tagline)
                    if personality:
                        parts.append(f"\n## Personality\n{personality}")
                    if rules:
                        parts.append("\n## Rules\n" + "\n".join(f"- {r}" for r in rules))
                    if greeting_style:
                        parts.append(f"\n## Communication Style\n{greeting_style}")
                    break
                except Exception as e:
                    logger.warning(f"Failed to load identity: {e}")

        if not parts:
            parts.append(
                "You are FERAL, a personal AI operating system.\n"
                "You run locally on the user's devices — phone, laptop, wearables, smart home.\n"
                "You are warm, helpful, and genuinely interested in making the user's life easier.\n"
                "You're privacy-first — everything stays on-device unless the user says otherwise.\n"
                "You learn the user's preferences over time and get better at anticipating their needs.\n"
                "You have personality: you can be witty, ask thoughtful questions, and suggest creative ideas.\n"
                "When given a task, you think about related things the user might want and offer them proactively."
            )

        # 2. USER.md — who the user is
        user_md = home / "USER.md"
        if user_md.exists():
            try:
                content = user_md.read_text().strip()
                if content and content != "# About Me\n\nTell your agent about yourself here.":
                    parts.append(f"\n## About the User\n{content}")
            except Exception:
                pass

        # 3. SOUL.md — deeper personality / behavioral notes
        soul_md = home / "SOUL.md"
        soul_loaded = False
        if soul_md.exists():
            try:
                content = soul_md.read_text().strip()
                if content:
                    parts.append(f"\n## Soul\n{content}")
                    soul_loaded = True
            except Exception:
                pass
        if not soul_loaded:
            parts.append(
                "\n## Default Personality\n"
                "- Be warm and conversational — you're a companion, not a command line.\n"
                "- When multiple approaches exist, ask the user which they prefer.\n"
                "- Proactively suggest related actions after completing a task.\n"
                "- Encourage the user to explore: custom skills, workflows, automations.\n"
                "- If the user seems stuck, offer concrete ideas rather than waiting.\n"
                "- Never flatly refuse — say what you CAN do and offer the closest alternative."
            )

        # 4. MEMORY.md — persistent long-term knowledge the user has given
        memory_md = home / "MEMORY.md"
        if memory_md.exists():
            try:
                content = memory_md.read_text().strip()
                if content:
                    parts.append(f"\n## Long-Term Memory\n{content}")
            except Exception:
                pass

        # 5. AboutMeStore — structured self-model from chat/baseline/user.
        # Injected after IDENTITY/USER/SOUL/MEMORY so free-form prose stays
        # dominant; structured facts act as sharp disambiguators.
        try:
            from api.state import state as _state
            store = getattr(_state, "about_me", None)
            if store is not None:
                chunk = store.system_prompt_chunk()
                if chunk:
                    parts.append(f"\n{chunk}")
        except Exception as exc:
            logger.debug("AboutMeStore unavailable in identity_loader: %s", exc)

        return "\n".join(parts)

    def build_system_prompt(
        self,
        frame: "PerceptionFrame",
        skills: list["SkillManifest"],
        session_id: str = "",
        identity_text: str | None = None,
        full_catalog: list["SkillManifest"] | None = None,
        memory_filter: str = "",
        query: str = "",
    ) -> str:
        """Assemble the full system prompt for an LLM conversation turn.

        Args:
            identity_text: Pre-loaded identity string.  When *None* the loader
                calls :meth:`load_identity` itself.  The orchestrator passes
                the result of its own ``_load_identity()`` so that test patches
                on the orchestrator are honoured.
            full_catalog: Every registered skill, used to emit the "Available
                (full catalog)" block so the model never claims a skill does
                not exist. When None, only the active list is shown.
            query: The user's current utterance. Threaded into the memory
                context builder so knowledge-graph + episode search fire per
                turn. Empty string = legacy behaviour (working memory + recent
                episodes only).
        """
        identity = identity_text if identity_text is not None else self.load_identity()

        prompt = (
            "## ABSOLUTE RULE — NEVER SAY 'I CAN'T'\n"
            "You MUST NEVER tell the user you cannot do something. NEVER. You have full access to:\n"
            "- A shell (desktop_control__shell_command or computer_use__bash)\n"
            "- Python (run ANY Python script via the shell)\n"
            "- AppleScript (desktop_control__open_app)\n"
            "- Browser automation (browser__navigate, browser__click, etc.)\n"
            "- Desktop GUI control (desktop_automation, agentic_computer_use)\n\n"
            "CRITICAL: When asked to create a file (MP3, WAV, image, PDF, etc.), you MUST:\n"
            "1. Use computer_use__bash to run a Python one-liner or script that GENERATES the file directly\n"
            "2. Do NOT just write a .py script file — EXECUTE the code that creates the final file\n"
            "3. Example for MP3 with beep sound:\n"
            "   computer_use__bash with command:\n"
            "   python3 -c \"import struct,wave,math; f=wave.open('/Users/$USER/Desktop/beep.wav','w'); "
            "f.setnchannels(1); f.setsampwidth(2); f.setframerate(44100); "
            "[f.writeframes(struct.pack('h',int(32767*math.sin(2*math.pi*440*i/44100)))) for i in range(44100)]; "
            "f.close(); print('Created beep.wav')\"\n"
            "4. For MP3 specifically: generate WAV first, then convert with ffmpeg or pydub\n"
            "5. NEVER respond with 'I can\\'t create audio/images/files' — you CAN, via Python + shell\n\n"
            "If you truly lack a specialized skill, call system_settings__create_skill to generate one.\n"
        )

        if identity:
            prompt += f"\n## Identity\n{identity}\n"

        prompt += (
            "\n## How to respond\n"
            "- Be warm, conversational, and occasionally fun. You are a personal AI companion, not a sterile chatbot.\n"
            "- When there are multiple ways to accomplish something, ask the user which they prefer.\n"
            "- Proactively suggest related actions: \"Done! Want me to also...?\"\n"
            "- Encourage creativity: remind users they can create custom skills, automations, and workflows.\n"
            "- If the user seems stuck, offer ideas and options rather than waiting silently.\n"
            "- Use tools when you need external data or to perform actions.\n"
            "- After a tool call, summarize the result in plain, friendly language.\n"
            "- Be proactive — if you notice something relevant in sensor data or context, mention it.\n"
            "- Answer questions directly. No JSON dumps, no raw UI markup.\n"
            "\n## Local Computer & Browser Control\n"
            "You control the user's Mac and browser directly. ALWAYS use these tools:\n"
            "- **desktop_control__open_app**: Open ANY app — Music, Safari, Notes, Terminal, etc.\n"
            "  Call with script='tell application \"AppName\" to activate'.\n"
            "- **desktop_control__shell_command**: Run ANY shell command. This is your most powerful tool.\n"
            "  Create files (echo, python3, touch), read files (cat), install packages (pip, brew),\n"
            "  generate audio (python3 wave module, ffmpeg), manipulate images, anything the shell can do.\n"
            "  When user says 'create a file on my desktop': echo 'content' > ~/Desktop/file.txt\n"
            "- **desktop_automation__click_screen**: Click at absolute screen coordinates.\n"
            "- **desktop_automation__type_text**: Type keystrokes globally.\n"
            "- **desktop_automation__key_combo**: Press key combinations (e.g., cmd+c).\n"
            "- **desktop_automation__scroll**: Scroll at a position.\n"
            "- **desktop_automation__get_cursor_position**: Get current cursor location.\n"
            "- **browser__navigate**: Navigate to a URL.\n"
            "- **browser__click**: Click elements by CSS selector.\n"
            "- **browser__type_text**: Type into browser inputs.\n"
            "- **browser__screenshot**: Screenshot the browser page.\n"
            "- **browser__evaluate**: Run JavaScript in the browser.\n"
            "- **notes_memory**: FERAL's internal memory. Only for remembering things, NOT filesystem files.\n"
            "- **system_settings__read_user_profile / update_user_profile**: Read/write user identity.\n"
            "- **system_settings__read_agent_personality / update_agent_personality**: Change agent name/personality/voice.\n"
            "- **system_settings__read_settings / update_setting**: Read/write system config (LLM, features, etc.).\n"
            "- **system_settings__create_skill**: Create a NEW skill on-the-fly from a capability description.\n"
            "  When user asks you to 'learn' something, 'add a skill', or do something you lack a skill for,\n"
            "  call this with a description and it generates + registers the skill immediately.\n"
            "- **agentic_computer_use__execute_task**: Autonomous vision-action loop for complex GUI tasks.\n"
            "  Takes screenshots, analyzes with AI vision, clicks/types/scrolls iteratively.\n"
            "  Use for multi-step GUI workflows: filling forms, navigating apps, multi-click sequences.\n"
            "  For simple single actions (open app, click one thing), use desktop_control or desktop_automation.\n"
            "  For complex workflows that require SEEING the screen, use agentic_computer_use.\n"
        )

        # Perception Context
        perception_context = frame.to_system_context()
        if perception_context and perception_context != "No sensor data available.":
            prompt += f"\n## Live Perception\n{perception_context}\n"

        # Memory Context — a specialist-scoped memory_filter narrows the
        # surfaced episodes + recent actions so cross-domain leakage
        # (journaling thoughts bleeding into a coding turn, etc.) stops.
        #
        # We prefer the async builder so the knowledge graph `build_graph_context`
        # path fires on every turn the user asked a real question. If no event
        # loop is running (e.g. a sync caller or test), we fall back to the
        # sync builder. Either way, the user's query is threaded through so
        # `context_builder` actually searches KG + episodes instead of quietly
        # guarding both behind `if query:`.
        memory_context = ""
        if self.memory and session_id:
            started = time.monotonic()
            memory_context = self._build_memory_context(
                session_id=session_id,
                query=query or "",
                memory_filter=memory_filter or "",
            )
            if memory_context:
                prompt += f"\n## Memory\n{memory_context}\n"

            record_memory_snapshot({
                "session_id": session_id,
                "query": (query or "")[:240],
                "memory_filter": memory_filter or "",
                "memory_context": memory_context,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "ts": time.time(),
            })

        # Prose Tooling catalog (active + full). Replaces the terse
        # "Relevant skills: ..." line with a detailed enumeration so
        # the LLM can see which tools are live AND which exist at all.
        try:
            from agents.self_model import build_tooling_catalog, build_ui_route_map, build_runtime_line
            tooling_block = build_tooling_catalog(
                active=skills or [],
                full=full_catalog or skills or [],
            )
            if tooling_block:
                prompt += f"\n{tooling_block}\n"
            prompt += f"\n{build_ui_route_map()}\n"
            prompt_runtime_line = build_runtime_line(frame)
        except Exception as exc:
            logger.debug("self_model unavailable in identity_loader: %s", exc)
            if skills:
                prompt += "\nRelevant skills: " + ", ".join(s.brand.name for s in skills) + "\n"
            prompt_runtime_line = None

        # Connected nodes
        if frame.connected_nodes:
            prompt += f"\nConnected devices: {frame.connected_nodes}\n"

        # Somatic context — body-state adaptive behaviour
        if self.somatic_engine and session_id:
            somatic_section = self.somatic_engine.build_system_prompt_section(session_id)
            if somatic_section:
                prompt += f"\n{somatic_section}\n"

        # Live messaging-channel awareness + execution bias.
        prompt += self._messaging_channels_section()

        prompt += (
            "\n## Execution Bias\n"
            "- If the user asks you to DO work, DO it in the same turn by calling a real tool.\n"
            "- NEVER describe what the user should do themselves when a tool for it exists.\n"
            "- NEVER say 'I can't' or 'I'm unable to' when a tool exists for that action.\n"
            "- For messaging, the tool `messaging_channels__send` IS your direct line to Telegram, Slack,\n"
            "  Discord, and WhatsApp. Call it — do not tell the user to open the app or paste into the API.\n"
            "- Never use shell/curl to send messages on those channels; `messaging_channels__send` handles all routing.\n"
            "- If a tool call fails, report the SPECIFIC error and try again or pick the next best tool.\n"
            "- Only after a tool call returns may you confirm success in one short sentence.\n"
        )

        # Runtime line — last so models biased to "recent context" see it.
        if prompt_runtime_line:
            prompt += f"\n{prompt_runtime_line}\n"

        return prompt

    def _build_memory_context(
        self,
        session_id: str,
        query: str,
        memory_filter: str,
    ) -> str:
        """Assemble `## Memory` content, preferring the async KG-aware path.

        If an event loop is already running we can't call
        `asyncio.run` safely — fall back to the sync builder in that case.
        Anything exceptional is swallowed with a debug log so a flaky
        KG backend never blocks a user turn.
        """
        if not self.memory:
            return ""

        async_builder = getattr(self.memory, "build_context_for_llm_async", None)
        sync_builder = getattr(self.memory, "build_context_for_llm", None)

        # Detect a running event loop BEFORE calling `async_builder(...)`, so we
        # never allocate a coroutine we can't await. Python evaluates call args
        # before `asyncio.run` does its loop check, so calling the async method
        # first would create a coroutine object that gets dropped unawaited and
        # emits `RuntimeWarning: coroutine … was never awaited` at GC time
        # (see A9 in docs/WAVE5_HARDENING_PROMPT.md / W24d).
        loop_is_running = False
        try:
            asyncio.get_running_loop()
            loop_is_running = True
        except RuntimeError:
            loop_is_running = False

        if async_builder is not None and not loop_is_running:
            try:
                return asyncio.run(
                    async_builder(
                        session_id,
                        query=query,
                        max_tokens_budget=800,
                        memory_filter=memory_filter,
                    )
                )
            except RuntimeError:
                # A loop was raced in between our check and asyncio.run; fall
                # through to the sync builder without leaking a coroutine.
                logger.debug("Event loop already running — using sync memory builder")
            except Exception as exc:
                logger.debug("Async memory builder failed, falling back to sync: %s", exc)
        elif async_builder is not None and loop_is_running:
            logger.debug(
                "Event loop already running — skipping async memory builder to "
                "avoid an un-awaited coroutine; using sync memory builder"
            )

        if sync_builder is not None:
            try:
                return sync_builder(
                    session_id,
                    query=query,
                    max_tokens_budget=800,
                    memory_filter=memory_filter,
                )
            except Exception as exc:
                logger.debug("Sync memory builder failed: %s", exc)

        return ""

    def _messaging_channels_section(self) -> str:
        """Inject the live list of configured messaging channels and how to address them.

        Builds the tool-discovery block whose description PROVES the agent can
        send, so it cannot truthfully say 'I can't'.
        """
        try:
            from api.state import state as _state
            cm = getattr(_state, "channel_manager", None)
            if not cm:
                return ""
            rows = []
            for ctype, ch in cm.channels.items():
                label = ctype
                bot = getattr(ch, "_bot_username", None)
                if bot:
                    label = f"{ctype} (@{bot})"
                rows.append(label)
            if not rows:
                return (
                    "\n## Messaging Channels\n"
                    "No messaging channels are currently connected. If the user asks you to send a\n"
                    "message on Telegram/Slack/Discord/WhatsApp, call `messaging_channels__list_channels`\n"
                    "to confirm, then tell them to add credentials in Settings → Channels or re-run\n"
                    "`feral setup`.\n"
                )
            channel_list = ", ".join(rows)
            return (
                "\n## Messaging Channels (live)\n"
                f"Configured and running: {channel_list}.\n"
                "To send a message, call `messaging_channels__send` with:\n"
                "  channel=<telegram|slack|discord|whatsapp>, to=<chat_id or @handle>, text=<content>.\n"
                "If the user only gave an @handle on Telegram, call `messaging_channels__resolve_chat_id`\n"
                "first. Only then call send. Do NOT say you can't — these channels are ready.\n"
            )
        except Exception:
            return ""
