"""
SkillManifest — Programmatic skill manifest builder.

Build skill manifests in Python instead of writing JSON by hand.

Usage::

    manifest = SkillManifest(
        skill_id="my_tool",
        description="Does something cool",
        endpoints=[
            Endpoint(
                id="run",
                description="Run the tool",
                params=[Parameter(name="input", type="string", description="The input")]
            )
        ]
    )
    manifest.save("my_tool.json")
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Parameter:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: str | None = None
    enum: list[str] | None = None


@dataclass
class Endpoint:
    id: str
    description: str = ""
    method: str = "POST"
    url: str = ""
    params: list[Parameter] = field(default_factory=list)
    ui_hint: str = "text"


@dataclass
class Brand:
    name: str = ""
    icon: str = "puzzle"
    color: str = "#6366f1"


@dataclass
class SkillManifest:
    skill_id: str
    description: str = ""
    version: str = "1.0.0"
    brand: Brand = field(default_factory=Brand)
    endpoints: list[Endpoint] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.brand.name:
            self.brand.name = self.skill_id.replace("_", " ").title()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def save(self, path: str | Path):
        Path(path).write_text(self.to_json())
