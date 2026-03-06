from sqlalchemy import String, Integer, Text, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from common.utils.snowflake import generate_id


class FetchFailure(Base):
    __tablename__ = "fetch_failures"
    __table_args__ = (
        Index("idx_fetch_fail_spider_created", "spider", "created_at"),
        Index("idx_fetch_fail_method_status", "method", "status_code"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id
    )

    spider: Mapped[str] = mapped_column(String(50), index=True)
    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(10))

    status_code: Mapped[int] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text)

    meta: Mapped[str] = mapped_column(Text)

    created_at: Mapped[str] = mapped_column(
        String(19),
        comment="YYYY-MM-DD HH:MM:SS"
    )
