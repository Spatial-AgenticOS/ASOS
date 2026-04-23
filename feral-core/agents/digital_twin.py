"""
FERAL Digital Twin Agent
============================
A cognitive replica that can answer questions "as the user" by drawing on
their full memory corpus, identity files, knowledge graph, and personality.

Features:
  - ask()               — answer any question as the user would
  - predict_preference() — infer preference in a category from memory
  - daily_reflection()   — end-of-day introspection from the twin's POV
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.store import MemoryStore
    from agents.identity_loader import IdentityLoader
    from agents.llm_provider import LLMProvider

logger = logging.getLogger("feral.digital_twin")


class DigitalTwin:
    """A digital twin of the user, built from memory and identity data."""

    def __init__(
        self,
        memory: "MemoryStore",
        identity_loader: "IdentityLoader",
        llm: "LLMProvider",
        policy_engine=None,
    ):
        self._memory = memory
        self._identity = identity_loader
        self._llm = llm
        # Optional TwinPolicyEngine — when wired, execute() gates every
        # action through per-domain policy + kill-switch + approval queue.
        self._policy = policy_engine

    def set_policy_engine(self, policy_engine) -> None:
        self._policy = policy_engine

    async def execute(
        self,
        domain: str,
        action: str,
        context: dict,
        *,
        executor=None,
    ) -> dict:
        """Attempt a twin action in a given domain.

        Returns a decision dict::

            {
              "status": "queued" | "executed" | "denied",
              "approval_id": "...",          # when queued
              "result": {...},               # when executed
              "reason": "...",
              "domain": domain,
              "action": action,
            }

        Execution path depends on the per-domain policy (see
        agents/twin_policy.TwinPolicyEngine):
          * disabled       → denied.
          * draft_only     → queued in the approval store.
          * auto_send      → executor(...) called immediately. The
            twin is responsible for providing a valid executor callable
            (a coroutine returning a dict). Without one, we queue and
            warn.
        """
        if self._policy is None:
            return {
                "status": "denied",
                "reason": "policy_engine_not_wired",
                "domain": domain,
                "action": action,
            }

        decision = self._policy.decide(domain)
        verdict = decision["verdict"]
        if verdict == "denied":
            return {
                "status": "denied",
                "reason": decision["reason"],
                "domain": domain,
                "action": action,
                "policy": decision.get("policy"),
            }
        if verdict == "queued":
            row = self._policy.queue_for_approval(domain, action, context)
            return {
                "status": "queued",
                "approval_id": row.approval_id,
                "reason": decision["reason"],
                "domain": domain,
                "action": action,
                "policy": decision.get("policy"),
            }

        if executor is None:
            # auto_send authorised but there's nothing to execute —
            # treat as queued so the user can see what was drafted.
            row = self._policy.queue_for_approval(domain, action, context)
            return {
                "status": "queued",
                "approval_id": row.approval_id,
                "reason": "auto_send_no_executor",
                "domain": domain,
                "action": action,
            }

        try:
            result = await executor(context)
        except Exception as exc:
            logger.exception("Twin executor for %s/%s failed: %s", domain, action, exc)
            return {
                "status": "denied",
                "reason": f"executor_error:{exc}",
                "domain": domain,
                "action": action,
            }

        self._policy.record_execution(domain)
        if getattr(self._policy, "supervisor", None):
            try:
                self._policy.supervisor.record(
                    source="twin",
                    kind="action_executed",
                    actor="twin",
                    payload=context,
                    decision="allowed",
                    detail={
                        "domain": domain,
                        "action": action,
                        "result": _truncate_dict(result),
                    },
                )
            except Exception as exc:
                logger.debug("supervisor.record(twin:executed) failed: %s", exc)

        return {
            "status": "executed",
            "result": result,
            "reason": "auto_send_ok",
            "domain": domain,
            "action": action,
        }

    async def ask(self, question: str, session_id: str = "") -> str:
        """Answer a question as the user would, based on their full context."""
        try:
            identity_text = self._identity.load_identity()
            user_name = self._extract_name(identity_text)

            episodes = self._memory.episode_recent(limit=20, session_id=None)
            episode_block = self._format_episodes(episodes)

            kg_context = self._fetch_kg_context(question)

            system_prompt = (
                f"You are a digital twin of {user_name}. You think, reason, and "
                f"respond EXACTLY as they would — same priorities, same tone, same "
                f"blind spots, same humor.\n\n"
                f"## Identity & Personality\n{identity_text}\n\n"
            )
            if episode_block:
                system_prompt += f"## Recent Life Events (last 30 days)\n{episode_block}\n\n"
            if kg_context:
                system_prompt += f"## Knowledge Graph Context\n{kg_context}\n\n"

            system_prompt += (
                "Based on their memories, preferences, knowledge, and personality, "
                f"answer this question AS THEM: {question}\n"
                "Think about how they would reason, what they would prioritize, "
                "and what decision they would make."
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ]

            response = await self._llm.chat(messages)
            # chat() either returns a usable dict with .choices, or an
            # error dict {"error": "..."}. Handle both so the UI never
            # sees a raw httpx 401 message.
            if isinstance(response, dict) and response.get("error") and not response.get("choices"):
                logger.warning("Digital twin ask(): provider failed — %s", response.get("error"))
                return (
                    "Couldn't reach your LLM right now. Configure a working "
                    "provider or add a fallback at Settings → Providers."
                )
            text, _ = self._llm.extract_response(response)
            logger.info("Digital twin answered question (len=%d)", len(text or ""))
            return text or ""

        except Exception as e:
            logger.error("Digital twin ask() failed: %s", e)
            return (
                "Couldn't reason about that right now. Configure a working "
                "provider or add a fallback at Settings → Providers."
            )

    async def predict_preference(self, category: str) -> dict:
        """Predict user preference in a given category from memory evidence."""
        try:
            results = self._memory.search(category, limit=15)

            if not results:
                return {
                    "category": category,
                    "preference": "unknown",
                    "confidence": 0.0,
                    "evidence": [],
                }

            evidence = [
                r.get("content", r.get("summary", ""))[:200]
                for r in results if r.get("content") or r.get("summary")
            ]

            prompt = (
                f"Based on these memory fragments about '{category}', determine the "
                f"user's likely preference. Be specific and concise.\n\n"
                f"Memories:\n" + "\n".join(f"- {e}" for e in evidence[:10]) + "\n\n"
                "Return a JSON object with keys: preference (string), confidence (0.0-1.0).\n"
                "ONLY return valid JSON, nothing else."
            )

            messages = [
                {"role": "system", "content": "You analyze memories to infer user preferences. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ]

            response = await self._llm.chat(messages)
            text, _ = self._llm.extract_response(response)
            text = text or ""

            parsed = self._parse_json_safely(text)
            return {
                "category": category,
                "preference": parsed.get("preference", text.strip()[:200]),
                "confidence": min(1.0, max(0.0, float(parsed.get("confidence", 0.5)))),
                "evidence": evidence[:5],
            }

        except Exception as e:
            logger.error("predict_preference failed for '%s': %s", category, e)
            return {
                "category": category,
                "preference": "unknown",
                "confidence": 0.0,
                "evidence": [],
            }

    async def daily_reflection(self) -> str:
        """Generate an end-of-day reflection from the twin's perspective."""
        try:
            identity_text = self._identity.load_identity()
            user_name = self._extract_name(identity_text)

            today_episodes = self._memory.episode_recent(limit=30, session_id=None)
            today_block = self._format_episodes(today_episodes)

            if not today_block:
                return "Not much happened today — or at least nothing I recorded. Tomorrow's a fresh page."

            prompt = (
                f"You are the digital twin of {user_name}. Write a short, honest "
                f"end-of-day reflection (2-4 paragraphs) from their perspective. "
                f"Use first person. Be authentic — mention what went well, what "
                f"was hard, and what's on their mind for tomorrow.\n\n"
                f"## Identity\n{identity_text}\n\n"
                f"## Today's Events\n{today_block}\n"
            )

            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Write my daily reflection."},
            ]

            response = await self._llm.chat(messages)
            text, _ = self._llm.extract_response(response)
            text = text or ""
            logger.info("Digital twin daily reflection generated (len=%d)", len(text))
            return text

        except Exception as e:
            logger.error("daily_reflection failed: %s", e)
            return f"Couldn't reflect on the day: {e}"

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _extract_name(identity_text: str) -> str:
        for line in identity_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("You are "):
                name = stripped.replace("You are ", "").rstrip(".")
                if name and len(name) < 60:
                    return name
        return "the user"

    @staticmethod
    def _format_episodes(episodes: list[dict]) -> str:
        if not episodes:
            return ""
        lines = []
        cutoff = time.time() - (30 * 86_400)
        for ep in episodes:
            ts = ep.get("timestamp", 0)
            if ts and ts < cutoff:
                continue
            summary = ep.get("summary", ep.get("content", ""))
            if summary:
                when = time.strftime("%b %d %H:%M", time.localtime(ts)) if ts else "recent"
                lines.append(f"[{when}] {summary[:300]}")
        return "\n".join(lines)

    def _fetch_kg_context(self, question: str) -> str:
        try:
            results = self._memory.knowledge_search(question, limit=10)
            if not results:
                return ""
            lines = []
            for r in results:
                subj = r.get("subject", "")
                pred = r.get("predicate", "")
                obj = r.get("object", "")
                if subj and pred and obj:
                    lines.append(f"{subj} → {pred} → {obj}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug("KG lookup failed: %s", e)
            return ""

    @staticmethod
    def _parse_json_safely(text: str) -> dict:  # noqa: E501
        return _parse_json_safely(text)


def _truncate_dict(d: dict, limit: int = 200) -> dict:
    """Trim long strings / lists in a result dict for audit-log safety."""
    if not isinstance(d, dict):
        return {"value": str(d)[:limit]}
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = v[:limit]
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x)[:limit] for x in v[:10]]
        elif isinstance(v, dict):
            out[k] = _truncate_dict(v, limit)
        else:
            out[k] = v
    return out


def _parse_json_safely(text: str) -> dict:
    import json as _json
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return _json.loads(text)
    except (_json.JSONDecodeError, ValueError):
        return {}
