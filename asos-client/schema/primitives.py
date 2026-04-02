"""
THEORA GenUI Schema — The SDUI Primitive Vocabulary
====================================================
These are the ONLY UI components that exist in the system.
Skills don't design screens. They describe data.
The GenUI engine maps data to these primitives.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal, Any, Union
from uuid import uuid4


# ─────────────────────────────────────────────
# Layout Primitives
# ─────────────────────────────────────────────

class VStack(BaseModel):
    type: Literal["VStack"] = "VStack"
    children: list[Any] = []
    spacing: int = 12
    padding: int = 16
    alignment: Literal["leading", "center", "trailing"] = "leading"


class HStack(BaseModel):
    type: Literal["HStack"] = "HStack"
    children: list[Any] = []
    spacing: int = 8
    alignment: Literal["top", "center", "bottom"] = "center"


class ScrollView(BaseModel):
    type: Literal["ScrollView"] = "ScrollView"
    children: list[Any] = []
    direction: Literal["vertical", "horizontal"] = "vertical"


class Grid(BaseModel):
    type: Literal["Grid"] = "Grid"
    children: list[Any] = []
    columns: int = 2
    spacing: int = 12


# ─────────────────────────────────────────────
# Display Primitives
# ─────────────────────────────────────────────

class Text(BaseModel):
    type: Literal["Text"] = "Text"
    value: str
    style: Literal["title", "subtitle", "body", "caption", "headline"] = "body"
    color: Optional[str] = None  # hex or semantic ("primary", "secondary", "destructive")
    align: Literal["left", "center", "right"] = "left"


class AsyncImage(BaseModel):
    type: Literal["AsyncImage"] = "AsyncImage"
    url: str
    width: Optional[int] = None
    height: Optional[int] = None
    corner_radius: int = 8
    aspect_ratio: Literal["fill", "fit"] = "fit"


class Icon(BaseModel):
    type: Literal["Icon"] = "Icon"
    name: str  # SF Symbol name or material icon name
    size: int = 24
    color: Optional[str] = None


class Badge(BaseModel):
    type: Literal["Badge"] = "Badge"
    label: str
    color: str = "#007AFF"
    text_color: str = "#FFFFFF"


class ProgressBar(BaseModel):
    type: Literal["ProgressBar"] = "ProgressBar"
    value: float  # 0.0 to 1.0
    label: Optional[str] = None
    color: str = "#007AFF"


class Divider(BaseModel):
    type: Literal["Divider"] = "Divider"


class MetricCard(BaseModel):
    """Single KPI / health metric display."""
    type: Literal["MetricCard"] = "MetricCard"
    icon: str = "heart.fill"
    value: str = "72"
    unit: str = "bpm"
    label: str = "Heart Rate"
    color: str = "#FF3B30"
    trend: Optional[Literal["up", "down", "stable"]] = None


# ─────────────────────────────────────────────
# Interactive Primitives
# ─────────────────────────────────────────────

class Button(BaseModel):
    type: Literal["Button"] = "Button"
    action_id: str = Field(default_factory=lambda: f"btn_{uuid4().hex[:8]}")
    label: str
    style: Literal["primary", "secondary", "destructive", "ghost"] = "primary"
    icon: Optional[str] = None
    disabled: bool = False


class Toggle(BaseModel):
    type: Literal["Toggle"] = "Toggle"
    action_id: str = Field(default_factory=lambda: f"tgl_{uuid4().hex[:8]}")
    label: str
    initial_value: bool = False


class Slider(BaseModel):
    type: Literal["Slider"] = "Slider"
    action_id: str = Field(default_factory=lambda: f"sld_{uuid4().hex[:8]}")
    label: str
    min_value: float = 0
    max_value: float = 100
    step: float = 1
    initial_value: float = 50


class TextField(BaseModel):
    type: Literal["TextField"] = "TextField"
    action_id: str = Field(default_factory=lambda: f"txt_{uuid4().hex[:8]}")
    placeholder: str = ""
    keyboard_type: Literal["default", "email", "number", "url"] = "default"


# ─────────────────────────────────────────────
# Rich / Compound Primitives
# ─────────────────────────────────────────────

class MapView(BaseModel):
    type: Literal["MapView"] = "MapView"
    center_lat: float
    center_lon: float
    zoom: int = 14
    pins: list[dict] = []  # [{"lat": f, "lon": f, "label": str, "icon": str}]
    height: int = 250


class ChartLine(BaseModel):
    type: Literal["ChartLine"] = "ChartLine"
    data_points: list[dict] = []  # [{"x": str|num, "y": num}]
    x_label: str = ""
    y_label: str = ""
    color: str = "#007AFF"
    height: int = 200


class Card(BaseModel):
    """A styled container with optional image, title, and action."""
    type: Literal["Card"] = "Card"
    children: list[Any] = []
    image_url: Optional[str] = None
    background_color: Optional[str] = None
    corner_radius: int = 12
    action_id: Optional[str] = None  # If set, entire card is tappable


class SkillCard(BaseModel):
    """A card representing a registered skill in the marketplace."""
    type: Literal["SkillCard"] = "SkillCard"
    name: str
    description: str
    icon_url: str = ""
    action_id: str = ""
    connected: bool = False


# ─────────────────────────────────────────────
# Primitive Registry
# ─────────────────────────────────────────────

SDUI_PRIMITIVES = {
    # Layout
    "VStack": VStack,
    "HStack": HStack,
    "ScrollView": ScrollView,
    "Grid": Grid,
    # Display
    "Text": Text,
    "AsyncImage": AsyncImage,
    "Icon": Icon,
    "Badge": Badge,
    "ProgressBar": ProgressBar,
    "Divider": Divider,
    "MetricCard": MetricCard,
    # Interactive
    "Button": Button,
    "Toggle": Toggle,
    "Slider": Slider,
    "TextField": TextField,
    # Rich
    "MapView": MapView,
    "ChartLine": ChartLine,
    "Card": Card,
    "SkillCard": SkillCard,
}


def validate_sdui_tree(node: dict) -> bool:
    """Recursively validate that an SDUI tree only uses known primitives."""
    node_type = node.get("type")
    if node_type not in SDUI_PRIMITIVES:
        return False
    children = node.get("children", [])
    return all(validate_sdui_tree(child) for child in children)
