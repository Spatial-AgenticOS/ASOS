"""Cross-client contract tests for the A2UI / GenUI protocol."""
import json

import pytest

from genui.a2ui_protocol import (
    A2UI_VERSION,
    A2UIComponent,
    A2UIMessage,
    A2UISurface,
    ComponentType,
    MessageType,
    StringValue,
)
from genui.generator import GenUIEngine, SDUI_COMPONENT_SCHEMA


# ── JSON schema validation ───────────────────────────────────────────────────

def _validate_a2ui_event(event: dict):
    """Assert the GenUI event satisfies the A2UI wire format."""
    assert "type" in event, "event must have 'type'"
    assert "surfaceId" in event, "event must have 'surfaceId'"
    assert "a2ui_version" in event, "event must have 'a2ui_version'"
    assert event["a2ui_version"] == A2UI_VERSION
    if "components" in event:
        comps = event["components"]
        items = comps.values() if isinstance(comps, dict) else comps
        for comp in items:
            assert "type" in comp
            assert "componentId" in comp


class TestA2UISchema:
    def test_begin_rendering_schema(self):
        surface = A2UISurface()
        root = A2UIComponent(component_type=ComponentType.COLUMN)
        surface.add_component(root)
        msg = A2UIMessage.begin_rendering(surface)
        event = msg.to_dict()
        _validate_a2ui_event(event)
        assert event["type"] == "beginRendering"

    def test_surface_update_schema(self):
        comp = A2UIComponent(component_type=ComponentType.TEXT, properties={"value": "hello"})
        msg = A2UIMessage.surface_update("surf1", [comp])
        event = msg.to_dict()
        _validate_a2ui_event(event)
        assert event["type"] == "surfaceUpdate"
        assert len(event["components"]) == 1

    def test_data_model_update_schema(self):
        msg = A2UIMessage.data_model_update("surf1", {"count": 42})
        event = msg.to_dict()
        _validate_a2ui_event(event)
        assert event["type"] == "dataModelUpdate"

    def test_delete_surface_schema(self):
        msg = A2UIMessage.delete_surface("surf1")
        event = msg.to_dict()
        _validate_a2ui_event(event)
        assert event["type"] == "deleteSurface"


# ── Core component round-trip ────────────────────────────────────────────────

CORE_TYPES = [
    ("container", ComponentType.COLUMN),
    ("text", ComponentType.TEXT),
    ("button", ComponentType.BUTTON),
    ("card", ComponentType.CARD),
    ("list", ComponentType.LIST),
]


class TestCoreComponentRoundTrip:
    @pytest.mark.parametrize("label,comp_type", CORE_TYPES)
    def test_component_round_trip(self, label, comp_type):
        comp = A2UIComponent(
            component_type=comp_type,
            properties={"value": f"test-{label}"},
        )
        d = comp.to_dict()
        assert d["type"] == comp_type.value
        assert d["properties"]["value"] == f"test-{label}"
        assert "componentId" in d

    @pytest.mark.parametrize("label,comp_type", CORE_TYPES)
    def test_component_serializes_to_json(self, label, comp_type):
        comp = A2UIComponent(
            component_type=comp_type,
            properties={"value": f"test-{label}"},
        )
        serialized = json.dumps(comp.to_dict())
        deserialized = json.loads(serialized)
        assert deserialized["type"] == comp_type.value


# ── Server emit deserialization ──────────────────────────────────────────────

class TestServerEmitDeserialization:
    def test_full_surface_emit_deserializes(self):
        surface = A2UISurface(data_model={"title": "Test"})
        root = A2UIComponent(component_type=ComponentType.COLUMN)
        text = A2UIComponent(component_type=ComponentType.TEXT, properties={"value": "Hello"})
        btn = A2UIComponent(component_type=ComponentType.BUTTON, properties={"label": "Click"})
        root.children = [text.component_id, btn.component_id]

        surface.add_component(root)
        surface.add_component(text)
        surface.add_component(btn)

        msg = A2UIMessage.begin_rendering(surface)
        payload_json = json.dumps(msg.to_dict())
        payload = json.loads(payload_json)

        _validate_a2ui_event(payload)
        assert payload["rootComponentId"] == root.component_id
        assert len(payload["components"]) == 3
        assert payload["dataModel"]["title"] == "Test"


# ── Version field ────────────────────────────────────────────────────────────

class TestVersionField:
    def test_version_present(self):
        msg = A2UIMessage.delete_surface("x")
        assert msg.a2ui_version == "1.0"

    def test_version_in_dict(self):
        msg = A2UIMessage.delete_surface("x")
        d = msg.to_dict()
        assert d["a2ui_version"] == "1.0"

    def test_version_constant(self):
        assert A2UI_VERSION == "1.0"


# ── StringValue data binding ─────────────────────────────────────────────────

class TestStringValueBinding:
    def test_literal(self):
        sv = StringValue(literal="hello")
        assert sv.resolve({}) == "hello"

    def test_path_binding(self):
        sv = StringValue(path="user/name")
        assert sv.resolve({"user": {"name": "Alice"}}) == "Alice"

    def test_missing_path(self):
        sv = StringValue(path="missing/key")
        assert sv.resolve({}) == ""


# ── GenUI engine fallback (SDUI) ─────────────────────────────────────────────

class TestGenUIEngineFallback:
    def test_fallback_text_produces_valid_sdui(self):
        result = GenUIEngine._fallback_text("Something happened")
        assert result["type"] == "VStack"
        assert "children" in result
        assert result["children"][0]["type"] == "Text"

    def test_sdui_schema_requires_type(self):
        assert "type" in SDUI_COMPONENT_SCHEMA["required"]
