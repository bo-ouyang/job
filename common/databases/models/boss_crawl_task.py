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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from common.databases.models.base import Base
from common.utils.snowflake import generate_id


class BossCrawlTask(Base):
    """A stable BOSS crawl target controlled by the shared crawler control plane."""

    __tablename__ = "boss_crawl_task"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('major', 'city_industry')",
            name="ck_boss_crawl_task_type",
        ),
        CheckConstraint("max_retries >= 0", name="ck_boss_crawl_task_max_retries"),
        UniqueConstraint("source_key", name="uq_boss_crawl_task_source_key"),
        Index("idx_boss_crawl_status_priority_created", "status", "priority", "created_at"),
        Index("idx_boss_crawl_filter_status", "filter_id", "status"),
        Index("idx_boss_crawl_url_hash", "url_hash"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    task_type = Column(String(30), nullable=False, default="city_industry")
    source_key = Column(String(255), nullable=False)
    url = Column(String(2048), nullable=False, index=True, comment="crawl URL")
    url_hash = Column(String(64), nullable=False)
    major_url_id = Column(
        BigInteger,
        ForeignKey("boss_stu_crawl_urls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    major_id = Column(
        BigInteger,
        ForeignKey("majors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    city_code = Column(String(30), nullable=True, index=True)
    industry_code = Column(String(30), nullable=True, index=True)

    filter_id = Column(
        BigInteger,
        ForeignKey("boss_spider_filter.id"),
        nullable=True,
        comment="optional source filter",
    )

    status = Column(String(50), default="pending", index=True)
    priority = Column(Integer, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    pid = Column(Integer, nullable=True)
    spider_name = Column(String(80), nullable=False, default="boss_list_drission")
    spider_args = Column(JSONB, nullable=False, default=dict)
    desired_status = Column(String(20), nullable=False, default="stopped", index=True)
    latest_run_id = Column(
        BigInteger,
        ForeignKey(
            "crawler_runs.id",
            name="fk_boss_crawl_task_latest_run",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )

    last_crawl_time = Column(DateTime, nullable=True)
    error_code = Column(String(50), nullable=True, index=True)
    error_msg = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<BossCrawlTask(id={self.id}, status='{self.status}', url='{self.url}')>"
