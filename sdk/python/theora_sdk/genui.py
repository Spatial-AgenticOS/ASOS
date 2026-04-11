"""
GenUI Components — Define custom Server-Driven UI components.

Return these from tool endpoints to render rich UI in the THEORA dashboard.

Usage::

    @theora_tool(description="Show weather")
    async def weather(self, city: str) -> dict:
        return GenUICard(
            title=f"Weather in {city}",
            children=[
                GenUIMetric(label="Temperature", value="72F", icon="thermometer"),
                GenUIMetric(label="Humidity", value="45%", icon="droplet"),
            ]
        ).to_sdui()
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenUIComponent:
    """Base class for all SDUI components."""
    type: str = "View"
    props: dict[str, Any] = field(default_factory=dict)
    children: list[GenUIComponent] = field(default_factory=list)

    def to_sdui(self) -> dict:
        result = {"type": self.type, **self.props}
        if self.children:
            result["children"] = [c.to_sdui() if isinstance(c, GenUIComponent) else c for c in self.children]
        return result


@dataclass
class GenUICard(GenUIComponent):
    title: str = ""
    subtitle: str = ""

    def __post_init__(self):
        self.type = "Card"
        self.props = {"title": self.title}
        if self.subtitle:
            self.props["subtitle"] = self.subtitle


@dataclass
class GenUIMetric(GenUIComponent):
    label: str = ""
    value: str = ""
    icon: str = ""
    trend: str = ""

    def __post_init__(self):
        self.type = "MetricCard"
        self.props = {"label": self.label, "value": self.value}
        if self.icon:
            self.props["icon"] = self.icon
        if self.trend:
            self.props["trend"] = self.trend


@dataclass
class GenUIList(GenUIComponent):
    items: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        self.type = "ListView"
        self.props = {"items": self.items}


@dataclass
class GenUIForm(GenUIComponent):
    """Interactive form component for SDUI."""
    fields: list[dict[str, Any]] = field(default_factory=list)
    submit_label: str = "Submit"
    action: str = ""

    def __post_init__(self):
        self.type = "FormView"
        self.props = {
            "fields": self.fields,
            "submitLabel": self.submit_label,
            "action": self.action,
        }


@dataclass
class GenUIMap(GenUIComponent):
    """Map component for location-aware SDUI."""
    latitude: float = 0.0
    longitude: float = 0.0
    zoom: int = 13
    markers: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self.type = "MapView"
        self.props = {
            "center": [self.latitude, self.longitude],
            "zoom": self.zoom,
            "markers": self.markers,
        }


@dataclass
class GenUIMediaPlayer(GenUIComponent):
    """Audio/video player component."""
    src: str = ""
    media_type: str = "audio"
    title: str = ""

    def __post_init__(self):
        self.type = "MediaPlayer"
        self.props = {"src": self.src, "mediaType": self.media_type}
        if self.title:
            self.props["title"] = self.title
