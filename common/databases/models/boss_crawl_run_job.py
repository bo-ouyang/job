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
    UniqueConstraint,
)
from sqlalchemy.sql import func

from common.databases.models.base import Base
from common.utils.snowflake import generate_id


class BossCrawlRunJob(Base):
    """Per-run BOSS job discovery, detail status, and resumable card position."""

    __tablename__ = "boss_crawl_run_job"
    __table_args__ = (
        CheckConstraint(
            "detail_status IN ('pending', 'processing', 'done', 'error')",
            name="ck_boss_crawl_run_job_detail_status",
        ),
        CheckConstraint(
            "detail_attempts >= 0",
            name="ck_boss_crawl_run_job_detail_attempts",
        ),
        UniqueConstraint(
            "run_id",
            "encrypt_job_id",
            name="uq_boss_crawl_run_job_run_encrypt_job",
        ),
        Index("idx_boss_crawl_run_job_run_status", "run_id", "detail_status"),
        Index("idx_boss_crawl_run_job_task_status", "task_id", "detail_status"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    run_id = Column(
        BigInteger,
        ForeignKey("crawler_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        BigInteger,
        ForeignKey("boss_crawl_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    encrypt_job_id = Column(String(100), nullable=False, index=True)
    job_id = Column(
        BigInteger,
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    list_page = Column(Integer, nullable=False, default=1)
    scroll_round = Column(Integer, nullable=False, default=0)
    card_index = Column(Integer, nullable=False, default=0)
    detail_status = Column(
        String(20), nullable=False, default="pending", index=True
    )
    detail_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    first_seen_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    detail_completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
