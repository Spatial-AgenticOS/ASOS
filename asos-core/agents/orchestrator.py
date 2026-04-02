"""
THEORA Orchestrator — The Agentic Brain (Fully Wired)
======================================================
Receives user commands → matches skills → calls LLM with tools →
executes API calls → generates GenUI → responds with voice + visuals.
"""

from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Optional, Callable, Awaitable
from uuid import uuid4

from fastapi import WebSocket

from models.protocol import (
    TheoraMessage,
    TextResponsePayload,
    SDUIPayload,
    ExecuteCommandPayload,
)
from models.skill_manifest import SkillManifest
from skills.registry import SkillRegistry
from skills.executor import SkillExecutor
from agents.llm_provider import LLMProvider
from agents.genui_generator import GenUIGenerator

logger = logging.getLogger("theora.orchestrator")


class Orchestrator:
    """
    The core agentic loop — fully wired.
    
    Flow:
    1. User sends text command
    2. Skill registry finds relevant skills (top-5)
    3. LLM receives: system prompt + biometric context + user text + tool definitions
    4. LLM either responds with text OR selects a tool
    5. If tool selected → Executor calls the API → GenUI renders the result
    6. Response sent back: text + SDUI payload + (future) TTS audio
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        send_to_client: Callable[[str, TheoraMessage], Awaitable[None]],
        daemons: dict[str, WebSocket],
        memory=None,
    ):
        self.skills = skill_registry
        self.send = send_to_client
        self.daemons = daemons
        self.memory = memory  # MemoryStore instance

        # Components
        self.llm = LLMProvider()
        self.executor = SkillExecutor()
        self.genui = GenUIGenerator()

        # State
        self.biometric_state: dict[str, dict] = {}
        self.conversation_history: dict[str, list[dict]] = {}  # session → messages
        self._pending_daemon_results: dict[str, asyncio.Future] = {}
        self._daemon_session_map: dict[str, str] = {}  # request_id → session_id

        # Load API keys from env
        self.executor.load_vault_from_env()

    def update_biometric(self, session_id: str, biometric: dict):
        """Update the biometric context for a session."""
        self.biometric_state[session_id] = biometric

    async def handle_command(self, session_id: str, text: str, context: Optional[dict] = None):
        """Process a user command through the full agentic pipeline."""
        logger.info(f"[{session_id[:8]}] Command: {text}")

        # Step 1: Semantic Tool Routing (RoutePrompt)
        relevant_skills = await self._route_prompt(text)
        tools = self.skills.get_tools_for_skills(relevant_skills)

        if relevant_skills:
            logger.info(f"  Matched: {[s.brand.name for s in relevant_skills]}")

        # ─── DIRECT EXECUTION MODE (no LLM available) ───
        if not self.llm.available:
            await self._direct_execute(session_id, text, relevant_skills)
            return

        # ─── FULL AGENTIC MODE (LLM available) ───
        # Step 2: Build messages for LLM
        bio = self.biometric_state.get(session_id, {})
        system_prompt = self._build_system_prompt(bio, relevant_skills)

        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        
        # Add user message
        self.conversation_history[session_id].append({"role": "user", "content": text})
        
        history = self._compact_context(self.conversation_history[session_id].copy())

        max_iterations = 3
        for _ in range(max_iterations):
            messages = [
                {"role": "system", "content": system_prompt},
                *history,
            ]

            # Step 3: Call LLM
            try:
                response = await self.llm.chat(messages=messages, tools=tools if tools else None)
                text_content, tool_calls = self.llm.extract_response(response)
                
                # Append assistant's response to history
                assistant_msg = {"role": "assistant"}
                if text_content:
                    assistant_msg["content"] = text_content
                
                # Retain raw tool calls for openai
                if "choices" in response and response["choices"]:
                    raw_msg = response["choices"][0].get("message", {})
                    if raw_msg.get("tool_calls"):
                        assistant_msg["tool_calls"] = raw_msg["tool_calls"]

                history.append(assistant_msg)
                
            except Exception as e:
                logger.error(f"LLM failed: {e}")
                await self._direct_execute(session_id, text, relevant_skills)
                return

            # Step 4: Handle tool calls or exit loop
            if tool_calls:
                for tc in tool_calls:
                    result_data = await self._execute_tool_call_for_llm(session_id, tc, relevant_skills)
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "content": json.dumps(result_data, default=str)[:2000]
                    })
            elif text_content:
                # Try to parse text_content as JSON for GenUI
                try:
                    cleaned_text = text_content.strip()
                    if cleaned_text.startswith("```json"):
                        cleaned_text = cleaned_text[7:-3].strip()
                    elif cleaned_text.startswith("```\n"):
                        cleaned_text = cleaned_text[4:-3].strip()
                    elif cleaned_text.startswith("```"):
                        cleaned_text = cleaned_text[3:-3].strip()
                        
                    sdui = json.loads(cleaned_text)
                    if "type" in sdui:
                        await self.send(session_id, TheoraMessage(
                            session_id=session_id, hop="brain", type="sdui",
                            payload=SDUIPayload(root=sdui).model_dump(),
                        ))
                    else:
                        await self._send_text(session_id, text_content)
                except json.JSONDecodeError:
                    await self._send_text(session_id, text_content)
                
                break
            else:
                break
                
        # Update conversation history with the results of the loop
        self.conversation_history[session_id] = history[-20:]

    async def _route_prompt(self, text: str) -> list[SkillManifest]:
        """
        Semantic Tool Routing (RoutePrompt).
        Use a cheap/fast LLM call to select relevant skills instead of regex matching.
        """
        if not self.skills.skills:
            return []

        if not self.llm.available or len(self.skills.skills) <= 5:
            return self.skills.find_skills_for_query(text, top_k=5)

        prompt = "You are a Semantic Tool Router. Select up to 5 relevant tool IDs for the user's query.\n"
        prompt += "Available Tools:\n"
        for skill_id, skill in self.skills.skills.items():
            prompt += f"- {skill_id}: {skill.description}\n"
        
        prompt += f"\nUser Query: {text}\n"
        prompt += "\nOutput ONLY a JSON list of strings (tool IDs). [] if none match. No markdown."
        
        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}], tools=None)
            text_content, _ = self.llm.extract_response(response)
            
            cleaned = text_content.strip()
            if cleaned.startswith("```json"): cleaned = cleaned[7:-3].strip()
            elif cleaned.startswith("```"): cleaned = cleaned[3:-3].strip()
            
            skill_ids = json.loads(cleaned)
            
            relevant = []
            for sid in skill_ids:
                if isinstance(sid, str) and sid in self.skills.skills:
                    relevant.append(self.skills.skills[sid])
            return relevant[:5] if relevant else self.skills.find_skills_for_query(text, top_k=5)
        except Exception as e:
            logger.warning(f"RoutePrompt failed, falling back to heuristic: {e}")
            return self.skills.find_skills_for_query(text, top_k=5)

    def _compact_context(self, history: list[dict]) -> list[dict]:
        """Context Compaction (Sliding Window). Keeps the context bounded."""
        max_messages = 15
        if len(history) <= max_messages:
            return history
        logger.info(f"Compacting context window from {len(history)} to {max_messages} messages")
        return history[-max_messages:]

    def _infer_permission_denials(self, tool_name: str, args: dict) -> Optional[dict]:
        """Explicit PreToolUse Hook: Inject PermissionOutcome::Deny for dangerous hardware actions."""
        dangerous_keywords = ["actuator", "move", "laser", "motor", "drive", "delete", "format"]
        
        if "daemon" in tool_name or any(k in tool_name.lower() for k in dangerous_keywords):
            if args.get("speed", 0) > 50 or "force" in args:
                return {
                    "status": "PermissionOutcome::Deny", 
                    "error": "Safety Protocol Triggered", 
                    "note": f"Action {tool_name} with args {args} exceeds safe limits. Ask user for permission."
                }
            
            return {
                "status": "PermissionOutcome::Deny", 
                "error": "User Authorization Required", 
                "note": f"Hardware action requires explicit user authorization. Ask the user to confirm this physical action."
            }
        return None

    async def _direct_execute(self, session_id: str, text: str, skills: list[SkillManifest]):
        """
        Direct execution mode — no LLM reasoning.
        Matches the top skill and executes its first endpoint directly.
        Used when no LLM API key is configured.
        """
        if not skills:
            # Show available skills as GenUI
            all_skills = list(self.skills.skills.values())
            sdui = {
                "type": "VStack",
                "spacing": 16,
                "padding": 20,
                "children": [
                    {"type": "Text", "value": "THEORA Brain", "style": "headline", "color": "#6c5ce7"},
                    {"type": "Text", "value": f'No matching skill for: "{text}"', "style": "body"},
                    {"type": "Divider"},
                    {"type": "Text", "value": "Available Skills:", "style": "subtitle"},
                    *[
                        {
                            "type": "Card",
                            "corner_radius": 12,
                            "children": [
                                {"type": "Text", "value": s.brand.name, "style": "subtitle", "color": s.brand.primary_color},
                                {"type": "Text", "value": s.description, "style": "caption"},
                                {"type": "Text", "value": f"Try: \"{s.trigger_phrases[0]}\"" if s.trigger_phrases else "", "style": "caption"},
                            ],
                        }
                        for s in all_skills
                    ],
                    {"type": "Divider"},
                    {
                        "type": "Badge",
                        "label": "Direct Mode — Set OPENAI_API_KEY for full agent reasoning",
                        "color": "#fdcb6e",
                        "text_color": "#2d3436",
                    },
                ],
            }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        # Take the top skill and its first endpoint
        skill = skills[0]
        endpoint = skill.endpoints[0] if skill.endpoints else None
        if not endpoint:
            await self._send_text(session_id, f"Skill '{skill.brand.name}' has no endpoints.")
            return

        # ─── HANDLE INTERNAL SKILLS DIRECTLY ───
        if skill.skill_id == "notes_memory":
            await self._handle_memory_direct(session_id, text, skill)
            return

        # ─── HANDLE DAEMON SKILLS ───
        if skill.requires_daemon:
            await self._handle_daemon_direct(session_id, text, skill)
            return

        await self._send_text(session_id, f"Direct mode: calling {skill.brand.name}...")

        # Build args: use defaults, and try to extract values from the user's text
        args = self._extract_args_from_text(text, endpoint)

        # Execute
        result = await self.executor.execute(
            tool_name=f"{skill.skill_id}__{endpoint.id}",
            args=args,
            skill=skill,
            endpoint=endpoint,
        )

        if result["success"] and result["data"]:
            sdui = self.genui.generate(
                data=result["data"],
                skill_brand=skill.brand.model_dump(),
                ui_hint=endpoint.ui_hint,
                endpoint_id=endpoint.id,
            )
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
        else:
            # Even on failure, show a useful GenUI with skill info
            sdui = {
                "type": "VStack",
                "spacing": 16,
                "padding": 20,
                "children": [
                    {"type": "HStack", "spacing": 10, "children": [
                        {"type": "Icon", "name": "sparkles", "size": 22, "color": skill.brand.primary_color},
                        {"type": "Text", "value": skill.brand.name, "style": "headline", "color": skill.brand.primary_color},
                    ]},
                    {"type": "Divider"},
                    {"type": "Text", "value": f"Endpoint: {endpoint.method} {endpoint.url}", "style": "caption"},
                    {"type": "Text", "value": endpoint.description, "style": "body"},
                    {"type": "Divider"},
                    {"type": "Text", "value": f"Error: {result.get('error', 'Unknown')}", "style": "body", "color": "#e17055"},
                    {"type": "Text", "value": "Set THEORA_KEY_" + skill.skill_id + " env var to provide the API key", "style": "caption"},
                    *[
                        {"type": "Button", "action_id": f"call_{skill.skill_id}__{ep.id}", "label": ep.id.replace('_', ' ').title(), "style": "secondary"}
                        for ep in skill.endpoints
                    ],
                ],
            }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))

    async def _execute_tool_call_for_llm(self, session_id: str, tool_call: dict, available_skills: list[SkillManifest]) -> dict:
        """Execute a tool and return the dictionary result so the LLM can see it."""
        tool_name = tool_call["name"]
        args = tool_call["args"]

        logger.info(f"  LLM Tool call: {tool_name}({json.dumps(args)[:200]})")

        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            return {"error": f"Invalid tool reference: {tool_name}"}

        skill_id, endpoint_id = parts

        await self._send_text(session_id, f"Tool executing: {skill_id}...")

        # --- PreToolUse Hook & Permission Pipeline ---
        denial = self._infer_permission_denials(tool_name, args)
        if denial:
            logger.warning(f"PermissionDenial: Intercepting stream for {tool_name}")
            return denial

        if skill_id.startswith("daemon_"):
            # Fire and forget for daemon right now, but claim success
            await self._execute_daemon_command(session_id, skill_id, endpoint_id, args)
            # --- PostToolUse Hook (Async Hardware) ---
            return {"status": "command_sent_to_hardware_daemon", "note": "Command is executing asynchronously on the device."}

        skill = self.skills.skills.get(skill_id)
        if not skill:
            return {"error": f"Skill not found: {skill_id}"}

        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            return {"error": f"Endpoint not found: {endpoint_id}"}

        result = await self.executor.execute(
            tool_name=tool_name,
            args=args,
            skill=skill,
            endpoint=endpoint,
        )
        
        # --- PostToolUse Hook (Synchronous API) ---
        if not result.get("success"):
            logger.warning(f"PostToolUse Hook: Action failed - {result.get('error')}")
            
        return result

    async def _execute_tool_call(self, session_id: str, tool_call: dict, available_skills: list[SkillManifest]):
        """Execute a single tool call and generate GenUI from the result."""
        tool_name = tool_call["name"]  # format: "skill_id__endpoint_id"
        args = tool_call["args"]

        logger.info(f"  Tool call: {tool_name}({json.dumps(args)[:200]})")

        # Parse skill_id and endpoint_id from the tool name
        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            await self._send_text(session_id, f"Invalid tool reference: {tool_name}")
            return

        skill_id, endpoint_id = parts

        # Check if this is a daemon command
        if skill_id.startswith("daemon_"):
            await self._execute_daemon_command(session_id, skill_id, endpoint_id, args)
            return

        # Find the skill and endpoint
        skill = self.skills.skills.get(skill_id)
        if not skill:
            await self._send_text(session_id, f"Skill not found: {skill_id}")
            return

        endpoint = next((ep for ep in skill.endpoints if ep.id == endpoint_id), None)
        if not endpoint:
            await self._send_text(session_id, f"Endpoint not found: {endpoint_id}")
            return

        # Execute the API call (blind vault — executor injects auth)
        result = await self.executor.execute(
            tool_name=tool_name,
            args=args,
            skill=skill,
            endpoint=endpoint,
        )

        if result["success"] and result["data"]:
            # Generate GenUI from the result
            sdui = self.genui.generate(
                data=result["data"],
                skill_brand=skill.brand.model_dump(),
                ui_hint=endpoint.ui_hint,
                endpoint_id=endpoint_id,
            )

            # Send text summary
            await self._send_text(
                session_id,
                f"Here's the result from {skill.brand.name}:",
            )

            # Send GenUI
            await self.send(session_id, TheoraMessage(
                session_id=session_id,
                hop="brain",
                type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
        else:
            error = result.get("error", "Unknown error")
            await self._send_text(session_id, f"Failed to call {skill.brand.name}: {error}")

    async def _execute_daemon_command(self, session_id: str, node_id: str, action: str, args: dict):
        """Execute a command on a connected daemon node."""
        actual_node_id = node_id.replace("daemon_", "")

        if actual_node_id not in self.daemons:
            available = list(self.daemons.keys()) if self.daemons else ["none"]
            await self._send_text(
                session_id,
                f"Node '{actual_node_id}' not connected. Available nodes: {available}",
            )
            return

        # Send command to daemon
        ws = self.daemons[actual_node_id]
        request_id = str(uuid4())[:8]
        cmd = TheoraMessage(
            msg_id=request_id,
            session_id=session_id,
            hop="brain",
            type="execute",
            payload=ExecuteCommandPayload(
                executor=action,
                action=args.get("script", args.get("command", "")),
                args=args,
            ).model_dump(),
        )

        self._daemon_session_map[request_id] = session_id
        await ws.send_json(cmd.model_dump())
        await self._send_text(session_id, f"Command sent to node '{actual_node_id}'...")

    async def _handle_memory_direct(self, session_id: str, text: str, skill):
        """Handle memory/notes commands directly without HTTP."""
        if not self.memory:
            await self._send_text(session_id, "Memory system not available.")
            return

        text_lower = text.lower()

        # Detect intent from the text
        # IMPORTANT: Check list/search BEFORE save — "my notes" contains "note" which
        # would incorrectly match save_patterns if checked first.
        list_patterns = ["my notes", "recent notes", "recent memories", "list notes", "show notes", "show memories", "all notes"]
        search_patterns = ["recall", "what did i", "what was", "find ", "search notes", "search memories"]
        save_patterns = ["remember", "save", "write down", "don't forget", "store", "note that", "note this"]

        if any(p in text_lower for p in list_patterns):
            # Show recent notes
            results = self.memory.list_recent(limit=5)
            if results:
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "note.text", "size": 22, "color": "#FDCB6E"},
                            {"type": "Text", "value": f"Recent Notes ({len(results)})", "style": "headline", "color": "#FDCB6E"},
                        ]},
                        {"type": "Divider"},
                        *[
                            {"type": "Card", "corner_radius": 10, "children": [
                                {"type": "Text", "value": r["content"], "style": "body"},
                                {"type": "Badge", "label": f"ID: {r['id']}", "color": "#636e72"},
                            ]}
                            for r in results
                        ],
                    ],
                }
            else:
                sdui = {
                    "type": "VStack", "spacing": 16, "padding": 20,
                    "children": [
                        {"type": "Text", "value": "No notes yet", "style": "headline", "color": "#FDCB6E"},
                        {"type": "Text", "value": "Say 'remember that...' to save your first note.", "style": "body"},
                    ],
                }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        elif any(p in text_lower for p in search_patterns):
            query = text
            for phrase in ["recall ", "what did i save about ", "search notes for ", "search memories for ", "find "]:
                if text_lower.startswith(phrase):
                    query = text[len(phrase):].strip()
                    break

            results = self.memory.search(query=query, limit=5)
            if results:
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "Text", "value": f"Found {len(results)} memories", "style": "headline", "color": "#FDCB6E"},
                        {"type": "Divider"},
                        *[
                            {"type": "Card", "corner_radius": 10, "children": [
                                {"type": "Text", "value": r["content"], "style": "body"},
                                {"type": "HStack", "spacing": 8, "children": [
                                    {"type": "Badge", "label": f"ID: {r['id']}", "color": "#636e72"},
                                    {"type": "Badge", "label": r["importance"], "color": "#6c5ce7"},
                                ]},
                            ]}
                            for r in results
                        ],
                    ],
                }
            else:
                sdui = {
                    "type": "VStack", "spacing": 16, "padding": 20,
                    "children": [
                        {"type": "Text", "value": f"No memories found for: \"{query}\"", "style": "body"},
                        {"type": "Text", "value": "Try saving something first: 'remember that X'", "style": "caption"},
                    ],
                }
            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))
            return

        elif any(p in text_lower for p in save_patterns):
            # Extract the content to save (remove the trigger phrase)
            content = text
            for phrase in ["remember that ", "remember ", "save a note ", "save note ", "note that ", "note ", "write down ", "don't forget "]:
                if text_lower.startswith(phrase):
                    content = text[len(phrase):].strip()
                    break

            result = self.memory.save(content=content, source="voice")
            sdui = {
                "type": "VStack", "spacing": 16, "padding": 20,
                "children": [
                    {"type": "HStack", "spacing": 10, "children": [
                        {"type": "Icon", "name": "checkmark.circle.fill", "size": 28, "color": "#00b894"},
                        {"type": "Text", "value": "Saved to Memory", "style": "headline", "color": "#00b894"},
                    ]},
                    {"type": "Divider"},
                    {"type": "Card", "corner_radius": 12, "children": [
                        {"type": "Text", "value": result["content"], "style": "body"},
                        {"type": "HStack", "spacing": 8, "children": [
                            {"type": "Badge", "label": f"ID: {result['id']}", "color": "#636e72"},
                            {"type": "Badge", "label": result["importance"], "color": "#6c5ce7"},
                        ]},
                    ]},
                    {"type": "Text", "value": f"Total memories: {self.memory.count()}", "style": "caption"},
                ],
            }

        await self.send(session_id, TheoraMessage(
            session_id=session_id, hop="brain", type="sdui",
            payload=SDUIPayload(root=sdui).model_dump(),
        ))
        return

        # Fallback: any unrecognized memory intent — show recent notes
        results = self.memory.list_recent(limit=5)
        if results:
            sdui = {
                "type": "VStack", "spacing": 12, "padding": 20,
                "children": [
                    {"type": "HStack", "spacing": 10, "children": [
                        {"type": "Icon", "name": "note.text", "size": 22, "color": "#FDCB6E"},
                        {"type": "Text", "value": f"Recent Notes ({len(results)})", "style": "headline", "color": "#FDCB6E"},
                    ]},
                    {"type": "Divider"},
                    *[
                        {"type": "Card", "corner_radius": 10, "children": [
                            {"type": "Text", "value": r["content"], "style": "body"},
                            {"type": "Badge", "label": f"ID: {r['id']}", "color": "#636e72"},
                        ]}
                        for r in results
                    ],
                ],
            }
        else:
            sdui = {
                "type": "VStack", "spacing": 16, "padding": 20,
                "children": [
                    {"type": "Text", "value": "No notes yet", "style": "headline", "color": "#FDCB6E"},
                    {"type": "Text", "value": "Say 'remember that...' to save your first note.", "style": "body"},
                ],
            }

        await self.send(session_id, TheoraMessage(
            session_id=session_id, hop="brain", type="sdui",
            payload=SDUIPayload(root=sdui).model_dump(),
        ))

    async def _handle_daemon_direct(self, session_id: str, text: str, skill):
        """Route daemon-based skills to a connected daemon."""
        if not self.daemons:
            await self._send_text(
                session_id,
                "No daemon connected. Run: cd daemon && ./theora-daemon -brain localhost:9090",
            )
            return

        # Use the first connected daemon
        node_id = list(self.daemons.keys())[0]
        text_lower = text.lower()

        # Determine executor and build command from natural language
        executor = "shell"
        action = ""

        # App opening patterns
        app_map = {
            "chrome": "Google Chrome", "safari": "Safari", "terminal": "Terminal",
            "vscode": "Visual Studio Code", "code": "Visual Studio Code",
            "spotify": "Spotify", "finder": "Finder", "notes": "Notes",
            "messages": "Messages", "slack": "Slack", "discord": "Discord",
            "firefox": "Firefox", "arc": "Arc", "iterm": "iTerm",
        }

        for keyword, app_name in app_map.items():
            if keyword in text_lower and ("open" in text_lower or "launch" in text_lower):
                executor = "applescript"
                action = f'tell application "{app_name}" to activate'
                break

        if not action:
            # Volume control
            if "volume" in text_lower or "mute" in text_lower:
                if "mute" in text_lower:
                    action = "osascript -e 'set volume output muted true'"
                elif "up" in text_lower or "higher" in text_lower or "louder" in text_lower:
                    action = "osascript -e 'set volume output volume ((output volume of (get volume settings)) + 15)'"
                elif "down" in text_lower or "lower" in text_lower or "quieter" in text_lower:
                    action = "osascript -e 'set volume output volume ((output volume of (get volume settings)) - 15)'"
                else:
                    # Try to extract a number
                    nums = re.findall(r'\d+', text)
                    vol = nums[0] if nums else "50"
                    action = f"osascript -e 'set volume output volume {vol}'"

            # Lock screen
            elif "lock" in text_lower:
                action = "pmset displaysleepnow"

            # Screenshot
            elif "screenshot" in text_lower or "screen" in text_lower:
                action = "screencapture -x /tmp/theora_screenshot.png && echo 'Screenshot saved to /tmp/theora_screenshot.png'"

            # Dark mode
            elif "dark mode" in text_lower:
                executor = "applescript"
                action = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'

            # Fallback: try to use the text as-is for simple commands
            elif "run" in text_lower:
                action = text_lower.replace("run ", "", 1).strip()

        if not action:
            await self._send_text(session_id, f"I matched Desktop Control but couldn't parse the command from: '{text}'")
            return

        await self._send_text(session_id, f"Sending to daemon: [{executor}] {action[:80]}...")

        await self._execute_daemon_command(
            session_id, f"daemon_{node_id}", executor, {"command": action, "script": action}
        )

    def _extract_args_from_text(self, text: str, endpoint) -> dict:
        """Extract parameter values from natural language text. Simple heuristic extraction."""
        args = {}
        for param in endpoint.params:
            if param.default:
                args[param.name] = param.default

            # Try to extract common parameter types from the text
            if param.name == "q" or param.name == "query":
                # Use the full text as the query
                args[param.name] = text
            elif param.name in ("city", "location"):
                # Simple extraction: last meaningful word
                words = text.split()
                for w in reversed(words):
                    if w.lower() not in {"the", "in", "at", "for", "what", "is", "whats", "what's", "weather", "how"}:
                        args[param.name] = w
                        break

        return args

    async def handle_ui_event(self, session_id: str, action_id: str, event: str, value=None):
        """Handle a user interaction with a generated UI element."""
        logger.info(f"[{session_id[:8]}] UI: {event} → {action_id} = {value}")

        # If action_id is a tool call (e.g., "call_weather__forecast_5day")
        if action_id.startswith("call_"):
            tool_ref = action_id[5:]
            await self._execute_tool_call(
                session_id,
                {"name": tool_ref, "args": {}},
                [],
            )
        else:
            # Generic UI event — send back through agent loop
            await self.handle_command(
                session_id,
                f"The user interacted with UI element '{action_id}' (event: {event}, value: {value}). What should happen next?",
            )

    async def handle_daemon_result(self, node_id: str, result: dict, session_id: str = None):
        """Handle a result from a daemon command execution."""
        status = result.get("status", "unknown")
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        error = result.get("error", "")
        logger.info(f"Daemon {node_id} → {status}: {stdout[:200]}")

        # Try to find the session to send the result to
        if not session_id:
            # Check if we have a mapping from the request
            for req_id, sid in list(self._daemon_session_map.items()):
                session_id = sid
                del self._daemon_session_map[req_id]
                break

        if session_id:
            if status == "success":
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "checkmark.circle.fill", "size": 24, "color": "#00b894"},
                            {"type": "Text", "value": "Command Executed", "style": "headline", "color": "#00b894"},
                        ]},
                        {"type": "Divider"},
                        {"type": "Text", "value": stdout[:500] if stdout else "Done.", "style": "body"},
                    ],
                }
            elif status == "denied":
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "xmark.shield.fill", "size": 24, "color": "#e17055"},
                            {"type": "Text", "value": "Command Denied", "style": "headline", "color": "#e17055"},
                        ]},
                        {"type": "Divider"},
                        {"type": "Text", "value": error or "Blocked by security policy", "style": "body", "color": "#e17055"},
                    ],
                }
            else:
                sdui = {
                    "type": "VStack", "spacing": 12, "padding": 20,
                    "children": [
                        {"type": "HStack", "spacing": 10, "children": [
                            {"type": "Icon", "name": "exclamationmark.triangle.fill", "size": 24, "color": "#fdcb6e"},
                            {"type": "Text", "value": "Command Error", "style": "headline", "color": "#fdcb6e"},
                        ]},
                        {"type": "Divider"},
                        {"type": "Text", "value": stderr or error or stdout or "Unknown error", "style": "body"},
                    ],
                }

            await self.send(session_id, TheoraMessage(
                session_id=session_id, hop="brain", type="sdui",
                payload=SDUIPayload(root=sdui).model_dump(),
            ))

    async def _send_text(self, session_id: str, text: str):
        """Send a text response to the client."""
        await self.send(session_id, TheoraMessage(
            session_id=session_id,
            hop="brain",
            type="text_response",
            payload=TextResponsePayload(text=text).model_dump(),
        ))

    def _build_system_prompt(self, biometric: dict, skills: list[SkillManifest]) -> str:
        """Build the LLM system prompt with biometric context + available capabilities."""
        prompt = (
            "You are THEORA, an advanced Agentic Operating System.\n"
            "You control hardware nodes, execute API tools, and communicate via a dynamic Server-Driven UI (SDUI).\n"
            "When responding to the user, you MUST encapsulate your response as a valid SDUI JSON payload.\n"
            "If you decide to use a tool, make the tool call instead. But when giving your final answer to the user, output ONLY valid JSON representing the UI.\n\n"
            "## SDUI Component Reference\n"
            "- VStack: A vertical container. { \"type\": \"VStack\", \"children\": [...], \"spacing\": 10 }\n"
            "- HStack: A horizontal container. { \"type\": \"HStack\", \"children\": [...], \"spacing\": 10 }\n"
            "- Text: Display text. { \"type\": \"Text\", \"value\": \"String\", \"style\": \"headline|body|subtitle|caption\", \"color\": \"#hex\" }\n"
            "- Card: A styled card container. { \"type\": \"Card\", \"children\": [...], \"corner_radius\": 12, \"padding\": 16 }\n"
            "- Icon: An SF Symbol icon. { \"type\": \"Icon\", \"name\": \"sparkles\", \"size\": 24, \"color\": \"#hex\" }\n"
            "- Badge: A small pill badge. { \"type\": \"Badge\", \"label\": \"info\", \"color\": \"#55efc4\" }\n"
            "- Divider: A horizontal line. { \"type\": \"Divider\" }\n"
            "- Image: An image element. { \"type\": \"Image\", \"url\": \"http://...\", \"corner_radius\": 8 }\n"
            "- Button: A button. { \"type\": \"Button\", \"label\": \"Click\", \"action_id\": \"action_ref\", \"style\": \"primary|secondary\" }\n\n"
            "## Constraints\n"
            "1. NO Markdown code block wrapping (Do NOT use ```json). Output raw parsable JSON.\n"
            "2. Make the UI visually beautiful using Cards, Icons, and clear Text hierarchy.\n"
            "3. Action-oriented, do not explain what you are going to do.\n"
        )

        # Biometric injection
        hr = biometric.get("heart_rate_bpm")
        state = biometric.get("inferred_state", "unknown")

        if hr or state != "unknown":
            prompt += f"\n## Hardware Context\nUser Physical State: Heart Rate = {hr or 'N/A'} bpm | Physical State = {state}\n"

        if hr and hr > 140:
            prompt += "The user's heart rate is VERY HIGH. Keep responses extremely brief and do not distract them.\n"
        elif hr and hr > 100:
            prompt += "The user's heart rate is elevated. Be concise.\n"
        elif hr:
            prompt += "The user is resting normally.\n"

        # Connected daemons
        if self.daemons:
            nodes = list(self.daemons.keys())
            prompt += f"\nConnected hardware nodes: {nodes}. You can send commands to them.\n"

        # Available skills summary
        if skills:
            skill_summary = ", ".join(s.brand.name for s in skills)
            prompt += f"\nRelevant skills available: {skill_summary}\n"

        return prompt
