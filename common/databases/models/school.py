
from sqlalchemy import (
    String, Integer, BigInteger, Index
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)
from .base import Base
from common.utils.snowflake import generate_id

class School(Base):
    __tablename__ = "schools"
    __table_args__ = (
        Index("idx_schools_name", "name"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    # 关系
    # 一对多关系：一个学校有多个专业
    specials  = relationship(
        "SchoolSpecial",  # 关联的模型类
        back_populates="school",  # 反向引用字段名
        cascade="all, delete-orphan",  # 级联操作
        lazy="selectin",  # 推荐使用 selectin 加载
        order_by="SchoolSpecial.id"  # 可选：排序
    )
    
    def __repr__(self):
        return f"<School {self.id} {self.name}>"

    def __repr__(self):
        return f"<School {self.id} {self.name}>"
