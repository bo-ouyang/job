from sqlalchemy import Column, Integer, String, Text, ForeignKey, BigInteger, JSON, Index
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from .base import Base
from common.utils.snowflake import generate_id
from sqlalchemy.dialects.postgresql import JSONB

class Major(Base):
    """
    专业表模型
    支持 专业大类-具体专业 多级结构
    """
    __tablename__ = 'majors'
    __table_args__ = (
        Index("idx_majors_parent_level", "parent_id", "level"),
        Index("idx_majors_name_code", "name", "code"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    
    name = Column(String(100), nullable=False, index=True, comment='专业名称')
    code = Column(String(20), nullable=True, index=True, default='', comment='专业代码')
    
    # 层级关系
    parent_id = Column(BigInteger, ForeignKey('majors.id'), nullable=True, comment='父级ID')
    level = Column(Integer, default=0, comment='层级：0-专业大类，1-具体专业')
    
    description = Column(Text, nullable=True, default='', comment='描述')
    
    # 自关联关系
    parent = relationship('Major', remote_side=[id], back_populates='children')
    children = relationship('Major', back_populates='parent', cascade="all, delete-orphan")
    
    # 关联到行业映射
    industry_relations = relationship("MajorIndustryRelation", back_populates="major", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Major(id={self.id}, name='{self.name}', level={self.level})>"

class MajorIndustryRelation(Base):
    """
    专业与行业关联表
    一个专业对应多个行业(JSON数据code)
    """
    __tablename__ = 'major_industry_relations'
    __table_args__ = (
        Index("idx_major_ind_rel_major_score", "major_id", "relevance_score"),
        Index("idx_major_ind_rel_name", "major_name"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    
    major_id = Column(BigInteger, ForeignKey('majors.id'), nullable=True, index=True)
    major_name = Column(String(100), nullable=True, index=True, default='', comment='专业名称')
    
    # 关联到 Industry 表的 code 字段列表
    industry_codes = Column(JSONB, nullable=True, default={}, comment='行业编码列表 (JSON Array)')
    
    # 额外属性
    keywords = Column(String(500), nullable=True, default='', comment='分析关键词 (逗号分隔)')
    relevance_score = Column(Integer, default=0, comment='相关度/热度')
    
    # 关系
    major = relationship("Major", back_populates="industry_relations")

    def __repr__(self):
        return f"<MajorIndustryRelation(major_name='{self.major_name}', codes={self.industry_codes})>"
