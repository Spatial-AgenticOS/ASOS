"""Tests for THEORA GenUI generator and service providers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from genui.generator import (
    SDUI_COMPONENT_SCHEMA,
    GenUIEngine,
    ServiceProvider,
    ServiceProviderRegistry,
)


class TestGenUIEngineInit:
    """Engine construction."""

    def test_init_without_error(self):
        engine = GenUIEngine()
        assert engine._providers == {}

    def test_init_with_mock_llm(self):
        llm = MagicMock()
        llm.available = False
        engine = GenUIEngine(llm=llm)
        assert engine._llm is llm


class TestGenerateForData:
    """Deterministic UI from structured data."""

    @pytest.mark.asyncio
    async def test_location_returns_map_structure(self):
        llm = MagicMock()
        engine = GenUIEngine(llm=llm)
        data = {"lat": 37.77, "lon": -122.42, "label": "SF"}
        ui = await engine.generate_for_data(data, ui_hint="map")
        assert ui["type"] == "VStack"
        children = ui.get("children", [])
        assert any(c.get("type") == "MapView" for c in children)
        map_node = next(c for c in children if c.get("type") == "MapView")
        assert map_node.get("lat") == 37.77
        assert map_node.get("lon") == -122.42


class TestServiceProvider:
    """Component registration and SDUI rendering."""

    def test_register_and_render_template(self):
        sp = ServiceProvider("p1", "Test")
        sp.register_component(
            "card",
            {
                "template": {
                    "type": "Text",
                    "value": "$title",
                }
            },
        )
        out = sp.render("card", {"title": "Hello"})
        assert out == {"type": "Text", "value": "Hello"}


class TestServiceProviderRegistry:
    """Registry of external UI providers."""

    def test_register_and_list(self):
        reg = ServiceProviderRegistry()
        cfg = {
            "provider_id": "acme",
            "name": "Acme",
            "description": "demo",
            "components": [{"id": "widget", "schema": {}}],
            "brand": {"primary_color": "#111827", "theme": "dark"},
            "ui_rules": {"layout_mode": "fixed", "brand_mode": "strict"},
            "cache_policy": {"mode": "static"},
            "endpoints": [{"id": "rides", "method": "GET", "path": "/rides"}],
            "surfaces": [{"id": "home", "title": "Home", "entry": True}],
        }
        p = reg.register(cfg)
        assert p.provider_id == "acme"
        listed = reg.list_providers()
        assert len(listed) == 1
        assert listed[0]["provider_id"] == "acme"
        assert "widget" in listed[0]["components"]
        assert listed[0]["brand"]["primary_color"] == "#111827"
        assert listed[0]["ui_rules"]["layout_mode"] == "fixed"
        assert listed[0]["cache_policy"]["mode"] == "static"
        assert listed[0]["endpoint_count"] == 1
        assert listed[0]["surface_ids"] == ["home"]


class TestProviderSurfaceCaching:
    """Provider-defined app surfaces compile once and stay stable."""

    @pytest.mark.asyncio
    async def test_compile_surface_caches_template_layout(self, tmp_path):
        engine = GenUIEngine(cache_dir=tmp_path)
        provider = ServiceProvider(
            "rides",
            "RideOS",
            brand={"primary_color": "#10b981"},
            ui_rules={"layout_mode": "fixed", "brand_mode": "strict"},
            cache_policy={"mode": "static"},
        )
        provider.register_surface(
            "home",
            {
                "title": "Home",
                "entry": True,
                "template": {
                    "type": "VStack",
                    "children": [
                        {"type": "Text", "value": "$headline", "style": "headline"},
                        {"type": "Button", "label": "$cta_label", "action_id": "request_ride"},
                    ],
                },
            },
        )
        engine.register_provider(provider)

        first = await engine.compile_provider_surface("rides", "home")
        second = await engine.compile_provider_surface("rides", "home")

        assert first["ok"] is True
        assert first["cache_hit"] is False
        assert first["metadata"]["layout_mode"] == "fixed"
        assert second["ok"] is True
        assert second["cache_hit"] is True
        assert second["payload"]["type"] == "VStack"

    @pytest.mark.asyncio
    async def test_render_surface_hydrates_cached_layout(self, tmp_path):
        engine = GenUIEngine(cache_dir=tmp_path)
        provider = ServiceProvider(
            "rides",
            "RideOS",
            cache_policy={"mode": "static"},
        )
        provider.register_surface(
            "home",
            {
                "title": "Home",
                "template": {
                    "type": "Card",
                    "children": [
                        {"type": "Text", "value": "$headline"},
                        {"type": "Text", "value": "$eta"},
                    ],
                },
            },
        )
        engine.register_provider(provider)

        result = await engine.render_provider_surface(
            "rides",
            "home",
            data={"headline": "Pick your ride", "eta": "2 min away"},
        )

        assert result["ok"] is True
        assert result["payload"]["children"][0]["value"] == "Pick your ride"
        assert result["payload"]["children"][1]["value"] == "2 min away"
        assert result["layout"]["children"][0]["value"] == "$headline"


class TestSDUISchema:
    """JSON schema component enum."""

    def test_contains_expected_component_types(self):
        enum_vals = SDUI_COMPONENT_SCHEMA["properties"]["type"]["enum"]
        for name in (
            "VStack",
            "MapView",
            "Chart",
            "Button",
            "MetricCard",
            "WebView",
        ):
            assert name in enum_vals
