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
        }
        p = reg.register(cfg)
        assert p.provider_id == "acme"
        listed = reg.list_providers()
        assert len(listed) == 1
        assert listed[0]["provider_id"] == "acme"
        assert "widget" in listed[0]["components"]


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
