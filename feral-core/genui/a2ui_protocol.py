"""A2UI Protocol — Agent-to-User Interface wire format for FERAL GenUI.

Formal message types following Google's A2UI specification, adapted for
FERAL's autonomous generation engine. This enables reactive data binding,
incremental updates, and multi-renderer support.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class MessageType(str, Enum):
    BEGIN_RENDERING = "beginRendering"
    SURFACE_UPDATE = "surfaceUpdate"
    DATA_MODEL_UPDATE = "dataModelUpdate"
    DELETE_SURFACE = "deleteSurface"


class ComponentType(str, Enum):
    TEXT = "Text"
    IMAGE = "Image"
    ICON = "Icon"
    VIDEO = "Video"
    AUDIO_PLAYER = "AudioPlayer"
    BUTTON = "Button"
    CHECKBOX = "Checkbox"
    TEXT_FIELD = "TextField"
    SLIDER = "Slider"
    DATE_TIME_INPUT = "DateTimeInput"
    MULTIPLE_CHOICE = "MultipleChoice"
    ROW = "Row"
    COLUMN = "Column"
    LIST = "List"
    CARD = "Card"
    TABS = "Tabs"
    DIVIDER = "Divider"
    MODAL = "Modal"
    # FERAL extensions
    MAP_VIEW = "MapView"
    CHART = "Chart"
    METRIC_CARD = "MetricCard"
    GRAPH_VIEW = "GraphView"
    CODE_BLOCK = "CodeBlock"
    PROGRESS_BAR = "ProgressBar"
    TABLE = "Table"
    WEB_VIEW = "WebView"


@dataclass
class StringValue:
    """A2UI string value — either literal or data-bound."""
    literal: Optional[str] = None
    path: Optional[str] = None

    def resolve(self, data_model: dict) -> str:
        if self.literal is not None:
            return self.literal
        if self.path:
            parts = self.path.strip("/").split("/")
            current = data_model
            for p in parts:
                if isinstance(current, dict):
                    current = current.get(p, "")
                else:
                    return ""
            return str(current)
        return ""

    def to_dict(self) -> dict:
        if self.literal is not None:
            return {"literalString": self.literal}
        return {"path": self.path}


@dataclass
class A2UIComponent:
    """A single UI component in the A2UI tree."""
    component_id: str = field(default_factory=lambda: str(uuid4())[:8])
    component_type: ComponentType = ComponentType.TEXT
    properties: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "componentId": self.component_id,
            "type": self.component_type.value,
            "properties": self.properties,
            "children": self.children,
        }


@dataclass
class A2UISurface:
    """A renderable surface containing a component tree + data model."""
    surface_id: str = field(default_factory=lambda: str(uuid4())[:8])
    catalog_id: str = "ai.feral.genui"
    root_component_id: Optional[str] = None
    components: dict[str, A2UIComponent] = field(default_factory=dict)
    data_model: dict[str, Any] = field(default_factory=dict)

    def add_component(self, component: A2UIComponent) -> str:
        self.components[component.component_id] = component
        if self.root_component_id is None:
            self.root_component_id = component.component_id
        return component.component_id

    def to_dict(self) -> dict:
        return {
            "surfaceId": self.surface_id,
            "catalogId": self.catalog_id,
            "rootComponentId": self.root_component_id,
            "components": {cid: c.to_dict() for cid, c in self.components.items()},
            "dataModel": self.data_model,
        }


A2UI_VERSION = "1.0"

# Future work — tracked at https://github.com/FERAL-AI/FERAL-AI/issues/82.
# This module intentionally does NOT expose any
# ``verify_marketplace_signature`` symbol today; the contract test
# ``test_a2ui_marketplace_trust_unimplemented_contract`` pins that
# fact so future code can't silently behave as if signed trust were
# already enforced. When the v2 verifier lands it must satisfy the
# exit criteria in issue #82 (rendering badge, fail-closed install,
# pytest coverage).


@dataclass
class A2UIMessage:
    """A wire-format message from server to client."""
    message_type: MessageType
    surface_id: str
    payload: dict = field(default_factory=dict)
    a2ui_version: str = A2UI_VERSION

    @staticmethod
    def begin_rendering(surface: A2UISurface) -> A2UIMessage:
        return A2UIMessage(
            message_type=MessageType.BEGIN_RENDERING,
            surface_id=surface.surface_id,
            payload=surface.to_dict(),
        )

    @staticmethod
    def surface_update(surface_id: str, components: list[A2UIComponent]) -> A2UIMessage:
        return A2UIMessage(
            message_type=MessageType.SURFACE_UPDATE,
            surface_id=surface_id,
            payload={"components": [c.to_dict() for c in components]},
        )

    @staticmethod
    def data_model_update(surface_id: str, patches: dict) -> A2UIMessage:
        return A2UIMessage(
            message_type=MessageType.DATA_MODEL_UPDATE,
            surface_id=surface_id,
            payload={"patches": patches},
        )

    @staticmethod
    def delete_surface(surface_id: str) -> A2UIMessage:
        return A2UIMessage(
            message_type=MessageType.DELETE_SURFACE,
            surface_id=surface_id,
        )

    def to_dict(self) -> dict:
        return {
            "a2ui_version": self.a2ui_version,
            "type": self.message_type.value,
            "surfaceId": self.surface_id,
            **self.payload,
        }
