from sqlalchemy import (
    String, Integer, Text, ForeignKey, JSON, BigInteger, Index
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship
)
from .base import Base

# # 多对多关联表
# job_skills = Table(
#     'skills',
#     Base.metadata,
#     Column('job_id', Integer, ForeignKey('jobs.id')),
#     Column('skill_id', Integer, ForeignKey('skills.id'))
# )


class SchoolSpecialIntro(Base):
    __tablename__ = "school_special_intro"
    __table_args__ = (
        Index("idx_school_intro_school_special", "school_id", "special_id"),
        Index("idx_school_intro_status_label", "status", "label"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("school_specials.id"),
        primary_key=True
    )

    school_id: Mapped[int] = mapped_column(BigInteger, index=True)
    special_id: Mapped[int] = mapped_column(BigInteger, index=True)

    name: Mapped[str] = mapped_column(String(50))
    degree: Mapped[str] = mapped_column(String(50))

    content: Mapped[str] = mapped_column(Text)

    job: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10))
    label: Mapped[str] = mapped_column(String(10))

    elective: Mapped[list] = mapped_column(JSON, default=list)
    video: Mapped[list] = mapped_column(JSON, default=list)

    satisfaction: Mapped[dict] = mapped_column(JSON)

    is_video: Mapped[int] = mapped_column(Integer)

    # 一对一关系：一个详细介绍属于一个专业
    special = relationship(
        "SchoolSpecial",
        back_populates="intro"  # 对应 SchoolSpecial.intro
    )

    def __repr__(self):
        return f"<SchoolSpecialIntro {self.name}>"

