
from sqlalchemy import (
    String, Integer, ForeignKey, BigInteger, Index
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)
from .base import Base
from common.utils.snowflake import generate_id

class SchoolSpecial(Base):
    __tablename__ = "school_specials"
    __table_args__ = (
        Index("idx_school_special_school_sid", "school_id", "special_id"),
        Index("idx_school_special_level3_year", "level3_code", "year"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id
    )

    school_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("schools.id"), index=True
    )

    special_id: Mapped[int] = mapped_column(
        BigInteger, index=True
    )

    special_name: Mapped[str] = mapped_column(String(50))
    code: Mapped[str] = mapped_column(String(20))

    # 层级
    level1_name: Mapped[str] = mapped_column(String(50))
    level2_name: Mapped[str] = mapped_column(String(50))
    level3_name: Mapped[str] = mapped_column(String(50))
    level3_code: Mapped[str] = mapped_column(String(20))

    # 属性
    nation_feature: Mapped[str] = mapped_column(String(10))
    province_feature: Mapped[str] = mapped_column(String(10))
    is_important: Mapped[str] = mapped_column(String(10))
    limit_year: Mapped[str] = mapped_column(String(20))
    year: Mapped[str] = mapped_column(String(10))

    # 排名
    xueke_rank: Mapped[str] = mapped_column(String(10))
    xueke_rank_score: Mapped[str] = mapped_column(String(10))
    ruanke_rank: Mapped[str] = mapped_column(String(10))
    ruanke_level: Mapped[str] = mapped_column(String(10))

    is_video: Mapped[int] = mapped_column(Integer)

    # 多对一关系：一个专业属于一个学校
    school = relationship( 
        "School",
        back_populates="specials"  # 对应 School.specials
    )
    
    
    # 一对一关系：一个专业有一个详细介绍
    intro  = relationship(
        "SchoolSpecialIntro",
        back_populates="special",  # 对应 SpecialIntro.special
        uselist=False,  # 关键：表示一对一关系
        cascade="all, delete-orphan",  # 级联操作
        lazy="joined"  # 通常一对一推荐使用 joined 立即加载
    )
    
    def __repr__(self):
        return f"<SchoolSpecial {self.school_id}-{self.special_name}>"
