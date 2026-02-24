from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
from common.utils.snowflake import generate_id

class FavoriteJob(Base):
    """职位收藏表"""
    __tablename__ = 'favorite_jobs'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    job_id = Column(BigInteger, ForeignKey('jobs.id'), nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())
    
    user = relationship("User", backref="favorite_jobs")
    job = relationship("Job")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'job_id', name='uq_user_job_favorite'),
    )

class FollowCompany(Base):
    """公司关注表"""
    __tablename__ = 'follow_companies'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    company_id = Column(BigInteger, ForeignKey('company.id'), nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())
    
    user = relationship("User", backref="followed_companies")
    company = relationship("Company")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'company_id', name='uq_user_company_follow'),
    )
