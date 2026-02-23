from sqlalchemy import String, Integer, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
from common.utils.snowflake import generate_id


class FetchFailure(Base):
    __tablename__ = "fetch_failures"

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
