from __future__ import annotations

import logging

logger = logging.getLogger("feral.memory")


async def build_context_for_llm_async(
    store,
    session_id: str,
    query: str = "",
    max_tokens_budget: int = 2000,
    memory_filter: str = "",
) -> str:
    """Async context builder using hybrid search + knowledge graph.

    ``memory_filter``: see the docstring on ``build_context_for_llm``.
    """
    sections = []
    budget_per_section = max_tokens_budget // 4

    working = store.working_context_string(session_id, limit=8)
    if working:
        sections.append(f"## Recent Context\n{working[:budget_per_section]}")

    if query and store._kg:
        graph_ctx = await store._kg.build_graph_context(query, max_chars=budget_per_section)
        if graph_ctx:
            sections.append(graph_ctx)
    elif query:
        knowledge = store.knowledge_search(query, limit=5)
        if knowledge:
            k_lines = [f"- {k['subject']} {k['predicate']} {k['object']}" for k in knowledge]
            sections.append("## Known Facts\n" + "\n".join(k_lines)[:budget_per_section])

    if query:
        episodes = await store.episode_search_hybrid(query, limit=3)
    else:
        episodes = store.episode_recent(limit=3, session_id=session_id)
    if memory_filter:
        episodes = [e for e in episodes if _topic_match(e, memory_filter)]
    if episodes:
        ep_lines = [f"- [{e['event_type']}] {e['summary']}" for e in episodes]
        sections.append("## Past Events\n" + "\n".join(ep_lines)[:budget_per_section])

    recent_execs = store.log_recent(limit=5)
    if memory_filter:
        recent_execs = [ex for ex in recent_execs if _topic_match(ex, memory_filter)]
    if recent_execs:
        ex_lines = [f"- {ex.get('skill_id', '?')}: {ex.get('result_status', '?')}" for ex in recent_execs]
        sections.append("## Recent Actions\n" + "\n".join(ex_lines)[:budget_per_section])

    return "\n\n".join(sections) if sections else ""


def _topic_match(item: dict, topic: str) -> bool:
    """Case-insensitive substring match across common fields.

    Used to post-filter episodes / execution log entries by a
    SpecialistAgent.memory_filter topic (e.g. ``"coding"``,
    ``"journal"``). Intentionally permissive — we want "security_analyst"
    to see rows tagged ``"security"`` or whose summary contains the word.
    """
    if not topic:
        return True
    needle = topic.lower().strip()
    if not needle:
        return True
    fields = (
        item.get("event_type"),
        item.get("summary"),
        item.get("skill_id"),
        item.get("tags"),
        item.get("topic"),
        item.get("category"),
    )
    for f in fields:
        if f is None:
            continue
        if isinstance(f, (list, tuple, set)):
            if any(needle in str(x).lower() for x in f):
                return True
        elif needle in str(f).lower():
            return True
    return False


def build_context_for_llm(
    store,
    session_id: str,
    query: str = "",
    max_tokens_budget: int = 2000,
    memory_filter: str = "",
) -> str:
    """Synchronous context builder (backward compat).

    ``memory_filter``: when a SpecialistAgent is routing the turn, its
    ``memory_filter`` topic is passed in and we drop episodes / recent
    actions that don't mention it. Keeps the journaling specialist from
    leaking into the coding specialist's context, etc. Empty string =
    pre-memory-filter behaviour (no filtering).
    """
    sections = []
    budget_per_section = max_tokens_budget // 4

    working = store.working_context_string(session_id, limit=8)
    if working:
        sections.append(f"## Recent Context\n{working[:budget_per_section]}")

    if query:
        knowledge = store.knowledge_search(query, limit=5)
        if knowledge:
            k_lines = [f"- {k['subject']} {k['predicate']} {k['object']}" for k in knowledge]
            sections.append("## Known Facts\n" + "\n".join(k_lines)[:budget_per_section])

    if query:
        episodes = store.episode_search(query, limit=3)
    else:
        episodes = store.episode_recent(limit=3, session_id=session_id)
    if memory_filter:
        episodes = [e for e in episodes if _topic_match(e, memory_filter)]
    if episodes:
        ep_lines = [f"- [{e['event_type']}] {e['summary']}" for e in episodes]
        sections.append("## Past Events\n" + "\n".join(ep_lines)[:budget_per_section])

    recent_execs = store.log_recent(limit=5)
    if memory_filter:
        recent_execs = [ex for ex in recent_execs if _topic_match(ex, memory_filter)]
    if recent_execs:
        ex_lines = [f"- {ex.get('skill_id', '?')}: {ex.get('result_status', '?')}" for ex in recent_execs]
        sections.append("## Recent Actions\n" + "\n".join(ex_lines)[:budget_per_section])

    return "\n\n".join(sections) if sections else ""


async def compact_session(
    store,
    session_id: str,
    history: list[dict],
    llm=None,
    preserve_last_n: int = 3,
    max_summary_chars: int = 16000,
) -> dict:
    """
    Multi-stage session compaction. Summarizes older messages while
    preserving the last N turns and identity context.
    """
    if len(history) <= preserve_last_n + 2:
        return {"compacted": False, "reason": "too_short"}

    preserved = history[-preserve_last_n:]
    summarizable = history[:-preserve_last_n]

    if not llm or not llm.available:
        summary = heuristic_summarize(summarizable)
    else:
        summary = await llm_summarize(messages=summarizable, llm=llm, max_chars=max_summary_chars)

    compacted_history = [
        {"role": "system", "content": f"[Session Summary]\n{summary}"},
        *preserved,
    ]

    if store.kg:
        try:
            conversation_text = " ".join(
                m.get("content", "") for m in summarizable if isinstance(m.get("content"), str)
            )
            if conversation_text:
                await store.kg.extract_and_store(conversation_text[:3000], llm)
        except Exception as e:
            logger.debug(f"KG extraction during compaction failed: {e}")

    return {
        "compacted": True,
        "original_length": len(history),
        "new_length": len(compacted_history),
        "summary_chars": len(summary),
        "history": compacted_history,
    }


async def llm_summarize(messages: list[dict], llm, max_chars: int) -> str:
    """Multi-stage LLM summarization of conversation history."""
    text_parts = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            text_parts.append(f"[{role}] {content[:500]}")
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    text_parts.append(f"[{role}] {c['text'][:500]}")

    full_text = "\n".join(text_parts)

    chunk_size = 6000
    if len(full_text) <= chunk_size:
        chunks = [full_text]
    else:
        chunks = [full_text[i : i + chunk_size] for i in range(0, len(full_text), chunk_size)]

    summaries = []
    for chunk in chunks:
        prompt = (
            "Summarize this conversation segment concisely. Preserve:\n"
            "- Key facts and decisions\n"
            "- User preferences and personal info\n"
            "- Tool call results and outcomes\n"
            "- Any unresolved questions or tasks\n\n"
            f"{chunk}"
        )
        try:
            response = await llm.chat([{"role": "user", "content": prompt}], tools=None)
            text, _ = llm.extract_response(response)
            summaries.append(text)
        except Exception as e:
            logger.warning(f"Summarization chunk failed: {e}")
            summaries.append(chunk[:500])

    result = "\n\n".join(summaries)
    return result[:max_chars]


def heuristic_summarize(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str) and content:
            lines.append(f"[{role}] {content[:100]}")
    return "\n".join(lines[-20:])


async def search_all(store, query: str, limit: int = 10) -> list[dict]:
    """Search across all memory tiers using hybrid ranking."""
    results = []

    episodes = await store.episode_search_hybrid(query, limit=limit)
    for item in episodes:
        results.append({**item, "tier": "episode", "score": item.get("relevance_score", 0)})

    notes = store.search(query, limit=limit)
    for note in notes:
        results.append({**note, "tier": "note", "score": note.get("relevance_score", 0.3)})

    knowledge = store.knowledge_search(query, limit=limit)
    for item in knowledge:
        results.append(
            {
                "tier": "knowledge",
                "score": 0.5,
                "summary": f"{item['subject']} {item['predicate']} {item['object']}",
                **item,
            }
        )

    if store._kg:
        entities = await store._kg.search_entities(query, limit=5)
        for entity in entities:
            results.append(
                {
                    "tier": "entity",
                    "score": entity.get("score", 0.5),
                    "summary": f"Entity: {entity['name']} ({entity.get('type', 'thing')})",
                    **entity,
                }
            )

    results.sort(key=lambda item: item.get("score", 0), reverse=True)
    return results[:limit]
