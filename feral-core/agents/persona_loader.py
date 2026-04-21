"""First-party persona + workflow-pack manifest loader.

This is the missing piece Track C fills. The JSON manifests under
``feral-core/agents/personas/*.json`` and ``feral-core/workflows/*.json``
were already being picked up by the registry seed script
(``feral-registry/scripts/seed_first_party.py``) but nothing in the
Brain runtime ever read them, so ``/api/agents/list`` returned only
Mitosis specialists (SQLite) and v2 had no way to browse the 10
curated personas or the 10 curated workflow packs.

This module exposes two loaders. Each validates manifests against a
Pydantic model and returns an in-memory dict keyed by the id so the
routes in ``api/routes/personas.py`` can serve them from ``state``.

Contract: loaders NEVER raise on a single bad manifest. They log the
offender and keep going so one malformed file can't kill the Brain
boot. The loader is permissive about unknown fields so future manifest
extensions don't force a code change here before the JSONs ship.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("feral.personas")


class PersonaManifest(BaseModel):
    """First-party agent persona manifest.

    Lives as JSON under ``feral-core/agents/personas/``. The schema
    mirrors what ``feral-registry/tests/test_seed_personas_workflows.py``
    asserts so the registry seed and the brain runtime never disagree on
    what a persona is.
    """

    model_config = ConfigDict(extra="allow")

    agent_id: str
    name: str
    description: str
    system_prompt: str
    tool_permissions: list[str] = Field(default_factory=list)
    schedule: Optional[str] = None
    memory_filter: Optional[str] = None
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    source_pattern: Optional[str] = None


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str


class WorkflowPackManifest(BaseModel):
    """First-party workflow pack manifest.

    Lives as JSON under ``feral-core/workflows/``. A pack is a *template*;
    instantiating it creates a live TaskFlow via the existing
    ``TaskFlowRuntime.create_flow`` API.
    """

    model_config = ConfigDict(extra="allow")

    workflow_id: str
    name: str
    description: str = ""
    schedule: Optional[str] = None
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    steps: list[WorkflowStep]


def load_personas(directory: Path | str) -> dict[str, PersonaManifest]:
    """Read every ``*.json`` in ``directory`` as a ``PersonaManifest``.

    Malformed files are logged and skipped — one bad persona must not
    kill the Brain boot. Returns a dict keyed by ``agent_id``.
    """
    directory = Path(directory)
    result: dict[str, PersonaManifest] = {}
    if not directory.is_dir():
        logger.info("Persona directory not found: %s (skipping)", directory)
        return result

    for path in sorted(directory.glob("*.json")):
        try:
            data: Any = json.loads(path.read_text())
            manifest = PersonaManifest(**data)
        except Exception as exc:
            logger.warning("Skipping malformed persona %s: %s", path.name, exc)
            continue
        if manifest.agent_id in result:
            logger.warning(
                "Duplicate persona agent_id %r in %s (first-party wins)",
                manifest.agent_id,
                path.name,
            )
            continue
        result[manifest.agent_id] = manifest
    logger.info("Loaded %d first-party personas from %s", len(result), directory)
    return result


def load_workflow_packs(directory: Path | str) -> dict[str, WorkflowPackManifest]:
    """Read every ``*.json`` in ``directory`` as a ``WorkflowPackManifest``."""
    directory = Path(directory)
    result: dict[str, WorkflowPackManifest] = {}
    if not directory.is_dir():
        logger.info("Workflow-pack directory not found: %s (skipping)", directory)
        return result

    for path in sorted(directory.glob("*.json")):
        try:
            data: Any = json.loads(path.read_text())
            manifest = WorkflowPackManifest(**data)
        except Exception as exc:
            logger.warning("Skipping malformed workflow pack %s: %s", path.name, exc)
            continue
        if manifest.workflow_id in result:
            logger.warning(
                "Duplicate workflow_id %r in %s (first-party wins)",
                manifest.workflow_id,
                path.name,
            )
            continue
        result[manifest.workflow_id] = manifest
    logger.info("Loaded %d first-party workflow packs from %s", len(result), directory)
    return result


def default_personas_dir() -> Path:
    """Canonical first-party personas directory."""
    return Path(__file__).resolve().parent / "personas"


def default_workflow_packs_dir() -> Path:
    """Canonical first-party workflow packs directory."""
    return Path(__file__).resolve().parents[1] / "workflows"
