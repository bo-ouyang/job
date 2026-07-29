"""normalize career profile courses, skills, and change history

Revision ID: 20260728_01
Revises: 20260721_01
Create Date: 2026-07-28 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260728_01"
down_revision: Union[str, Sequence[str], None] = "20260721_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "career_profile_courses",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("level", sa.String(length=30), nullable=True),
        sa.Column("is_core", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["career_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "normalized_name",
            name="uq_career_profile_courses_profile_name",
        ),
    )
    op.create_index(
        "ix_career_profile_courses_profile_id",
        "career_profile_courses",
        ["profile_id"],
    )
    op.create_index(
        "idx_career_profile_courses_profile_status",
        "career_profile_courses",
        ["profile_id", "confirmation_status"],
    )

    op.create_table(
        "career_profile_skills",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("proficiency_level", sa.Integer(), nullable=True),
        sa.Column("years_experience", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "proficiency_level IS NULL OR "
            "(proficiency_level >= 1 AND proficiency_level <= 5)",
            name="ck_career_profile_skills_proficiency",
        ),
        sa.CheckConstraint(
            "years_experience IS NULL OR years_experience >= 0",
            name="ck_career_profile_skills_years",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["career_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "normalized_name",
            name="uq_career_profile_skills_profile_name",
        ),
    )
    op.create_index(
        "ix_career_profile_skills_profile_id",
        "career_profile_skills",
        ["profile_id"],
    )
    op.create_index(
        "idx_career_profile_skills_profile_status",
        "career_profile_skills",
        ["profile_id", "confirmation_status"],
    )

    op.create_table(
        "career_profile_change_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("conflict_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["career_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_career_profile_change_logs_profile_id",
        "career_profile_change_logs",
        ["profile_id"],
    )
    op.create_index(
        "idx_career_profile_change_logs_profile_created",
        "career_profile_change_logs",
        ["profile_id", "created_at"],
    )
    op.create_index(
        "idx_career_profile_change_logs_profile_review",
        "career_profile_change_logs",
        ["profile_id", "review_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_career_profile_change_logs_profile_review",
        table_name="career_profile_change_logs",
    )
    op.drop_index(
        "idx_career_profile_change_logs_profile_created",
        table_name="career_profile_change_logs",
    )
    op.drop_index(
        "ix_career_profile_change_logs_profile_id",
        table_name="career_profile_change_logs",
    )
    op.drop_table("career_profile_change_logs")

    op.drop_index(
        "idx_career_profile_skills_profile_status",
        table_name="career_profile_skills",
    )
    op.drop_index("ix_career_profile_skills_profile_id", table_name="career_profile_skills")
    op.drop_table("career_profile_skills")

    op.drop_index(
        "idx_career_profile_courses_profile_status",
        table_name="career_profile_courses",
    )
    op.drop_index("ix_career_profile_courses_profile_id", table_name="career_profile_courses")
    op.drop_table("career_profile_courses")
