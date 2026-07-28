"""create legacy schema baseline when migrating an empty database

Revision ID: 20260201_00
Revises:
Create Date: 2026-02-01 00:00:00

This baseline is intentionally metadata-driven because the repository did not
have historical create-table migrations. Agent tables are excluded and are
created by the dedicated 20260721_01 revision.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260201_00"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AGENT_TABLES = {
    "agent_conversations",
    "agent_messages",
    "agent_runs",
    "career_profiles",
}


def upgrade() -> None:
    # Import all model modules so CoreBase.metadata is complete.
    import common.databases.models  # noqa: F401
    from common.databases.models.base import Base as CoreBase
    from common.databases.models.city import Base as CityBase
    from common.databases.models.city_hot import Base as CityHotBase

    bind = op.get_bind()
    core_tables = [
        table
        for table in CoreBase.metadata.sorted_tables
        if table.name not in AGENT_TABLES
    ]
    CoreBase.metadata.create_all(bind=bind, tables=core_tables, checkfirst=True)
    CityBase.metadata.create_all(bind=bind, checkfirst=True)
    CityHotBase.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Legacy tables may predate Alembic and can contain production data.
    # Never drop them from the baseline downgrade.
    pass
