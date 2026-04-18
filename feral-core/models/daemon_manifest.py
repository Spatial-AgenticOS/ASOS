"""
FERAL Daemon Manifest
=====================
Defines the minimum metadata a publishable daemon bundle must declare.

Daemons are long-running local processes (e.g. hardware bridges, sync
workers, platform integrations) that the Brain may spawn on behalf of
the user. This manifest is the counterpart to ``SkillManifest`` for
daemon packages pushed through the FERAL registry.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DaemonManifest(BaseModel):
    """Minimal schema for a daemon package manifest.

    The publish/install flow only validates the fields listed in the task
    spec (``id``, ``name``, ``version``, ``capabilities``, ``entrypoint``).
    Additional fields are preserved but optional so registry payloads can
    evolve without breaking older CLIs.
    """

    id: str = Field(..., description="Stable daemon identifier (e.g. 'wristband-bridge').")
    name: str = Field(..., description="Human-readable display name.")
    version: str = Field(..., description="Semver version string, e.g. '1.2.0'.")
    capabilities: list[str] = Field(
        default_factory=list,
        description="Capability tags the daemon exposes (e.g. ['bluetooth', 'healthkit']).",
    )
    entrypoint: str = Field(
        ...,
        description="Command or script to launch the daemon relative to the bundle root.",
    )

    description: Optional[str] = None
    author: Optional[str] = None
    node_type: Optional[str] = None
    requires: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
