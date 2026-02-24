from sqlalchemy import Column, Integer, String, DateTime, Text, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
from common.utils.snowflake import generate_id

class Company(Base):
    """公司信息表"""
    __tablename__ = 'company'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    source_id = Column(String(50), nullable=True, unique=True,comment="Boss直聘 encryptBrandId") 
    name = Column(String(255), nullable=False, index=True)
    industry = Column(String(100))
    scale = Column(String(50))  # 公司规模
    stage = Column(String(50)) # 融资阶段 e.g. "已上市"
    location = Column(String(100))
    logo = Column(String(255)) # 公司Logo
    website = Column(String(255))
    description = Column(Text)
    introduction = Column(Text) # 公司介绍
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 关系
    jobs = relationship("Job", back_populates="company")
    
    def __repr__(self):
        return f"<Company(id={self.id}, name='{self.name}')>"
