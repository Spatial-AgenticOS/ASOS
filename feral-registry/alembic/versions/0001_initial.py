"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-17 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publishers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("github_login", sa.String(length=100), nullable=False, unique=True),
        sa.Column("github_id", sa.Integer(), nullable=False),
        sa.Column("pubkey_hex", sa.String(length=64), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_publishers_github_login", "publishers", ["github_login"], unique=True)

    op.create_table(
        "items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column(
            "author_id",
            sa.String(length=36),
            sa.ForeignKey("publishers.id"),
            nullable=False,
        ),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("blob_path", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("signature_b64", sa.Text(), nullable=False),
        sa.Column("downloads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "name", "version", name="uq_items_kind_name_version"),
    )
    op.create_index("ix_items_kind", "items", ["kind"])
    op.create_index("ix_items_name", "items", ["name"])
    op.create_index("ix_items_sha256", "items", ["sha256"])
    op.create_index("ix_items_author_id", "items", ["author_id"])

    op.create_table(
        "flags",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "item_id",
            sa.String(length=36),
            sa.ForeignKey("items.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_flags_item_id", "flags", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_flags_item_id", table_name="flags")
    op.drop_table("flags")
    op.drop_index("ix_items_author_id", table_name="items")
    op.drop_index("ix_items_sha256", table_name="items")
    op.drop_index("ix_items_name", table_name="items")
    op.drop_index("ix_items_kind", table_name="items")
    op.drop_table("items")
    op.drop_index("ix_publishers_github_login", table_name="publishers")
    op.drop_table("publishers")
