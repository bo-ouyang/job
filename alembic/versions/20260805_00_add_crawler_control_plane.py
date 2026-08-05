"""add crawler control plane

Revision ID: 20260805_00
Revises: 20260728_02
Create Date: 2026-08-05 14:20:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260805_00"
down_revision: Union[str, Sequence[str], None] = "20260728_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_boss_crawl_task_id_key() -> None:
    """Repair legacy installations whose task table was created without a key."""
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                id_attribute smallint;
            BEGIN
                SELECT attnum
                  INTO id_attribute
                  FROM pg_attribute
                 WHERE attrelid = 'boss_crawl_task'::regclass
                   AND attname = 'id'
                   AND NOT attisdropped;

                IF NOT EXISTS (
                    SELECT 1
                      FROM pg_constraint
                     WHERE conrelid = 'boss_crawl_task'::regclass
                       AND contype IN ('p', 'u')
                       AND conkey = ARRAY[id_attribute]::smallint[]
                ) THEN
                    IF EXISTS (SELECT 1 FROM boss_crawl_task WHERE id IS NULL)
                       OR EXISTS (
                            SELECT 1
                              FROM boss_crawl_task
                             GROUP BY id HAVING count(*) > 1
                       ) THEN
                        RAISE EXCEPTION
                            'boss_crawl_task.id must be non-null and unique before crawler control migration';
                    END IF;

                    ALTER TABLE boss_crawl_task
                        ADD CONSTRAINT pk_boss_crawl_task_control_plane PRIMARY KEY (id);
                END IF;
            END
            $$;
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "crawler_workers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="offline"),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('online', 'offline', 'draining')", name="ck_crawler_worker_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_crawler_worker_status_heartbeat", "crawler_workers", ["status", "last_heartbeat_at"])
    op.create_index(op.f("ix_crawler_workers_status"), "crawler_workers", ["status"])

    op.add_column(
        "boss_crawl_task",
        sa.Column("spider_name", sa.String(length=80), nullable=False, server_default="boss_list_drission"),
    )
    op.add_column(
        "boss_crawl_task",
        sa.Column("spider_args", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "boss_crawl_task",
        sa.Column("desired_status", sa.String(length=20), nullable=False, server_default="stopped"),
    )
    op.add_column("boss_crawl_task", sa.Column("latest_run_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_boss_crawl_task_desired_status"), "boss_crawl_task", ["desired_status"])
    op.create_index(op.f("ix_boss_crawl_task_latest_run_id"), "boss_crawl_task", ["latest_run_id"])

    _ensure_boss_crawl_task_id_key()

    op.create_table(
        "crawler_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("spider_name", sa.String(length=80), nullable=False),
        sa.Column("spider_args", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("desired_status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("execution_token", sa.String(length=64), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("desired_status IN ('running', 'paused', 'stopped')", name="ck_crawler_run_desired_status"),
        sa.CheckConstraint(
            "status IN ('queued', 'starting', 'running', 'pausing', 'paused', 'stopping', 'stopped', 'succeeded', 'failed', 'stale')",
            name="ck_crawler_run_status",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["boss_crawl_task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["crawler_workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_crawler_run_status_created", "crawler_runs", ["status", "created_at"])
    op.create_index("idx_crawler_run_task_status", "crawler_runs", ["task_id", "status"])
    op.create_index("idx_crawler_run_worker_status", "crawler_runs", ["worker_id", "status"])
    op.create_index(op.f("ix_crawler_runs_desired_status"), "crawler_runs", ["desired_status"])
    op.create_index(op.f("ix_crawler_runs_execution_token"), "crawler_runs", ["execution_token"], unique=True)
    op.create_index(op.f("ix_crawler_runs_heartbeat_at"), "crawler_runs", ["heartbeat_at"])
    op.create_index(op.f("ix_crawler_runs_status"), "crawler_runs", ["status"])
    op.create_index(op.f("ix_crawler_runs_task_id"), "crawler_runs", ["task_id"])
    op.create_index(op.f("ix_crawler_runs_worker_id"), "crawler_runs", ["worker_id"])
    op.create_foreign_key(
        "fk_boss_crawl_task_latest_run",
        "boss_crawl_task",
        "crawler_runs",
        ["latest_run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "crawler_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("level IN ('debug', 'info', 'warning', 'error')", name="ck_crawler_event_level"),
        sa.ForeignKeyConstraint(["run_id"], ["crawler_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["crawler_workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_crawler_event_run_created", "crawler_events", ["run_id", "created_at"])
    op.create_index("idx_crawler_event_worker_created", "crawler_events", ["worker_id", "created_at"])
    op.create_index(op.f("ix_crawler_events_event_type"), "crawler_events", ["event_type"])
    op.create_index(op.f("ix_crawler_events_run_id"), "crawler_events", ["run_id"])
    op.create_index(op.f("ix_crawler_events_worker_id"), "crawler_events", ["worker_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_crawler_events_worker_id"), table_name="crawler_events")
    op.drop_index(op.f("ix_crawler_events_run_id"), table_name="crawler_events")
    op.drop_index(op.f("ix_crawler_events_event_type"), table_name="crawler_events")
    op.drop_index("idx_crawler_event_worker_created", table_name="crawler_events")
    op.drop_index("idx_crawler_event_run_created", table_name="crawler_events")
    op.drop_table("crawler_events")
    op.drop_constraint("fk_boss_crawl_task_latest_run", "boss_crawl_task", type_="foreignkey")
    op.drop_index(op.f("ix_crawler_runs_worker_id"), table_name="crawler_runs")
    op.drop_index(op.f("ix_crawler_runs_task_id"), table_name="crawler_runs")
    op.drop_index(op.f("ix_crawler_runs_status"), table_name="crawler_runs")
    op.drop_index(op.f("ix_crawler_runs_heartbeat_at"), table_name="crawler_runs")
    op.drop_index(op.f("ix_crawler_runs_execution_token"), table_name="crawler_runs")
    op.drop_index(op.f("ix_crawler_runs_desired_status"), table_name="crawler_runs")
    op.drop_index("idx_crawler_run_worker_status", table_name="crawler_runs")
    op.drop_index("idx_crawler_run_task_status", table_name="crawler_runs")
    op.drop_index("idx_crawler_run_status_created", table_name="crawler_runs")
    op.drop_table("crawler_runs")
    op.drop_index(op.f("ix_boss_crawl_task_latest_run_id"), table_name="boss_crawl_task")
    op.drop_index(op.f("ix_boss_crawl_task_desired_status"), table_name="boss_crawl_task")
    op.drop_column("boss_crawl_task", "latest_run_id")
    op.drop_column("boss_crawl_task", "desired_status")
    op.drop_column("boss_crawl_task", "spider_args")
    op.drop_column("boss_crawl_task", "spider_name")
    op.execute(
        sa.text(
            """
            ALTER TABLE boss_crawl_task
                DROP CONSTRAINT IF EXISTS pk_boss_crawl_task_control_plane;
            """
        )
    )
    op.drop_index(op.f("ix_crawler_workers_status"), table_name="crawler_workers")
    op.drop_index("idx_crawler_worker_status_heartbeat", table_name="crawler_workers")
    op.drop_table("crawler_workers")
