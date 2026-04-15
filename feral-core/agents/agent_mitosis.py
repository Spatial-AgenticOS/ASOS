"""Agent Mitosis — self-spawning persistent specialist agents from observed patterns."""
from __future__ import annotations
import json
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("feral.agent_mitosis")

@dataclass
class TaskPattern:
    """A recurring task pattern detected from user interactions."""
    pattern_id: str
    topic_cluster: str
    tool_affinities: list[str]
    time_pattern: Optional[str] = None  # e.g., "weekday_morning", "monday_9am"
    occurrence_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    sample_prompts: list[str] = field(default_factory=list)

@dataclass
class SpecialistAgent:
    """A permanently spawned specialist agent."""
    agent_id: str
    name: str
    description: str
    system_prompt: str
    source_pattern: str
    tool_permissions: list[str]
    schedule: Optional[str] = None  # cron expression
    memory_filter: Optional[str] = None  # topic filter for memory subset
    created_at: float = field(default_factory=time.time)
    last_active: float = 0.0
    tasks_completed: int = 0
    satisfaction_score: float = 0.5  # 0-1, evolves from feedback
    prompt_version: int = 1

SPAWN_THRESHOLD = 5
MAX_SPECIALISTS = 10

class AgentMitosisEngine:
    def __init__(self, llm=None, memory=None):
        self._llm = llm
        self._memory = memory
        self._patterns: dict[str, TaskPattern] = {}
        self._specialists: dict[str, SpecialistAgent] = {}
        self._topic_tracker: dict[str, Counter] = {}  # session -> topic counts

    def observe_interaction(self, session_id: str, text: str, tools_used: list[str]):
        topic = self._classify_topic(text, tools_used)
        if not topic:
            return

        counter = self._topic_tracker.setdefault(session_id, Counter())
        counter[topic] += 1

        pattern_id = f"pattern_{topic}"
        if pattern_id in self._patterns:
            p = self._patterns[pattern_id]
            p.occurrence_count += 1
            p.last_seen = time.time()
            for t in tools_used:
                if t not in p.tool_affinities:
                    p.tool_affinities.append(t)
            if len(p.sample_prompts) < 5:
                p.sample_prompts.append(text[:200])
        else:
            t = time.localtime()
            time_label = f"{'weekday' if t.tm_wday < 5 else 'weekend'}_{['morning','afternoon','evening','night'][t.tm_hour // 6]}"
            self._patterns[pattern_id] = TaskPattern(
                pattern_id=pattern_id,
                topic_cluster=topic,
                tool_affinities=tools_used[:],
                time_pattern=time_label,
                occurrence_count=1,
                sample_prompts=[text[:200]],
            )

    def _classify_topic(self, text: str, tools: list[str]) -> Optional[str]:
        text_lower = text.lower()
        topic_keywords = {
            "health_monitoring": ["health", "heart", "sleep", "exercise", "spo2", "stress", "wellness"],
            "code_review": ["code", "review", "pull request", "pr", "diff", "commit", "bug"],
            "email_management": ["email", "inbox", "reply", "draft", "send email", "unread"],
            "calendar_planning": ["calendar", "schedule", "meeting", "appointment", "event"],
            "research": ["research", "search", "find", "look up", "article", "paper"],
            "writing": ["write", "draft", "essay", "blog", "content", "summarize"],
            "finance": ["budget", "expense", "price", "cost", "payment", "financial"],
            "home_automation": ["lights", "thermostat", "home", "temperature", "scene"],
            "music": ["play", "song", "playlist", "music", "spotify"],
            "news": ["news", "headlines", "trending", "current events"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return topic

        if tools:
            tool_prefix = tools[0].split("__")[0] if "__" in tools[0] else tools[0]
            return f"tool_{tool_prefix}"

        return None

    def get_spawn_proposals(self) -> list[dict]:
        proposals = []
        for pid, pattern in self._patterns.items():
            if pattern.occurrence_count >= SPAWN_THRESHOLD and pid not in self._specialists:
                name = pattern.topic_cluster.replace("_", " ").title() + " Agent"
                proposals.append({
                    "pattern_id": pid,
                    "name": name,
                    "topic": pattern.topic_cluster,
                    "seen_count": pattern.occurrence_count,
                    "tools": pattern.tool_affinities,
                    "time_pattern": pattern.time_pattern,
                    "sample_prompts": pattern.sample_prompts[:3],
                })
        return proposals[:MAX_SPECIALISTS - len(self._specialists)]

    async def spawn_specialist(self, pattern_id: str) -> Optional[SpecialistAgent]:
        pattern = self._patterns.get(pattern_id)
        if not pattern or not self._llm:
            return None
        if len(self._specialists) >= MAX_SPECIALISTS:
            return None

        prompt_gen = (
            f"Create a focused system prompt for a specialist AI agent.\n"
            f"Topic: {pattern.topic_cluster}\n"
            f"Tools available: {', '.join(pattern.tool_affinities)}\n"
            f"Sample user requests:\n" + "\n".join(f"- {p}" for p in pattern.sample_prompts[:3]) +
            f"\n\nThe prompt should be 3-5 sentences. Be specific about the agent's expertise."
        )

        try:
            response = await self._llm.chat([
                {"role": "system", "content": "You write concise, focused system prompts for AI specialist agents."},
                {"role": "user", "content": prompt_gen},
            ])
            text, _ = self._llm.extract_response(response)

            agent_id = f"specialist_{pattern.topic_cluster}"
            name = pattern.topic_cluster.replace("_", " ").title() + " Agent"

            specialist = SpecialistAgent(
                agent_id=agent_id,
                name=name,
                description=f"Specialist for {pattern.topic_cluster} tasks",
                system_prompt=text.strip(),
                source_pattern=pattern_id,
                tool_permissions=pattern.tool_affinities[:],
                schedule=self._pattern_to_cron(pattern),
            )
            self._specialists[pattern_id] = specialist
            logger.info(f"Agent Mitosis: spawned {agent_id} from pattern {pattern.topic_cluster}")
            return specialist
        except Exception as e:
            logger.warning(f"Agent Mitosis spawn failed: {e}")
            return None

    def record_feedback(self, agent_id: str, positive: bool):
        for spec in self._specialists.values():
            if spec.agent_id == agent_id:
                delta = 0.05 if positive else -0.1
                spec.satisfaction_score = max(0, min(1, spec.satisfaction_score + delta))
                spec.tasks_completed += 1
                spec.last_active = time.time()

    @staticmethod
    def _pattern_to_cron(pattern: TaskPattern) -> Optional[str]:
        if pattern.time_pattern and "morning" in pattern.time_pattern:
            return "0 9 * * *"  # 9 AM daily
        if pattern.time_pattern and "evening" in pattern.time_pattern:
            return "0 18 * * *"
        return None

    def list_specialists(self) -> list[dict]:
        return [
            {"agent_id": s.agent_id, "name": s.name, "description": s.description,
             "tools": s.tool_permissions, "schedule": s.schedule,
             "tasks": s.tasks_completed, "satisfaction": s.satisfaction_score,
             "created": s.created_at, "last_active": s.last_active}
            for s in self._specialists.values()
        ]

    def stats(self) -> dict:
        return {
            "patterns_tracked": len(self._patterns),
            "proposals_ready": len(self.get_spawn_proposals()),
            "specialists_active": len(self._specialists),
            "total_tasks": sum(s.tasks_completed for s in self._specialists.values()),
        }
