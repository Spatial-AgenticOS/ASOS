"""Tests for the 4-tier FERAL memory system. Async-native since
v2026.5.33 (Option C). Every MemoryStore method that touches I/O is a
coroutine — tests are ``async def`` + ``await`` accordingly."""
import os
import tempfile
import pytest
from memory.store import MemoryStore


@pytest.fixture
def store():
    """Create a temp-file memory store for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = MemoryStore(db_path=path)
    yield s
    os.unlink(path)


# ─── Tier 0: Legacy Notes ───

class TestNotes:
    async def test_save_and_count(self, store):
        result = await store.save("buy groceries")
        assert result["status"] == "saved"
        assert result["content"] == "buy groceries"
        assert await store.count() == 1

    async def test_search(self, store):
        await store.save("meeting with John at 3pm")
        await store.save("dentist appointment Friday")
        results = await store.search("John")
        assert len(results) >= 1
        assert "John" in results[0]["content"]

    async def test_list_recent(self, store):
        await store.save("first")
        await store.save("second")
        await store.save("third")
        recent = await store.list_recent(limit=2)
        assert len(recent) == 2
        assert recent[0]["content"] == "third"

    async def test_delete(self, store):
        result = await store.save("to delete")
        assert await store.delete(result["id"]) is True
        assert await store.count() == 0

    async def test_delete_nonexistent(self, store):
        assert await store.delete("nope") is False


# ─── Tier 1: Working Memory (sync — in-RAM only) ───

class TestWorkingMemory:
    def test_push_and_get(self, store):
        store.working_push("s1", {"role": "user", "text": "hello"})
        store.working_push("s1", {"role": "assistant", "text": "hi there"})
        entries = store.working_get("s1")
        assert len(entries) == 2
        assert entries[0]["role"] == "user"

    def test_context_string(self, store):
        store.working_push("s1", {"role": "user", "text": "what's my heart rate?"})
        store.working_push("s1", {"role": "assistant", "text": "Your heart rate is 72 BPM."})
        ctx = store.working_context_string("s1")
        assert "heart rate" in ctx

    def test_clear(self, store):
        store.working_push("s1", {"role": "user", "text": "test"})
        store.working_clear("s1")
        assert store.working_get("s1") == []

    def test_isolation(self, store):
        store.working_push("s1", {"role": "user", "text": "session 1"})
        store.working_push("s2", {"role": "user", "text": "session 2"})
        assert len(store.working_get("s1")) == 1
        assert len(store.working_get("s2")) == 1


# ─── Tier 2: Episodic Memory ───

class TestEpisodicMemory:
    async def test_save_and_search(self, store):
        await store.episode_save("s1", "user_command", "User asked about weather in Paris")
        results = await store.episode_search("weather Paris")
        assert len(results) >= 1
        assert "weather" in results[0]["summary"].lower() or "Paris" in results[0]["summary"]

    async def test_recent(self, store):
        await store.episode_save("s1", "observation", "User is cooking")
        await store.episode_save("s1", "observation", "User asked for recipe")
        recent = await store.episode_recent(limit=1)
        assert len(recent) == 1
        assert "recipe" in recent[0]["summary"]

    async def test_session_filter(self, store):
        await store.episode_save("s1", "cmd", "session 1 event")
        await store.episode_save("s2", "cmd", "session 2 event")
        s1_only = await store.episode_recent(limit=10, session_id="s1")
        assert all(e["session_id"] == "s1" for e in s1_only)


# ─── Tier 3: Semantic Memory ───

class TestSemanticMemory:
    async def test_store_and_query(self, store):
        await store.knowledge_store("user", "name_is", "Alice")
        results = await store.knowledge_query(subject="user", predicate="name_is")
        assert len(results) == 1
        assert results[0]["object"] == "Alice"

    async def test_upsert(self, store):
        await store.knowledge_store("user", "favorite_color", "blue")
        await store.knowledge_store("user", "favorite_color", "green")
        results = await store.knowledge_query(subject="user", predicate="favorite_color")
        assert len(results) == 1
        assert results[0]["object"] == "green"

    async def test_search(self, store):
        await store.knowledge_store("user", "lives_in", "San Francisco")
        await store.knowledge_store("user", "works_at", "FERAL")
        results = await store.knowledge_search("San Francisco")
        assert len(results) >= 1

    async def test_about(self, store):
        await store.knowledge_store("user", "likes", "coffee")
        await store.knowledge_store("user", "dislikes", "spam")
        about = await store.knowledge_about("user")
        assert len(about) == 2


# ─── Tier 4: Execution Log ───

class TestExecutionLog:
    async def test_log_and_retrieve(self, store):
        await store.log_execution("s1", "web_search", "web_search", {"q": "test"}, "success", "Found 5 results", 120.5)
        logs = await store.log_recent(skill_id="web_search")
        assert len(logs) == 1
        assert logs[0]["result_status"] == "success"

    async def test_feedback(self, store):
        eid = await store.log_execution("s1", "spotify", "play", {}, "success")
        await store.log_feedback(eid, "worked great")
        logs = await store.log_recent(skill_id="spotify")
        assert logs[0]["user_feedback"] == "worked great"

    async def test_success_rate(self, store):
        await store.log_execution("s1", "weather", "forecast", {}, "success")
        await store.log_execution("s1", "weather", "forecast", {}, "success")
        await store.log_execution("s1", "weather", "forecast", {}, "failure")
        rate = await store.log_success_rate("weather")
        assert rate["total_executions"] == 3
        assert rate["successes"] == 2
        assert abs(rate["rate"] - 0.666) < 0.01


# ─── Unified Context Builder ───

class TestContextBuilder:
    async def test_builds_nonempty(self, store):
        store.working_push("s1", {"role": "user", "text": "hello"})
        await store.knowledge_store("user", "name", "Alice")
        await store.episode_save("s1", "cmd", "Greeted")
        await store.log_execution("s1", "web_search", "search", {}, "success")

        ctx = await store.build_context_for_llm("s1", query="hello")
        assert len(ctx) > 0
        assert "Recent Context" in ctx or "Known Facts" in ctx

    async def test_empty_session(self, store):
        ctx = await store.build_context_for_llm("empty_session")
        assert ctx == ""


# ─── Stats ───

class TestStats:
    async def test_stats(self, store):
        await store.save("note")  # also creates a knowledge triple via cross-tier
        await store.episode_save("s1", "cmd", "test")
        await store.knowledge_store("a", "b", "c")
        await store.log_execution("s1", "sk", "ep", {}, "ok")
        stats = await store.stats()
        assert stats["notes"] == 1
        assert stats["episodes"] == 1
        assert stats["knowledge_triples"] == 2  # 1 from save cross-tier + 1 explicit
        assert stats["execution_logs"] == 1


class TestMemoryWiki:
    async def test_compile_and_fetch_pages(self, store):
        await store.save("I like Ethiopian coffee", tags=["preference"])
        await store.episode_save("s1", "cmd", "Asked for coffee recommendations")
        await store.knowledge_store("user", "likes", "coffee")

        compiled = await store.wiki_compile(notes_limit=20, episodes_limit=20, knowledge_limit=20)
        assert compiled["compiled"] is True
        assert compiled["total_pages"] >= 1

        pages = await store.wiki_list_pages(limit=20)
        assert len(pages) >= 1

        index_page = await store.wiki_get_page("index")
        assert index_page is not None
        assert "Memory Wiki" in index_page["title"] or "Memory Wiki" in index_page["body_markdown"]


class TestSessionSnapshots:
    async def test_snapshot_and_restore_payload(self, store):
        store.working_push("s1", {"role": "user", "text": "original"})
        history = [{"role": "user", "content": "hello"}]
        snap = await store.snapshot_session(
            session_id="s1",
            history=history,
            label="checkpoint-1",
            branch_name="main",
        )
        assert snap["snapshot_id"]

        fetched = await store.get_snapshot(snap["snapshot_id"])
        assert fetched is not None
        assert fetched["session_id"] == "s1"
        assert fetched["history"][0]["content"] == "hello"

        store.working_replace("s1", [{"role": "assistant", "text": "restored"}])
        restored = store.working_get("s1")
        assert restored[-1]["text"] == "restored"
