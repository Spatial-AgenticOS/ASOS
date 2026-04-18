"""extend allowed item kinds to the full eight categories

Revision ID: 0002_extended_kinds
Revises: 0001_initial
Create Date: 2026-04-18 00:00:00

The ``items.kind`` column is already ``String(16)`` so no structural
change is required to accept the new values. This migration exists to
*document* the expansion from the original three kinds
(``skill``, ``daemon``, ``mcp``) to the full eight categories the
registry now supports:

    skill | daemon | mcp | channel | provider | memory | workflow | agent

A CHECK constraint would be nice for belt-and-suspenders but we keep it
out because:

1. Sqlite CHECK constraints can't be altered without a full table copy,
   and we want to stay ahead of new kinds we may add later without
   forcing a disruptive migration each time.
2. Validation already happens in the Pydantic ``Manifest`` layer and in
   :func:`feral_registry.schemas.validate_manifest_for_kind` before any
   row reaches the database.
"""
from __future__ import annotations

from typing import Sequence, Union

revision: str = "0002_extended_kinds"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No DDL. The migration is documentation-only; see module docstring
    # for the full list of accepted kinds.
    pass


def downgrade() -> None:
    # Nothing to undo.
    pass
