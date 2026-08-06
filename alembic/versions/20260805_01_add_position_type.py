"""add Boss position taxonomy table

Revision ID: 20260805_01
Revises: 20260805_00
Create Date: 2026-08-05 21:20:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260805_01"
down_revision: Union[str, Sequence[str], None] = "20260805_00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "position_type",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_code", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_leaf", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tip", sa.Text(), nullable=True),
        sa.Column("first_char", sa.String(length=8), nullable=True),
        sa.Column("pinyin", sa.String(length=200), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mark", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_position_type", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("city_type", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capital", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("color", sa.String(length=50), nullable=True),
        sa.Column("recruitment_type", sa.String(length=50), nullable=True),
        sa.Column("city_code", sa.String(length=30), nullable=True),
        sa.Column("region_code", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("center_geo", postgresql.JSONB(), nullable=True),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column(
            "source_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["position_type.id"],
            name="fk_position_type_parent",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_position_type_path"),
        if_not_exists=True,
    )
    op.create_index(
        "idx_position_type_parent_order",
        "position_type",
        ["parent_id", "sort_order"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_position_type_code_level",
        "position_type",
        ["code", "level"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_position_type_name",
        "position_type",
        ["name"],
        if_not_exists=True,
    )


def downgrade() -> None:
    """Intentionally preserve taxonomy data on downgrade.

    This revision adopted a ``position_type`` table that could already have
    been populated by the standalone taxonomy importer. Alembic cannot prove
    that it owns that table or its data, so dropping it (or its possibly
    pre-existing indexes) would be destructive. A downgrade only moves the
    revision marker; operators may remove an empty, migration-owned table
    manually after verifying ownership.
    """

    return None
