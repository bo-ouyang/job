"""add idempotent Agent run billing fields

Revision ID: 20260728_02
Revises: 20260728_01
Create Date: 2026-07-28 16:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260728_02"
down_revision: Union[str, Sequence[str], None] = "20260728_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("billing_feature_key", sa.String(length=50), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("charge_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
    )
    op.add_column("agent_runs", sa.Column("charged_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "charged_at")
    op.drop_column("agent_runs", "charge_amount")
    op.drop_column("agent_runs", "billing_feature_key")
