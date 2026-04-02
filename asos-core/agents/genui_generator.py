"""
THEORA GenUI Generator — Turns Data Into Interfaces
=====================================================
Three strategies, tried in priority order:
1. Template match — skill manifest has UI templates → fill with data
2. Structural rules — map data shape to primitives deterministically
3. LLM generation — ask the LLM to generate SDUI JSON (validated)
"""

from __future__ import annotations
import json
import logging
from typing import Optional

logger = logging.getLogger("theora.genui")


class GenUIGenerator:
    """
    Generates SDUI JSON from API response data + skill metadata.
    This is what replaces app development.
    """

    def generate(
        self,
        data: dict,
        skill_brand: dict,
        ui_hint: Optional[str] = None,
        endpoint_id: str = "",
    ) -> dict:
        """
        Generate an SDUI layout from API response data.
        
        Args:
            data: The raw API response data
            skill_brand: Brand profile (name, primary_color, logo_url)
            ui_hint: Optional hint from skill manifest ("grid_cards", "metric", etc.)
            endpoint_id: The endpoint that produced this data
        
        Returns:
            SDUI JSON tree
        """
        brand_name = skill_brand.get("name", "Skill")
        brand_color = skill_brand.get("primary_color", "#6c5ce7")

        # Strategy 1: Use ui_hint if available
        if ui_hint:
            result = self._from_hint(data, ui_hint, brand_name, brand_color)
            if result:
                return self._wrap_with_header(result, brand_name, brand_color)

        # Strategy 2: Structural rules based on data shape
        result = self._from_data_shape(data, brand_name, brand_color)
        return self._wrap_with_header(result, brand_name, brand_color)

    def _wrap_with_header(self, content: dict, brand_name: str, brand_color: str) -> dict:
        """Wrap content with a branded header."""
        return {
            "type": "VStack",
            "spacing": 16,
            "padding": 20,
            "children": [
                {
                    "type": "HStack",
                    "spacing": 10,
                    "children": [
                        {"type": "Icon", "name": "sparkles", "size": 22, "color": brand_color},
                        {"type": "Text", "value": brand_name, "style": "headline", "color": brand_color},
                    ],
                },
                {"type": "Divider"},
                content,
            ],
        }

    def _from_hint(self, data: dict, hint: str, brand_name: str, color: str) -> Optional[dict]:
        """Generate SDUI based on the skill's ui_hint."""

        if hint == "metric" and isinstance(data, dict):
            return self._render_metrics(data, color)

        elif hint == "list" and isinstance(data, (list, dict)):
            items = data if isinstance(data, list) else data.get("list", data.get("items", [data]))
            return self._render_list(items, color)

        elif hint == "grid_cards" and isinstance(data, (list, dict)):
            items = data if isinstance(data, list) else data.get("list", data.get("items", [data]))
            return self._render_grid(items, color)

        elif hint == "map" and isinstance(data, dict):
            lat = data.get("lat", data.get("coord", {}).get("lat", 37.33))
            lon = data.get("lon", data.get("coord", {}).get("lon", -122.03))
            return {"type": "MapView", "center_lat": lat, "center_lon": lon, "zoom": 14, "height": 250}

        elif hint == "detail_card":
            return self._render_detail_card(data, color)

        return None

    def _from_data_shape(self, data: dict, brand_name: str, color: str) -> dict:
        """Infer the best layout from the shape of the data."""

        # If it's a list of items → render as scrollable cards
        if isinstance(data, list):
            if len(data) > 6:
                return self._render_list(data[:20], color)
            else:
                return self._render_grid(data, color)

        # If it's a dict with a nested array → find the array and render it
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0:
                    return {
                        "type": "VStack",
                        "spacing": 12,
                        "children": [
                            {"type": "Text", "value": key.replace("_", " ").title(), "style": "subtitle"},
                            self._render_list(value[:20], color),
                        ],
                    }

            # It's a flat dict → render as key-value metrics
            return self._render_metrics(data, color)

        # Fallback: just show the data as text
        return {"type": "Text", "value": str(data)[:500], "style": "body"}

    def _render_metrics(self, data: dict, color: str) -> dict:
        """Render a dict as metric cards."""
        # Pick numeric values as metrics, strings as text
        metrics = []
        texts = []

        for key, value in data.items():
            if key.startswith("_") or key in ("cod", "id", "base", "timezone", "visibility"):
                continue  # Skip internal fields

            if isinstance(value, (int, float)):
                metrics.append(self._make_metric(key, value, color))
            elif isinstance(value, str) and len(value) < 100:
                texts.append({
                    "type": "HStack",
                    "spacing": 8,
                    "children": [
                        {"type": "Text", "value": key.replace("_", " ").title() + ":", "style": "caption"},
                        {"type": "Text", "value": str(value), "style": "body"},
                    ],
                })
            elif isinstance(value, dict):
                # Nested dict — flatten one level
                for k2, v2 in value.items():
                    if isinstance(v2, (int, float)):
                        metrics.append(self._make_metric(f"{key} {k2}", v2, color))

        children = []
        if metrics:
            # Arrange metrics in a grid
            children.append({"type": "Grid", "columns": 2, "spacing": 12, "children": metrics[:8]})
        if texts:
            children.extend(texts[:10])

        return {"type": "VStack", "spacing": 12, "children": children} if children else {"type": "Text", "value": json.dumps(data, indent=2)[:500], "style": "body"}

    def _render_list(self, items: list, color: str) -> dict:
        """Render a list of items as cards in a ScrollView."""
        cards = []
        for item in items[:20]:
            if isinstance(item, dict):
                cards.append(self._dict_to_card(item, color))
            else:
                cards.append({"type": "Text", "value": str(item), "style": "body"})

        return {"type": "ScrollView", "children": cards}

    def _render_grid(self, items: list, color: str) -> dict:
        """Render items in a 2-column grid."""
        cards = []
        for item in items[:12]:
            if isinstance(item, dict):
                cards.append(self._dict_to_card(item, color))
            else:
                cards.append({"type": "Text", "value": str(item), "style": "body"})

        return {"type": "Grid", "columns": 2, "spacing": 12, "children": cards}

    def _render_detail_card(self, data: dict, color: str) -> dict:
        """Render a single item as a detailed card."""
        return self._dict_to_card(data, color)

    def _dict_to_card(self, d: dict, color: str) -> dict:
        """Convert a dict to a Card with key-value rows."""
        children = []

        # Look for a title field
        for title_key in ("name", "title", "label", "display_name", "restaurant_name"):
            if title_key in d:
                children.append({"type": "Text", "value": str(d[title_key]), "style": "subtitle"})
                break

        # Look for a description
        for desc_key in ("description", "summary", "weather_description", "conditions"):
            if desc_key in d:
                children.append({"type": "Text", "value": str(d[desc_key]), "style": "caption"})
                break

        # Look for an image
        for img_key in ("image_url", "icon_url", "thumbnail", "photo"):
            if img_key in d and d[img_key]:
                children.append({"type": "AsyncImage", "url": str(d[img_key]), "height": 120, "corner_radius": 8})
                break

        # Add numeric values as badges/metrics
        for key, value in d.items():
            if key.startswith("_"):
                continue
            if isinstance(value, (int, float)) and key not in ("id", "cod", "timezone"):
                children.append({
                    "type": "HStack",
                    "spacing": 8,
                    "children": [
                        {"type": "Text", "value": key.replace("_", " ").title(), "style": "caption"},
                        {"type": "Badge", "label": str(value), "color": color},
                    ],
                })

        return {"type": "Card", "corner_radius": 12, "children": children}

    def _make_metric(self, key: str, value, color: str) -> dict:
        """Create a MetricCard from a key-value pair."""
        label = key.replace("_", " ").title()

        # Guess the icon and unit
        icon = "chart.bar.fill"
        unit = ""
        if "temp" in key.lower():
            icon = "thermometer"
            unit = "°F"
        elif "humidity" in key.lower():
            icon = "drop.fill"
            unit = "%"
        elif "wind" in key.lower() or "speed" in key.lower():
            icon = "wind"
            unit = "mph"
        elif "pressure" in key.lower():
            icon = "gauge"
            unit = "hPa"
        elif "heart" in key.lower() or "hr" in key.lower():
            icon = "heart.fill"
            unit = "bpm"

        return {
            "type": "MetricCard",
            "icon": icon,
            "value": str(round(value, 1) if isinstance(value, float) else value),
            "unit": unit,
            "label": label,
            "color": color,
        }
