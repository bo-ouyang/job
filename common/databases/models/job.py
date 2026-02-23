from sqlalchemy import Column, Integer, String, DateTime, Text, Float, Boolean, ForeignKey, \
Table, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from .base import Base
from common.utils.snowflake import generate_id

# # 多对多关联表
# job_skills = Table(
#     'skills',
#     Base.metadata,
#     Column('job_id', Integer, ForeignKey('jobs.id')),
#     Column('skill_id', Integer, ForeignKey('skills.id'))
# )

class Job(Base):
    """职位信息表"""
    __tablename__ = 'jobs'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    requirements = Column(Text)
    salary_min = Column(Float)
    salary_max = Column(Float)

    salary_unit = Column(String(20), default='月')  # 月/年/小时
    salary_desc = Column(String(50)) # 原始薪资描述 e.g. "18-35K"
    
    # HR/Boss信息
    boss_name = Column(String(50))
    boss_title = Column(String(50))
    boss_avatar = Column(String(255))
    
    experience = Column(String(50))  # 经验要求
    education = Column(String(50))   # 学历要求
    location = Column(String(100))
    area_district = Column(String(100)) # 行政区
    business_district = Column(String(100)) # 商圈
    longitude = Column(Float)
    latitude = Column(Float)
    
    # 标签与福利
    tags = Column(JSONB) # JSON of job labels
    welfare = Column(JSONB) # JSON of welfare list
    work_type = Column(String(50))   # 全职/兼职/实习
    source_site = Column(String(50)) # 来源网站
    source_url = Column(String(255), unique=True)
    publish_date = Column(DateTime)
    encrypt_job_id = Column(String(100), unique=True, index=True, comment="Boss直聘 encryptJobId")
    job_labels = Column(JSONB) # JSON of jobLabels list e.g. ["1-3年", "本科", "Python"]
    company_id = Column(BigInteger, ForeignKey('company.id'),nullable=True, index=True)
    
    # skill_id = Column(Integer, ForeignKey("skills.id"), nullable=True, index=True)

    industry_code = Column(Integer, nullable=True, index=True)
    city_code = Column(Integer, nullable=True, index=True)
    
    industry_id = Column(BigInteger, ForeignKey('industries.id'), nullable=True, index=True)
    # AI 大模型解析提取
    ai_parsed = Column(Integer, default=0, comment="0:未解析, 1:解析中, 2:已解析")
    ai_summary = Column(Text, comment="AI一句话职责总结")
    ai_skills = Column(JSONB, comment="AI提取的技能标签数组")
    ai_benefits = Column(JSONB, comment="AI提取的福利待遇数组")

    # 元数据
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)
    is_crawl = Column(Integer, default=0, comment="是否已抓取详情")
    
    #is_crawled = Column(Boolean, default=False)
    # 关系
    company = relationship("Company", back_populates="jobs")
    
    #skills = relationship("skills", secondary=job_skills, back_populates="jobs")
    #skills = relationship("Skills",  back_populates="jobs")
    
    industry = relationship("Industry", back_populates="jobs")
    
    def __repr__(self):
        
        return f"<Job(id={self.id}, title='{self.title}')>"
