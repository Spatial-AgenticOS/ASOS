"""app store gate: item moderation lifecycle + review_events

Revision ID: 0003_app_store_gate
Revises: 0002_extended_kinds
Create Date: 2026-05-03 00:00:00

Adds the moderation lifecycle the registry needs to act as an
acceptance-gated app store:

* ``items.status`` -- submitted | approved | rejected | quarantined
* ``items.visibility`` -- private | public
* ``items.reviewed_by`` / ``items.reviewed_at`` / ``items.review_notes``
* ``review_events`` -- append-only audit trail per item

Backward compatibility / safe backfill:

* New columns are NOT NULL with server defaults of ``submitted`` /
  ``private`` so a freshly migrated database stays internally
  consistent even if no application code has run yet.
* All *existing* rows are then explicitly backfilled to
  ``approved`` / ``public`` via an ``UPDATE`` so the public catalog
  does not silently disappear after deploy. Operators who want to put
  legacy items back into the queue can do so manually after rollout.
* Downgrade drops the new table and columns; existing item rows are
  preserved.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_app_store_gate"
down_revision: Union[str, None] = "0002_extended_kinds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="submitted",
            )
        )
        batch.add_column(
            sa.Column(
                "visibility",
                sa.String(length=16),
                nullable=False,
                server_default="private",
            )
        )
        batch.add_column(sa.Column("reviewed_by", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("review_notes", sa.Text(), nullable=True))

    op.create_index("ix_items_status", "items", ["status"])
    op.create_index("ix_items_visibility", "items", ["visibility"])

    # Pre-existing items predate the gate -- treat them as already
    # approved so a deploy does not pull the public catalog out from
    # under existing users. New rows inserted by the publish handler
    # use the model defaults (submitted/private).
    op.execute(
        sa.text(
            "UPDATE items SET status = 'approved', visibility = 'public' "
            "WHERE status = 'submitted' AND visibility = 'private'"
        )
    )

    op.create_table(
        "review_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "item_id",
            sa.String(length=36),
            sa.ForeignKey("items.id"),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_review_events_item_id", "review_events", ["item_id"])
    op.create_index("ix_review_events_event", "review_events", ["event"])


def downgrade() -> None:
    op.drop_index("ix_review_events_event", table_name="review_events")
    op.drop_index("ix_review_events_item_id", table_name="review_events")
    op.drop_table("review_events")

    op.drop_index("ix_items_visibility", table_name="items")
    op.drop_index("ix_items_status", table_name="items")

    with op.batch_alter_table("items") as batch:
        batch.drop_column("review_notes")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by")
        batch.drop_column("visibility")
        batch.drop_column("status")
