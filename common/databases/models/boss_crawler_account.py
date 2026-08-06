from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from common.databases.models.base import Base
from common.utils.snowflake import generate_id


class BossCrawlerAccount(Base):
    """BOSS account metadata; credentials remain in an external secret store."""

    __tablename__ = "boss_crawler_account"
    __table_args__ = (
        CheckConstraint(
            "status IN ('available', 'in_use', 'cooldown', 'disabled')",
            name="ck_boss_crawler_account_status",
        ),
        UniqueConstraint(
            "profile_ref", name="uq_boss_crawler_account_profile_ref"
        ),
        UniqueConstraint("secret_ref", name="uq_boss_crawler_account_secret_ref"),
        UniqueConstraint("name", name="uq_boss_crawler_account_name"),
        Index(
            "idx_boss_crawler_account_status_cooldown",
            "status",
            "cooldown_until",
        ),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    name = Column(String(120), nullable=False)
    profile_ref = Column(String(255), nullable=False)
    secret_ref = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="available", index=True)
    cooldown_until = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
