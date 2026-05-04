"""Tests for HybridGenerator — authored vs generated vs hybrid render."""

from __future__ import annotations

import json

import pytest

from agents.app_registry import (
    HybridGenerator,
    _hydrate,
    _resolve_placeholder,
)
from models.app_manifest import (
    ActionSpec,
    AppManifest,
    InteractionRules,
    SurfaceSpec,
)
from models.skill_manifest import BrandProfile


class FakeGenUIEngine:
    def __init__(self, tree=None, raises=False):
        self._tree = tree or {
            "type": "Card",
            "children": [{"type": "Text", "value": "from llm"}],
        }
        self._raises = raises
        self.calls = []

    async def generate_from_prompt(self, prompt, context=None):
        self.calls.append({"prompt": prompt, "context": context})
        if self._raises:
            raise RuntimeError("LLM is down")
        return self._tree


def _manifest(surfaces, entry="home") -> AppManifest:
    return AppManifest(
        app_id="demo-app",
        brand=BrandProfile(name="Demo"),
        surfaces=surfaces,
        entry_surface_id=entry,
        interactions=InteractionRules(prose_guidance="Never show raw IDs."),
    )


@pytest.fixture
def tmp_cache(tmp_path):
    return tmp_path / "cache"


class TestHydrate:
    def test_replaces_simple_placeholder(self):
        tree = {"type": "Text", "value": "$data.name"}
        out = _hydrate(tree, {"name": "Mahmoud"})
        assert out["value"] == "Mahmoud"

    def test_replaces_curly_placeholder(self):
        out = _resolve_placeholder("${data.greeting}", {"greeting": "hello"})
        assert out == "hello"

    def test_missing_path_becomes_empty_string(self):
        out = _resolve_placeholder("$data.missing", {})
        assert out == ""

    def test_walks_nested_lists_and_dicts(self):
        tree = {
            "type": "VStack",
            "children": [
                {"type": "Text", "value": "$data.a"},
                {"type": "Text", "value": "$data.b"},
            ],
        }
        out = _hydrate(tree, {"a": "A!", "b": "B!"})
        assert out["children"][0]["value"] == "A!"
        assert out["children"][1]["value"] == "B!"

    def test_non_placeholder_strings_untouched(self):
        out = _resolve_placeholder("not a ref", {})
        assert out == "not a ref"


class TestAuthoredSurfaces:
    @pytest.mark.asyncio
    async def test_authored_hydrates_and_never_calls_llm(self, tmp_cache):
        engine = FakeGenUIEngine()
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="home",
            kind="authored",
            template_root={"type": "Text", "value": "$data.msg"},
            action_contract=[],
        )
        manifest = _manifest([surface])
        tree = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={"msg": "hi"},
        )
        assert tree == {"type": "Text", "value": "hi"}
        assert engine.calls == []


class TestGeneratedSurfaces:
    @pytest.mark.asyncio
    async def test_generated_first_open_calls_llm_and_caches(self, tmp_cache):
        engine = FakeGenUIEngine()
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="gen",
            kind="generated",
            generation_prompt="build a gen surface",
            action_contract=[
                ActionSpec(action_id="close", handler="close"),
            ],
        )
        manifest = _manifest([surface], entry="gen")
        tree1 = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
            user_fingerprint="user-a",
        )
        assert tree1["type"] == "Card"
        assert len(engine.calls) == 1

        # Second open hits cache.
        tree2 = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
            user_fingerprint="user-a",
        )
        assert tree2 == tree1
        assert len(engine.calls) == 1, "LLM should not fire again"

    @pytest.mark.asyncio
    async def test_generated_prefers_publisher_default_before_llm(
        self, tmp_cache, tmp_path
    ):
        engine = FakeGenUIEngine()
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        bundle = tmp_path / "bundle"
        (bundle / "surfaces").mkdir(parents=True)
        (bundle / "surfaces" / "gen.default.json").write_text(
            json.dumps({"type": "Text", "value": "shipped-default"})
        )
        surface = SurfaceSpec(
            surface_id="gen",
            kind="generated",
            generation_prompt="build",
            action_contract=[],
        )
        manifest = _manifest([surface], entry="gen")
        tree = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
            bundle_dir=bundle,
            user_fingerprint="user-a",
        )
        assert tree == {"type": "Text", "value": "shipped-default"}
        assert engine.calls == [], "LLM should not fire when a default is shipped"

    @pytest.mark.asyncio
    async def test_generated_falls_back_when_llm_raises(self, tmp_cache):
        engine = FakeGenUIEngine(raises=True)
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="gen",
            kind="generated",
            generation_prompt="build",
            action_contract=[],
        )
        manifest = _manifest([surface], entry="gen")
        tree = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
        )
        # Deterministic fallback still renders the brand header + surface title.
        assert tree["type"] == "Card"
        assert any(
            isinstance(c, dict) and "Demo" in str(c.get("value", ""))
            for c in tree.get("children", [])
        )


class TestHybridSurfaces:
    @pytest.mark.asyncio
    async def test_hybrid_default_is_authored_template(self, tmp_cache):
        engine = FakeGenUIEngine()
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="home",
            kind="hybrid",
            template_root={"type": "Text", "value": "$data.x"},
            generation_prompt="fallback",
            action_contract=[],
        )
        manifest = _manifest([surface])
        tree = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={"x": "authored"},
        )
        assert tree == {"type": "Text", "value": "authored"}
        assert engine.calls == []

    @pytest.mark.asyncio
    async def test_hybrid_regenerate_hits_llm_and_caches(self, tmp_cache):
        engine = FakeGenUIEngine(tree={"type": "Text", "value": "personal"})
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="home",
            kind="hybrid",
            template_root={"type": "Text", "value": "$data.x"},
            generation_prompt="fallback",
            action_contract=[],
        )
        manifest = _manifest([surface])
        tree = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
            regenerate=True,
            user_fingerprint="user-a",
        )
        assert tree == {"type": "Text", "value": "personal"}
        assert len(engine.calls) == 1

        # Subsequent open w/o regenerate hits the cache, NOT the authored template.
        tree2 = await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
            user_fingerprint="user-a",
        )
        assert tree2 == {"type": "Text", "value": "personal"}
        assert len(engine.calls) == 1


class TestCachePurge:
    @pytest.mark.asyncio
    async def test_purge_app_cache_removes_all_renders(self, tmp_cache):
        engine = FakeGenUIEngine(tree={"type": "Text", "value": "x"})
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="gen",
            kind="generated",
            generation_prompt="g",
            action_contract=[],
        )
        manifest = _manifest([surface], entry="gen")
        await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
            user_fingerprint="user-a",
        )
        await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={},
            user_fingerprint="user-b",
        )
        count = gen.purge_app_cache("demo-app")
        assert count == 2
        assert gen.purge_app_cache("demo-app") == 0  # idempotent


class TestRenderTraces:
    @pytest.mark.asyncio
    async def test_render_writes_audit_trace(self, tmp_cache):
        gen = HybridGenerator(genui_engine=FakeGenUIEngine(), cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="home",
            kind="authored",
            template_root={"type": "Text", "value": "$data.msg"},
            action_contract=[],
        )
        manifest = _manifest([surface], entry="home")

        await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={"msg": "hello"},
            user_fingerprint="trace-user",
        )

        trace_file = tmp_cache / "_render_traces" / "demo-app" / "home.jsonl"
        assert trace_file.exists()
        lines = [line for line in trace_file.read_text().splitlines() if line.strip()]
        assert lines
        row = json.loads(lines[-1])
        assert row["source"] == "authored_template"
        assert row["app_id"] == "demo-app"
        assert row["surface_schema_version"] == 1
        assert row["user_fingerprint_hash"]


class TestLLMPromptIncludesRules:
    @pytest.mark.asyncio
    async def test_llm_prompt_contains_interaction_rules(self, tmp_cache):
        engine = FakeGenUIEngine()
        gen = HybridGenerator(genui_engine=engine, cache_dir=tmp_cache)
        surface = SurfaceSpec(
            surface_id="gen",
            kind="generated",
            generation_prompt="build the welcome surface",
            action_contract=[
                ActionSpec(action_id="close", handler="close"),
            ],
        )
        manifest = _manifest([surface], entry="gen")
        await gen.render(
            app_id="demo-app",
            manifest=manifest,
            surface=surface,
            data={"user": "A"},
        )
        assert len(engine.calls) == 1
        prompt = engine.calls[0]["prompt"]
        assert "Never show raw IDs" in prompt
        assert "close" in prompt
        assert "build the welcome surface" in prompt
