from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
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

    courses = relationship(
        "CareerProfileCourse",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    normalized_skills = relationship(
        "CareerProfileSkill",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    change_logs = relationship(
        "CareerProfileChangeLog",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class CareerProfileCourse(Base):
    """A course that can be edited, deduplicated, and reviewed independently."""

    __tablename__ = "career_profile_courses"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "normalized_name",
            name="uq_career_profile_courses_profile_name",
        ),
        Index(
            "idx_career_profile_courses_profile_status",
            "profile_id",
            "confirmation_status",
        ),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    profile_id = Column(
        BigInteger,
        ForeignKey("career_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    normalized_name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=True)
    level = Column(String(30), nullable=True)
    is_core = Column(Boolean, nullable=False, default=False)
    source = Column(String(30), nullable=False, default="manual")
    source_reference = Column(String(500), nullable=True)
    confirmation_status = Column(String(20), nullable=False, default="confirmed")
    evidence = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    profile = relationship("CareerProfile", back_populates="courses")


class CareerProfileSkill(Base):
    """A normalized skill with proficiency, experience, and supporting evidence."""

    __tablename__ = "career_profile_skills"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "normalized_name",
            name="uq_career_profile_skills_profile_name",
        ),
        CheckConstraint(
            "proficiency_level IS NULL OR "
            "(proficiency_level >= 1 AND proficiency_level <= 5)",
            name="ck_career_profile_skills_proficiency",
        ),
        CheckConstraint(
            "years_experience IS NULL OR years_experience >= 0",
            name="ck_career_profile_skills_years",
        ),
        Index(
            "idx_career_profile_skills_profile_status",
            "profile_id",
            "confirmation_status",
        ),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    profile_id = Column(
        BigInteger,
        ForeignKey("career_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    normalized_name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=True)
    proficiency_level = Column(Integer, nullable=True)
    years_experience = Column(Numeric(5, 1), nullable=True)
    source = Column(String(30), nullable=False, default="manual")
    source_reference = Column(String(500), nullable=True)
    confirmation_status = Column(String(20), nullable=False, default="confirmed")
    evidence = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    profile = relationship("CareerProfile", back_populates="normalized_skills")


class CareerProfileChangeLog(Base):
    """Append-only audit record for manual and resume-derived profile changes."""

    __tablename__ = "career_profile_change_logs"
    __table_args__ = (
        Index(
            "idx_career_profile_change_logs_profile_created",
            "profile_id",
            "created_at",
        ),
        Index(
            "idx_career_profile_change_logs_profile_review",
            "profile_id",
            "review_status",
        ),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    profile_id = Column(
        BigInteger,
        ForeignKey("career_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type = Column(String(30), nullable=False)
    entity_id = Column(BigInteger, nullable=True)
    change_type = Column(String(30), nullable=False)
    source = Column(String(30), nullable=False, default="manual")
    source_reference = Column(String(500), nullable=True)
    before_data = Column(JSONB, nullable=True)
    after_data = Column(JSONB, nullable=True)
    conflict_data = Column(JSONB, nullable=True)
    review_status = Column(String(20), nullable=False, default="accepted")
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    profile = relationship("CareerProfile", back_populates="change_logs")
