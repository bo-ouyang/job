"""add structured and idempotent message-center notifications

Revision ID: 20260807_00
Revises: 20260806_00
Create Date: 2026-08-07 14:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260807_00"
down_revision: Union[str, Sequence[str], None] = "20260806_00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OWNERSHIP_MARKER = "managed_by_alembic:20260807_00"
STRUCTURED_COLUMNS = (
    ("category", "VARCHAR(30)"),
    ("status", "VARCHAR(30)"),
    ("action_type", "VARCHAR(30)"),
    ("action_data", "JSONB"),
    ("source_type", "VARCHAR(50)"),
    ("source_id", "VARCHAR(128)"),
    ("dedupe_key", "VARCHAR(180)"),
)


def _add_column_if_missing(name: str, column_type: str) -> str:
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'messages'
              AND column_name = '{name}'
        ) THEN
            ALTER TABLE messages ADD COLUMN {name} {column_type};
            COMMENT ON COLUMN messages.{name} IS '{OWNERSHIP_MARKER}';
        END IF;
    END $$
    """


def upgrade() -> None:
    # ``20260201_00`` can create a metadata-derived baseline in a new
    # environment.  The notification fields may therefore already exist when
    # this incremental revision is applied.  PostgreSQL's idempotent DDL keeps
    # both fresh and upgraded databases on the same schema.
    for name, column_type in STRUCTURED_COLUMNS:
        op.execute(_add_column_if_missing(name, column_type))
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_index AS index_definition
                JOIN pg_attribute AS indexed_column
                  ON indexed_column.attrelid = index_definition.indrelid
                 AND indexed_column.attnum = index_definition.indkey[0]
                WHERE index_definition.indrelid = 'messages'::regclass
                  AND index_definition.indisunique
                  AND index_definition.indnkeyatts = 1
                  AND indexed_column.attname = 'dedupe_key'
            ) THEN
                ALTER TABLE messages
                ADD CONSTRAINT uq_messages_dedupe_key UNIQUE (dedupe_key);
                COMMENT ON CONSTRAINT uq_messages_dedupe_key ON messages
                IS '{OWNERSHIP_MARKER}';
            END IF;
        END $$
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass(current_schema() || '.idx_messages_receiver_category_created') IS NULL THEN
                CREATE INDEX idx_messages_receiver_category_created
                ON messages (receiver_id, category, created_at);
                COMMENT ON INDEX idx_messages_receiver_category_created
                IS '{OWNERSHIP_MARKER}';
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    # A metadata-derived baseline can predate this revision while already
    # having equivalent fields/unique indexes.  Only drop objects carrying our
    # explicit ownership marker, never a baseline-owned anonymous object.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_class
                WHERE relkind = 'i'
                  AND relname = 'idx_messages_receiver_category_created'
                  AND obj_description(oid, 'pg_class') = '{OWNERSHIP_MARKER}'
            ) THEN
                DROP INDEX idx_messages_receiver_category_created;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'messages'::regclass
                  AND conname = 'uq_messages_dedupe_key'
                  AND obj_description(oid, 'pg_constraint') = '{OWNERSHIP_MARKER}'
            ) THEN
                ALTER TABLE messages DROP CONSTRAINT uq_messages_dedupe_key;
            END IF;
        END $$
        """
    )
    for name, _column_type in reversed(STRUCTURED_COLUMNS):
        op.execute(
            f"""
            DO $$
            DECLARE column_number smallint;
            BEGIN
                SELECT attnum INTO column_number
                FROM pg_attribute
                WHERE attrelid = 'messages'::regclass
                  AND attname = '{name}'
                  AND NOT attisdropped;
                IF column_number IS NOT NULL
                   AND col_description('messages'::regclass, column_number) = '{OWNERSHIP_MARKER}' THEN
                    ALTER TABLE messages DROP COLUMN {name};
                END IF;
            END $$
            """
        )
