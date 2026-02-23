from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Date, BigInteger
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .base import Base
from datetime import datetime
from common.utils.snowflake import generate_id

class Resume(Base):
    """简历主表"""
    __tablename__ = "resumes"
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, unique=True, comment="关联用户ID")
    
    # 基本信息
    name = Column(String(50), nullable=False, comment="姓名")
    gender = Column(String(10), comment="性别")
    age = Column(Integer, comment="年龄")
    avatar = Column(String(255), comment="头像URL")
    phone = Column(String(20), comment="联系电话")
    email = Column(String(100), comment="联系邮箱")
    wechat = Column(String(50), comment="微信号")
    
    # 求职意向
    desired_position = Column(String(100), comment="期望职位")
    desired_salary = Column(String(50), comment="期望薪资")
    desired_city = Column(String(50), comment="期望城市")
    current_status = Column(String(50), comment="求职状态: 离职-随时到岗/在职-月内到岗等")
    
    # 概括
    summary = Column(Text, comment="个人优势/自我评价")
    attachment_url = Column(String(255), comment="附件简历URL")
    
    # 关联
    user = relationship("User", back_populates="resume")
    educations = relationship("Education", back_populates="resume", cascade="all, delete-orphan")
    work_experiences = relationship("WorkExperience", back_populates="resume", cascade="all, delete-orphan")
    projects = relationship("ProjectExperience", back_populates="resume", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class Education(Base):
    """教育经历"""
    __tablename__ = "resume_educations"
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    resume_id = Column(BigInteger, ForeignKey("resumes.id"), nullable=False)
    school = Column(String(100), nullable=False, comment="学校")
    major = Column(String(100), comment="专业")
    degree = Column(String(50), comment="学历")
    start_date = Column(Date, comment="开始时间")
    end_date = Column(Date, comment="结束时间")
    description = Column(Text, comment="在校经历描述")
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    resume = relationship("Resume", back_populates="educations")

class WorkExperience(Base):
    """工作经历"""
    __tablename__ = "resume_works"
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    resume_id = Column(BigInteger, ForeignKey("resumes.id"), nullable=False)
    company = Column(String(100), nullable=False, comment="公司名称")
    position = Column(String(100), nullable=False, comment="职位名称")
    start_date = Column(Date, comment="开始时间")
    end_date = Column(Date, comment="结束时间") # null means present
    department = Column(String(50), comment="所属部门")
    content = Column(Text, comment="工作内容")
    achievement = Column(Text, comment="工作业绩")
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    resume = relationship("Resume", back_populates="work_experiences")

class ProjectExperience(Base):
    """项目经历"""
    __tablename__ = "resume_projects"
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    resume_id = Column(BigInteger, ForeignKey("resumes.id"), nullable=False)
    name = Column(String(100), nullable=False, comment="项目名称")
    role = Column(String(100), comment="担任角色")
    start_date = Column(Date, comment="开始时间")
    end_date = Column(Date, comment="结束时间")
    description = Column(Text, comment="项目描述")
    performance = Column(Text, comment="项目业绩/连接")
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    resume = relationship("Resume", back_populates="projects")
