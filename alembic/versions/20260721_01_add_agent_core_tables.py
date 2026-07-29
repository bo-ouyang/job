"""add Agent conversation, run, message, and career profile tables

Revision ID: 20260721_01
Revises: 20260306_01
Create Date: 2026-07-21 10:50:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260721_01"
down_revision: Union[str, Sequence[str], None] = "20260306_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_users_id_primary_key() -> None:
    """Normalize legacy databases created without ORM constraints."""
    bind = op.get_bind()
    primary_key = sa.inspect(bind).get_pk_constraint("users")
    constrained_columns = primary_key.get("constrained_columns") or []
    if constrained_columns == ["id"]:
        return
    if constrained_columns:
        raise RuntimeError(
            "users has an unexpected primary key; expected users.id before Agent migration"
        )

    row_count, nonnull_id_count, distinct_id_count = bind.execute(
        sa.text(
            "SELECT COUNT(*), COUNT(id), COUNT(DISTINCT id) "
            "FROM users"
        )
    ).one()
    if row_count != nonnull_id_count or row_count != distinct_id_count:
        raise RuntimeError(
            "cannot add users.id primary key: legacy data contains null or duplicate ids"
        )

    op.create_primary_key("pk_users", "users", ["id"])


def upgrade() -> None:
    _ensure_users_id_primary_key()

    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_conversations_user_id", "agent_conversations", ["user_id"])
    op.create_index("ix_agent_conversations_status", "agent_conversations", ["status"])
    op.create_index(
        "idx_agent_conv_user_status_updated",
        "agent_conversations",
        ["user_id", "status", "updated_at"],
    )
    op.create_index(
        "idx_agent_conv_user_created",
        "agent_conversations",
        ["user_id", "created_at"],
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("message_type", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "conversation_id",
            "idempotency_key",
            name="uq_agent_message_user_conversation_idempotency",
        ),
    )
    op.create_index("ix_agent_messages_conversation_id", "agent_messages", ["conversation_id"])
    op.create_index("ix_agent_messages_user_id", "agent_messages", ["user_id"])
    op.create_index(
        "idx_agent_msg_conversation_created",
        "agent_messages",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index("idx_agent_msg_user_created", "agent_messages", ["user_id", "created_at"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("input_message_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("execution_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("current_node", sa.String(length=80), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("state_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("status_updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["input_message_id"], ["agent_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "conversation_id",
            "idempotency_key",
            name="uq_agent_run_user_conversation_idempotency",
        ),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_input_message_id", "agent_runs", ["input_message_id"])
    op.create_index("ix_agent_runs_execution_token", "agent_runs", ["execution_token"])
    op.create_index("ix_agent_runs_status_updated_at", "agent_runs", ["status_updated_at"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("idx_agent_run_user_status", "agent_runs", ["user_id", "status"])
    op.create_index(
        "idx_agent_run_conversation_status",
        "agent_runs",
        ["conversation_id", "status"],
    )
    op.create_index(
        "idx_agent_run_conversation_created",
        "agent_runs",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "career_profiles",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("education", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("skills", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("experience", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("goals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_career_profiles_user_id"),
    )
    op.create_index("ix_career_profiles_user_id", "career_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_career_profiles_user_id", table_name="career_profiles")
    op.drop_table("career_profiles")

    op.drop_index("idx_agent_run_conversation_created", table_name="agent_runs")
    op.drop_index("idx_agent_run_conversation_status", table_name="agent_runs")
    op.drop_index("idx_agent_run_user_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_input_message_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_execution_token", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status_updated_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("idx_agent_msg_user_created", table_name="agent_messages")
    op.drop_index("idx_agent_msg_conversation_created", table_name="agent_messages")
    op.drop_index("ix_agent_messages_user_id", table_name="agent_messages")
    op.drop_index("ix_agent_messages_conversation_id", table_name="agent_messages")
    op.drop_table("agent_messages")

    op.drop_index("idx_agent_conv_user_created", table_name="agent_conversations")
    op.drop_index("idx_agent_conv_user_status_updated", table_name="agent_conversations")
    op.drop_index("ix_agent_conversations_status", table_name="agent_conversations")
    op.drop_index("ix_agent_conversations_user_id", table_name="agent_conversations")
    op.drop_table("agent_conversations")
