"""
THEORA Learner — The Self-Learning Agent
==========================================
What makes THEORA an OS instead of a chatbot:
the intelligence learns who you are from every interaction.

Three learning mechanisms:
1. Knowledge Extraction — LLM extracts facts from conversations
   (preferences, relationships, routines) → semantic memory
2. Session Summarization — on disconnect or context compact,
   conversations are summarized → episodic memory
3. Execution-Aware Routing — skill success/failure rates
   from the execution log influence future routing decisions
"""

from __future__ import annotations
import json
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.llm_provider import LLMProvider
    from memory.store import MemoryStore

logger = logging.getLogger("theora.learner")

EXTRACT_PROMPT = """You are a knowledge extraction engine for a personal AI operating system.
Analyze the following conversation excerpt and extract structured facts about the user.

Return ONLY a JSON array of knowledge triples. Each triple has:
- "subject": the entity (usually "user" or a person/place name)
- "predicate": the relationship (e.g., "name_is", "lives_in", "works_at", "prefers", "dislikes", "age_is", "has_pet", "allergic_to")
- "object": the value

If no facts can be extracted, return an empty array: []
Do NOT invent facts. Only extract what is explicitly stated or strongly implied.

Examples:
- User says "I'm allergic to peanuts" → [{"subject":"user","predicate":"allergic_to","object":"peanuts"}]
- User says "My dog Rex is a golden retriever" → [{"subject":"user","predicate":"has_pet","object":"Rex"},{"subject":"Rex","predicate":"breed_is","object":"golden retriever"}]
- User says "search the web for recipes" → []  (no personal facts)

Conversation:
"""

SUMMARIZE_PROMPT = """You are a memory consolidation engine for a personal AI operating system.
Summarize the following conversation into a single concise paragraph (2-4 sentences).
Focus on: what the user wanted, what was accomplished, and any important context.
Do NOT include greetings or filler. Be factual and dense.

Conversation:
"""


class Learner:
    """
    Background learning agent that extracts knowledge and
    consolidates memories from conversations.
    """

    def __init__(self, llm: "LLMProvider", memory: "MemoryStore"):
        self.llm = llm
        self.memory = memory
        self._extract_interval = 5  # run extraction every N messages
        self._message_counters: dict[str, int] = {}

    async def on_message(self, session_id: str, role: str, text: str):
        """Called after every message. Triggers extraction at intervals."""
        if not self.llm.available or not text.strip():
            return

        key = session_id
        self._message_counters[key] = self._message_counters.get(key, 0) + 1

        if self._message_counters[key] >= self._extract_interval:
            self._message_counters[key] = 0
            await self.extract_knowledge(session_id)

    async def extract_knowledge(self, session_id: str):
        """
        Run an LLM call to extract user facts from recent working memory
        and store them as semantic knowledge triples.
        """
        recent = self.memory.working_get(session_id, limit=10)
        if not recent:
            return

        conversation_text = ""
        for entry in recent:
            role = entry.get("role", "?")
            text = entry.get("text", entry.get("summary", ""))
            if text:
                conversation_text += f"{role}: {text}\n"

        if len(conversation_text) < 20:
            return

        prompt = EXTRACT_PROMPT + conversation_text.strip()

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                temperature=0.1,
                max_tokens=512,
            )
            text_content, _ = self.llm.extract_response(response)
            if not text_content:
                return

            cleaned = text_content.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:-3].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:-3].strip()

            triples = json.loads(cleaned)
            if not isinstance(triples, list):
                return

            extracted = 0
            for triple in triples:
                subject = triple.get("subject", "").strip()
                predicate = triple.get("predicate", "").strip()
                obj = triple.get("object", "").strip()
                if subject and predicate and obj:
                    self.memory.knowledge_store(
                        subject=subject,
                        predicate=predicate,
                        obj=obj,
                        confidence=0.8,
                        source=f"conversation_extraction:{session_id}",
                    )
                    extracted += 1

            if extracted:
                logger.info(f"[{session_id[:8]}] Learner extracted {extracted} knowledge triples")

        except json.JSONDecodeError:
            logger.debug("Knowledge extraction returned non-JSON, skipping")
        except Exception as e:
            logger.warning(f"Knowledge extraction failed: {e}")

    async def summarize_session(self, session_id: str):
        """
        Summarize the full session conversation and store as an episodic memory.
        Called on session disconnect or explicit flush.
        """
        recent = self.memory.working_get(session_id, limit=30)
        if len(recent) < 3:
            return

        conversation_text = ""
        for entry in recent:
            role = entry.get("role", "?")
            text = entry.get("text", entry.get("summary", ""))
            if text:
                conversation_text += f"{role}: {text}\n"

        if len(conversation_text) < 50:
            return

        if not self.llm.available:
            self.memory.episode_save(
                session_id=session_id,
                event_type="session_summary",
                summary=f"Session with {len(recent)} messages (no LLM available for summarization)",
                importance=0.4,
            )
            return

        prompt = SUMMARIZE_PROMPT + conversation_text.strip()

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                temperature=0.3,
                max_tokens=256,
            )
            summary, _ = self.llm.extract_response(response)
            if summary and len(summary) > 10:
                self.memory.episode_save(
                    session_id=session_id,
                    event_type="session_summary",
                    summary=summary.strip()[:500],
                    detail=f"Messages: {len(recent)}",
                    importance=0.6,
                )
                logger.info(f"[{session_id[:8]}] Session summarized: {summary[:80]}...")

        except Exception as e:
            logger.warning(f"Session summarization failed: {e}")

    def get_skill_reliability(self, skill_id: str) -> dict:
        """
        Query the execution log for a skill's reliability metrics.
        Returns success rate, avg latency, and a routing recommendation.
        """
        rate = self.memory.log_success_rate(skill_id)
        recent = self.memory.log_recent(skill_id=skill_id, limit=10)

        avg_latency = 0.0
        if recent:
            latencies = [r.get("latency_ms", 0) for r in recent if r.get("latency_ms")]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        recent_failures = sum(1 for r in recent[:5] if r.get("result_status") != "success")

        recommendation = "normal"
        if rate["total_executions"] >= 5:
            if rate["rate"] < 0.3:
                recommendation = "avoid"
            elif rate["rate"] < 0.6:
                recommendation = "caution"
            elif recent_failures >= 3:
                recommendation = "degraded"

        return {
            "skill_id": skill_id,
            "success_rate": rate["rate"],
            "total_executions": rate["total_executions"],
            "avg_latency_ms": round(avg_latency, 1),
            "recent_failures": recent_failures,
            "recommendation": recommendation,
        }

    def get_routing_penalties(self) -> dict[str, float]:
        """
        Return a map of skill_id → penalty multiplier for skill routing.
        Skills with poor track records get penalized in routing scores.
        """
        penalties = {}
        for skill_id in set(
            r.get("skill_id", "") for r in self.memory.log_recent(limit=100)
        ):
            if not skill_id:
                continue
            reliability = self.get_skill_reliability(skill_id)
            rec = reliability["recommendation"]
            if rec == "avoid":
                penalties[skill_id] = 0.1
            elif rec == "degraded":
                penalties[skill_id] = 0.4
            elif rec == "caution":
                penalties[skill_id] = 0.7
        return penalties
