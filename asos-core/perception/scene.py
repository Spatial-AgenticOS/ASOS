"""
THEORA Scene Understanding — Vision-Language Model Pipeline
=============================================================
Analyzes camera frames via a VLM (GPT-4o, LLaVA, etc.) to produce
structured scene descriptions that feed into the PerceptionFrame.

Output:
  {
    "scene_description": "User is at a coffee shop, laptop open on table",
    "detected_objects": ["laptop", "coffee cup", "menu board"],
    "text_in_scene": ["WiFi: CafeNet", "Today's Special: Latte $4.50"],
    "people_count": 3,
    "ambient": "indoor_crowded"
  }
"""

from __future__ import annotations
import base64
import json
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.llm_provider import LLMProvider

logger = logging.getLogger("theora.scene")

SCENE_ANALYSIS_PROMPT = """You are the vision system of a wearable AI operating system (smart glasses).
Analyze this camera frame and return a JSON object with these fields:
- "scene_description": one sentence describing the scene and user's likely activity
- "detected_objects": array of up to 10 notable objects visible
- "text_in_scene": array of any readable text (signs, screens, labels)
- "people_count": integer count of people visible
- "ambient": one of "indoor_quiet", "indoor_crowded", "outdoor_urban", "outdoor_nature", "vehicle", "workspace", "unknown"

Return ONLY valid JSON. No markdown, no explanation."""


class SceneAnalyzer:
    """
    Periodically analyzes vision frames through a VLM to produce
    structured scene understanding for the PerceptionFrame.
    """

    def __init__(self, llm: "LLMProvider" = None):
        self._llm = llm
        self._last_analysis: dict[str, float] = {}  # node_id → timestamp
        self._cooldown = 10.0  # seconds between analyses per node
        self._cache: dict[str, dict] = {}  # node_id → last analysis result

    @property
    def available(self) -> bool:
        return self._llm is not None and self._llm.available

    async def analyze_frame(
        self,
        data_b64: str,
        encoding: str = "jpeg",
        node_id: str = "default",
        force: bool = False,
    ) -> Optional[dict]:
        """
        Analyze a base64-encoded frame via VLM.
        Returns structured scene dict or None if skipped/failed.
        """
        if not self.available:
            return None

        now = time.time()
        last = self._last_analysis.get(node_id, 0)
        if not force and (now - last) < self._cooldown:
            return self._cache.get(node_id)

        self._last_analysis[node_id] = now

        mime = f"image/{encoding}"
        data_url = f"data:{mime};base64,{data_b64}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SCENE_ANALYSIS_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "low"}},
                ],
            }
        ]

        try:
            response = await self._llm.chat(
                messages=messages,
                tools=None,
                temperature=0.1,
                max_tokens=400,
            )
            text_content, _ = self._llm.extract_response(response)
            if not text_content:
                return None

            cleaned = text_content.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:-3].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:-3].strip()

            result = json.loads(cleaned)
            self._cache[node_id] = result
            logger.info(f"Scene analysis [{node_id}]: {result.get('scene_description', '?')[:60]}")
            return result

        except json.JSONDecodeError:
            logger.debug("VLM returned non-JSON scene description")
            return None
        except Exception as e:
            logger.warning(f"Scene analysis failed: {e}")
            return None

    def get_cached(self, node_id: str = "default") -> Optional[dict]:
        return self._cache.get(node_id)

    def set_cooldown(self, seconds: float):
        self._cooldown = max(1.0, seconds)
