from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from common.utils.snowflake import generate_id
from .base import Base


class CrawlerWorker(Base):
    """A machine-side Agent capable of running one or more allowlisted spiders."""

    __tablename__ = "crawler_workers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('online', 'offline', 'draining')",
            name="ck_crawler_worker_status",
        ),
        Index("idx_crawler_worker_status_heartbeat", "status", "last_heartbeat_at"),
    )

    id = Column(String(64), primary_key=True)
    name = Column(String(120), nullable=False)
    hostname = Column(String(255), nullable=False)
    platform = Column(String(80), nullable=False, default="unknown")
    status = Column(String(20), nullable=False, default="online", index=True)
    capabilities = Column(JSONB, nullable=False, default=dict)
    max_concurrency = Column(Integer, nullable=False, default=1)
    active_runs = Column(Integer, nullable=False, default=0)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CrawlerRun(Base):
    """One durable execution attempt for a crawler task."""

    __tablename__ = "crawler_runs"
    __table_args__ = (
        CheckConstraint(
            "desired_status IN ('running', 'paused', 'stopped')",
            name="ck_crawler_run_desired_status",
        ),
        CheckConstraint(
            "status IN ('queued', 'starting', 'running', 'pausing', 'paused', "
            "'stopping', 'stopped', 'succeeded', 'failed', 'stale')",
            name="ck_crawler_run_status",
        ),
        Index("idx_crawler_run_task_status", "task_id", "status"),
        Index("idx_crawler_run_worker_status", "worker_id", "status"),
        Index("idx_crawler_run_status_created", "status", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    task_id = Column(
        BigInteger,
        ForeignKey("boss_crawl_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id = Column(
        String(64),
        ForeignKey("crawler_workers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    spider_name = Column(String(80), nullable=False)
    spider_args = Column(JSONB, nullable=False, default=dict)
    desired_status = Column(String(20), nullable=False, default="running", index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    execution_token = Column(String(64), nullable=True, unique=True, index=True)
    pid = Column(Integer, nullable=True)
    metrics = Column(JSONB, nullable=False, default=dict)
    checkpoint = Column(JSONB, nullable=False, default=dict)
    exit_code = Column(Integer, nullable=True)
    error_msg = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True, index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CrawlerEvent(Base):
    """A bounded structured log/progress event emitted by a crawler run."""

    __tablename__ = "crawler_events"
    __table_args__ = (
        CheckConstraint(
            "level IN ('debug', 'info', 'warning', 'error')",
            name="ck_crawler_event_level",
        ),
        Index("idx_crawler_event_run_created", "run_id", "created_at"),
        Index("idx_crawler_event_worker_created", "worker_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    run_id = Column(
        BigInteger,
        ForeignKey("crawler_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id = Column(
        String(64),
        ForeignKey("crawler_workers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(50), nullable=False, index=True)
    level = Column(String(20), nullable=False, default="info")
    message = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
