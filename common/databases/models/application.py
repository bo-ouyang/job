from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, BigInteger, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
import enum
from common.utils.snowflake import generate_id

class ApplicationStatus(str, enum.Enum):
    APPLIED = "applied"       # 已投递
    VIEWED = "viewed"         # 被查看
    COMMUNICATING = "communicating" # 沟通中
    INTERVIEW = "interview"   # 面试
    OFFER = "offer"           # 发送Offer
    REJECTED = "rejected"     # 不合适

class Application(Base):
    """职位投递申请表"""
    __tablename__ = 'applications'
    __table_args__ = (
        Index("idx_app_user_status_created", "user_id", "status", "created_at"),
        Index("idx_app_job_status_created", "job_id", "status", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True)
    job_id = Column(BigInteger, ForeignKey('jobs.id'), nullable=False, index=True)
    resume_id = Column(BigInteger, ForeignKey('resumes.id'), nullable=True) # 投递时使用的简历快照ID
    
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.APPLIED)
    
    # 备注或消息
    note = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    user = relationship("User", backref="applications")
    job = relationship("Job", backref="applications")
    resume = relationship("Resume")

    def __repr__(self):
        return f"<Application(user={self.user_id}, job={self.job_id}, status={self.status})>"
