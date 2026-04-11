"""Tests for the 4-tier FERAL memory system."""
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
    def test_save_and_count(self, store):
        result = store.save("buy groceries")
        assert result["status"] == "saved"
        assert result["content"] == "buy groceries"
        assert store.count() == 1

    def test_search(self, store):
        store.save("meeting with John at 3pm")
        store.save("dentist appointment Friday")
        results = store.search("John")
        assert len(results) >= 1
        assert "John" in results[0]["content"]

    def test_list_recent(self, store):
        store.save("first")
        store.save("second")
        store.save("third")
        recent = store.list_recent(limit=2)
        assert len(recent) == 2
        assert recent[0]["content"] == "third"

    def test_delete(self, store):
        result = store.save("to delete")
        assert store.delete(result["id"]) is True
        assert store.count() == 0

    def test_delete_nonexistent(self, store):
        assert store.delete("nope") is False


# ─── Tier 1: Working Memory ───

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
    def test_save_and_search(self, store):
        store.episode_save("s1", "user_command", "User asked about weather in Paris")
        results = store.episode_search("weather Paris")
        assert len(results) >= 1
        assert "weather" in results[0]["summary"].lower() or "Paris" in results[0]["summary"]

    def test_recent(self, store):
        store.episode_save("s1", "observation", "User is cooking")
        store.episode_save("s1", "observation", "User asked for recipe")
        recent = store.episode_recent(limit=1)
        assert len(recent) == 1
        assert "recipe" in recent[0]["summary"]

    def test_session_filter(self, store):
        store.episode_save("s1", "cmd", "session 1 event")
        store.episode_save("s2", "cmd", "session 2 event")
        s1_only = store.episode_recent(limit=10, session_id="s1")
        assert all(e["session_id"] == "s1" for e in s1_only)


# ─── Tier 3: Semantic Memory ───

class TestSemanticMemory:
    def test_store_and_query(self, store):
        store.knowledge_store("user", "name_is", "Alice")
        results = store.knowledge_query(subject="user", predicate="name_is")
        assert len(results) == 1
        assert results[0]["object"] == "Alice"

    def test_upsert(self, store):
        store.knowledge_store("user", "favorite_color", "blue")
        store.knowledge_store("user", "favorite_color", "green")
        results = store.knowledge_query(subject="user", predicate="favorite_color")
        assert len(results) == 1
        assert results[0]["object"] == "green"

    def test_search(self, store):
        store.knowledge_store("user", "lives_in", "San Francisco")
        store.knowledge_store("user", "works_at", "FERAL")
        results = store.knowledge_search("San Francisco")
        assert len(results) >= 1

    def test_about(self, store):
        store.knowledge_store("user", "likes", "coffee")
        store.knowledge_store("user", "dislikes", "spam")
        about = store.knowledge_about("user")
        assert len(about) == 2


# ─── Tier 4: Execution Log ───

class TestExecutionLog:
    def test_log_and_retrieve(self, store):
        store.log_execution("s1", "web_search", "web_search", {"q": "test"}, "success", "Found 5 results", 120.5)
        logs = store.log_recent(skill_id="web_search")
        assert len(logs) == 1
        assert logs[0]["result_status"] == "success"

    def test_feedback(self, store):
        eid = store.log_execution("s1", "spotify", "play", {}, "success")
        store.log_feedback(eid, "worked great")
        logs = store.log_recent(skill_id="spotify")
        assert logs[0]["user_feedback"] == "worked great"

    def test_success_rate(self, store):
        store.log_execution("s1", "weather", "forecast", {}, "success")
        store.log_execution("s1", "weather", "forecast", {}, "success")
        store.log_execution("s1", "weather", "forecast", {}, "failure")
        rate = store.log_success_rate("weather")
        assert rate["total_executions"] == 3
        assert rate["successes"] == 2
        assert abs(rate["rate"] - 0.666) < 0.01


# ─── Unified Context Builder ───

class TestContextBuilder:
    def test_builds_nonempty(self, store):
        store.working_push("s1", {"role": "user", "text": "hello"})
        store.knowledge_store("user", "name", "Alice")
        store.episode_save("s1", "cmd", "Greeted")
        store.log_execution("s1", "web_search", "search", {}, "success")

        ctx = store.build_context_for_llm("s1", query="hello")
        assert len(ctx) > 0
        assert "Recent Context" in ctx or "Known Facts" in ctx

    def test_empty_session(self, store):
        ctx = store.build_context_for_llm("empty_session")
        assert ctx == ""


# ─── Stats ───

class TestStats:
    def test_stats(self, store):
        store.save("note")  # also creates a knowledge triple via cross-tier
        store.episode_save("s1", "cmd", "test")
        store.knowledge_store("a", "b", "c")
        store.log_execution("s1", "sk", "ep", {}, "ok")
        stats = store.stats()
        assert stats["notes"] == 1
        assert stats["episodes"] == 1
        assert stats["knowledge_triples"] == 2  # 1 from save cross-tier + 1 explicit
        assert stats["execution_logs"] == 1


class TestMemoryWiki:
    def test_compile_and_fetch_pages(self, store):
        store.save("I like Ethiopian coffee", tags=["preference"])
        store.episode_save("s1", "cmd", "Asked for coffee recommendations")
        store.knowledge_store("user", "likes", "coffee")

        compiled = store.wiki_compile(notes_limit=20, episodes_limit=20, knowledge_limit=20)
        assert compiled["compiled"] is True
        assert compiled["total_pages"] >= 1

        pages = store.wiki_list_pages(limit=20)
        assert len(pages) >= 1

        index_page = store.wiki_get_page("index")
        assert index_page is not None
        assert "Memory Wiki" in index_page["title"] or "Memory Wiki" in index_page["body_markdown"]


class TestSessionSnapshots:
    def test_snapshot_and_restore_payload(self, store):
        store.working_push("s1", {"role": "user", "text": "original"})
        history = [{"role": "user", "content": "hello"}]
        snap = store.snapshot_session(
            session_id="s1",
            history=history,
            label="checkpoint-1",
            branch_name="main",
        )
        assert snap["snapshot_id"]

        fetched = store.get_snapshot(snap["snapshot_id"])
        assert fetched is not None
        assert fetched["session_id"] == "s1"
        assert fetched["history"][0]["content"] == "hello"

        store.working_replace("s1", [{"role": "assistant", "text": "restored"}])
        restored = store.working_get("s1")
        assert restored[-1]["text"] == "restored"
