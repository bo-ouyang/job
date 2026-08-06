from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from common.databases.models.base import Base
from common.utils.snowflake import generate_id


class BossStuCrawlUrl(Base):
    """A discovered BOSS major URL and its stable crawl identity."""

    __tablename__ = "boss_stu_crawl_urls"
    __table_args__ = (
        UniqueConstraint("url_hash", name="uq_boss_stu_crawl_urls_url_hash"),
        Index("idx_boss_stu_major_status", "major_name", "status"),
        Index("idx_boss_stu_status_created", "status", "created_at"),
        Index("idx_boss_stu_major_active", "major_id", "is_active"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    major_id = Column(
        BigInteger,
        ForeignKey("majors.id", ondelete="SET NULL"),
        nullable=True,
    )
    major_code = Column(String(50), nullable=True)
    major_name = Column(String(100), nullable=True, index=True)

    # ``url`` and ``ka`` are retained while callers migrate to the canonical fields.
    url = Column(String(2048), nullable=False, comment="legacy discovered URL")
    ka = Column(String(100), nullable=True)
    raw_url = Column(String(2048), nullable=False)
    canonical_url = Column(String(2048), nullable=False)
    url_hash = Column(String(64), nullable=False)
    position_codes = Column(JSONB, nullable=False, default=list)
    experience_code = Column(String(30), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    first_seen_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_version = Column(String(64), nullable=True)
    parse_error = Column(Text, nullable=True)

    # Legacy crawl-state fields are kept for a non-breaking incremental migration.
    status = Column(String(20), default="pending", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_crawl_time = Column(DateTime(timezone=True), nullable=True)
    error_msg = Column(Text, nullable=True)

    positions = relationship(
        "BossStuUrlPosition",
        back_populates="major_url",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return (
            f"<BossStuCrawlUrl(id={self.id}, major_name={self.major_name!r}, "
            f"canonical_url={self.canonical_url!r})>"
        )


class BossStuUrlPosition(Base):
    """Normalized many-to-many mapping from a major URL to BOSS positions."""

    __tablename__ = "boss_stu_url_position"

    major_url_id = Column(
        BigInteger,
        ForeignKey("boss_stu_crawl_urls.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position_type_id = Column(
        BigInteger,
        ForeignKey("position_type.id", ondelete="CASCADE"),
        primary_key=True,
    )

    major_url = relationship("BossStuCrawlUrl", back_populates="positions")
    position_type = relationship("PositionType")
