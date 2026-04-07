"""
THEORA GenUI Generator — Structured UI Generation
====================================================
LLM generates SDUI JSON via structured output.
Service provider SDK for external integrations.

Components: VStack, HStack, Text, Card, Button, Image, MapView, Chart,
AudioPlayer, VideoPlayer, Form, Table, CodeBlock, Markdown, ProgressBar, Skeleton.
"""

from __future__ import annotations
import json
import logging
import time
from typing import Optional
from uuid import uuid4

logger = logging.getLogger("theora.genui")

SDUI_COMPONENT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": [
            "VStack", "HStack", "Text", "Card", "Button", "Image", "MapView",
            "Chart", "AudioPlayer", "VideoPlayer", "Form", "Table", "CodeBlock",
            "Markdown", "ProgressBar", "Skeleton", "Badge", "Divider", "Icon",
            "MetricCard", "Grid", "ScrollView", "WebView", "Spacer",
        ]},
        "children": {"type": "array", "items": {"$ref": "#"}},
        "value": {}, "label": {"type": "string"},
        "style": {"type": "string"}, "color": {"type": "string"},
        "action_id": {"type": "string"}, "url": {"type": "string"},
        "spacing": {"type": "integer"}, "padding": {"type": "integer"},
    },
    "required": ["type"],
}

GENUI_SYSTEM_PROMPT = """You generate SDUI (Server-Driven UI) JSON components.
Available types: VStack, HStack, Text, Card, Button, Image, MapView, Chart,
AudioPlayer, VideoPlayer, Form, Table, CodeBlock, Markdown, ProgressBar,
MetricCard, Grid, Badge, Divider, Icon, WebView, Skeleton.

Rules:
- Output ONLY valid JSON (no markdown, no explanation)
- Root must be a single component (usually VStack)
- Use semantic colors: #6c5ce7 (accent), #00b894 (success), #e17055 (error)
- Text styles: headline, subtitle, body, caption
- Cards have corner_radius, children array
- Charts need: data (array), chart_type (line/bar), label
- Forms need: fields [{name, type, label, placeholder}], submit_label, action_id
- Maps need: lat, lon, zoom, markers [{lat, lon, label}]
- Tables need: headers [], rows [[]]
"""


class GenUIEngine:
    """Production GenUI engine with LLM structured output."""

    def __init__(self, llm=None):
        self._llm = llm
        self._providers: dict[str, ServiceProvider] = {}

    def set_llm(self, llm):
        self._llm = llm

    async def generate_from_prompt(self, prompt: str, context: dict = None) -> dict:
        """Ask the LLM to generate SDUI JSON for a given prompt."""
        if not self._llm or not self._llm.available:
            return self._fallback_text(prompt)

        messages = [
            {"role": "system", "content": GENUI_SYSTEM_PROMPT},
            {"role": "user", "content": f"Generate UI for: {prompt}\nContext: {json.dumps(context or {})[:1000]}"},
        ]

        try:
            response = await self._llm.chat(messages, tools=None)
            text, _ = self._llm.extract_response(response)
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            sdui = json.loads(cleaned)
            if "type" in sdui:
                return sdui
        except Exception as e:
            logger.warning(f"GenUI generation failed: {e}")

        return self._fallback_text(prompt)

    async def generate_for_data(self, data: dict, skill_brand: dict = None,
                                ui_hint: str = None, endpoint_id: str = "") -> dict:
        """Generate UI for API response data (deterministic + LLM fallback)."""
        if ui_hint == "map" and ("lat" in data or "latitude" in data):
            return self._build_map(data, skill_brand)

        if ui_hint == "chart" or "chart_data" in data:
            return self._build_chart(data, skill_brand)

        if isinstance(data, dict):
            if "results" in data and isinstance(data["results"], list):
                return self._build_list(data["results"], skill_brand)
            if "image_url" in data or "image_b64" in data:
                return self._build_image(data, skill_brand)

        return self._build_card(data, skill_brand)

    def register_provider(self, provider: "ServiceProvider"):
        """Register a service provider's UI components."""
        self._providers[provider.provider_id] = provider
        logger.info(f"GenUI provider registered: {provider.provider_id} ({len(provider.components)} components)")

    def get_provider_component(self, provider_id: str, component_id: str, data: dict) -> Optional[dict]:
        """Get a rendered component from a service provider."""
        provider = self._providers.get(provider_id)
        if not provider:
            return None
        return provider.render(component_id, data)

    @staticmethod
    def _fallback_text(text: str) -> dict:
        return {
            "type": "VStack", "spacing": 12, "padding": 16,
            "children": [{"type": "Text", "value": str(text)[:500], "style": "body"}],
        }

    @staticmethod
    def _build_map(data: dict, brand: dict = None) -> dict:
        lat = data.get("lat") or data.get("latitude") or 0
        lon = data.get("lon") or data.get("longitude") or 0
        return {
            "type": "VStack", "spacing": 12, "padding": 16,
            "children": [
                {"type": "MapView", "lat": lat, "lon": lon, "zoom": 14,
                 "markers": data.get("markers", []), "height": 250},
                {"type": "Text", "value": data.get("label", f"{lat:.4f}, {lon:.4f}"), "style": "caption"},
            ],
        }

    @staticmethod
    def _build_chart(data: dict, brand: dict = None) -> dict:
        chart_data = data.get("chart_data") or data.get("data") or data.get("values", [])
        return {
            "type": "VStack", "spacing": 12, "padding": 16,
            "children": [
                {"type": "Text", "value": data.get("title", "Chart"), "style": "headline",
                 "color": (brand or {}).get("primary_color", "#6c5ce7")},
                {"type": "Chart", "data": chart_data,
                 "chart_type": data.get("chart_type", "line"),
                 "label": data.get("label", ""), "height": 200},
            ],
        }

    @staticmethod
    def _build_list(items: list, brand: dict = None) -> dict:
        cards = []
        for item in items[:10]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("name") or str(item)[:80]
                desc = item.get("description") or item.get("snippet") or ""
                cards.append({
                    "type": "Card", "corner_radius": 12,
                    "children": [
                        {"type": "Text", "value": title, "style": "subtitle"},
                        *([{"type": "Text", "value": desc[:200], "style": "caption"}] if desc else []),
                    ],
                })
            else:
                cards.append({"type": "Text", "value": str(item)[:200], "style": "body"})
        return {
            "type": "VStack", "spacing": 12, "padding": 16,
            "children": [
                {"type": "Text", "value": f"{len(items)} results", "style": "headline",
                 "color": (brand or {}).get("primary_color", "#6c5ce7")},
                *cards,
            ],
        }

    @staticmethod
    def _build_image(data: dict, brand: dict = None) -> dict:
        url = data.get("image_url") or ""
        if data.get("image_b64"):
            url = f"data:image/jpeg;base64,{data['image_b64']}"
        return {
            "type": "VStack", "spacing": 12, "padding": 16,
            "children": [
                {"type": "Image", "url": url, "corner_radius": 12},
                *([{"type": "Text", "value": data.get("caption", ""), "style": "caption"}]
                  if data.get("caption") else []),
            ],
        }

    @staticmethod
    def _build_card(data: dict, brand: dict = None) -> dict:
        children = []
        for k, v in data.items():
            if k.startswith("_"):
                continue
            children.append({
                "type": "HStack", "spacing": 8,
                "children": [
                    {"type": "Text", "value": k.replace("_", " ").title(), "style": "caption"},
                    {"type": "Text", "value": str(v)[:200], "style": "body"},
                ],
            })
        return {
            "type": "Card", "corner_radius": 12,
            "children": children[:15],
        }


class ServiceProvider:
    """
    External service provider that registers UI components with THEORA.
    This is the "UI as a service" SDK.
    """

    def __init__(
        self,
        provider_id: str,
        name: str,
        description: str = "",
        base_url: str = "",
    ):
        self.provider_id = provider_id
        self.name = name
        self.description = description
        self.base_url = base_url
        self.components: dict[str, dict] = {}
        self._renderers: dict[str, callable] = {}

    def register_component(self, component_id: str, schema: dict, renderer: callable = None):
        """Register a UI component spec with optional custom renderer."""
        self.components[component_id] = schema
        if renderer:
            self._renderers[component_id] = renderer

    def render(self, component_id: str, data: dict) -> Optional[dict]:
        """Render a component with data."""
        renderer = self._renderers.get(component_id)
        if renderer:
            return renderer(data)

        schema = self.components.get(component_id)
        if not schema:
            return None

        template = schema.get("template", {})
        return self._fill_template(template, data)

    @staticmethod
    def _fill_template(template: dict, data: dict) -> dict:
        """Fill a component template with data values."""
        result = {}
        for k, v in template.items():
            if isinstance(v, str) and v.startswith("$"):
                data_key = v[1:]
                result[k] = data.get(data_key, v)
            elif isinstance(v, dict):
                result[k] = ServiceProvider._fill_template(v, data)
            elif isinstance(v, list):
                result[k] = [
                    ServiceProvider._fill_template(item, data) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result


class ServiceProviderRegistry:
    """REST API interface for service provider management."""

    def __init__(self):
        self._providers: dict[str, ServiceProvider] = {}

    def register(self, config: dict) -> ServiceProvider:
        pid = config.get("provider_id", str(uuid4())[:8])
        provider = ServiceProvider(
            provider_id=pid,
            name=config.get("name", "Unknown"),
            description=config.get("description", ""),
            base_url=config.get("base_url", ""),
        )
        for comp in config.get("components", []):
            provider.register_component(
                comp.get("id", ""),
                comp.get("schema", {}),
            )
        self._providers[pid] = provider
        return provider

    def list_providers(self) -> list[dict]:
        return [
            {
                "provider_id": p.provider_id,
                "name": p.name,
                "description": p.description,
                "components": list(p.components.keys()),
            }
            for p in self._providers.values()
        ]

    def get(self, provider_id: str) -> Optional[ServiceProvider]:
        return self._providers.get(provider_id)
