from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from common.utils.snowflake import generate_id
from .base import Base


class CareerProfile(Base):
    """Long-lived, user-confirmed career profile data."""

    __tablename__ = "career_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_career_profiles_user_id"),)

    id = Column(BigInteger, primary_key=True, default=generate_id)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    education = Column(JSONB, nullable=True)
    skills = Column(JSONB, nullable=True)
    experience = Column(JSONB, nullable=True)
    preferences = Column(JSONB, nullable=True)
    constraints = Column(JSONB, nullable=True)
    goals = Column(JSONB, nullable=True)
    confidence = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
