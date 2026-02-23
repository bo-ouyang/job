from sqlalchemy import Column, Integer, String, DateTime, Text, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
from common.utils.snowflake import generate_id

class Skills(Base):
    """技能关键词表"""
    __tablename__ = 'skills'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    category = Column(String(50), index=True)  # 技能分类
    description = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    # 关系
    #jobs = relationship("Job", back_populates="skills")
    def __repr__(self):
        return f"<Skill(id={self.id}, name='{self.name}')>"
