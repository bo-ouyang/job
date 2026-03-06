from sqlalchemy import Column, String, DateTime, Text, BigInteger, Float, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from .base import Base
from common.utils.snowflake import generate_id


class AiTask(Base):
    """AI 异步任务记录表"""
    __tablename__ = 'ai_tasks'

    id             = Column(BigInteger, primary_key=True, default=generate_id)
    user_id        = Column(BigInteger, nullable=False, index=True)
    celery_task_id = Column(String(50), nullable=False, unique=True, index=True)
    feature_key    = Column(String(50), nullable=False, index=True)  # career_advice / career_compass / resume_parse
    status         = Column(String(20), default='pending', index=True)  # pending / processing / completed / failed
    request_params = Column(JSONB, nullable=True)       # 用户提交的请求参数
    result_data    = Column(Text, nullable=True)         # AI 返回的完整输出
    error_message  = Column(Text, nullable=True)         # 失败时的错误信息
    execution_time = Column(Float, nullable=True)        # 执行耗时(秒)
    created_at     = Column(DateTime, server_default=func.now())
    completed_at   = Column(DateTime, nullable=True)
    analysis_input = Column(JSONB, nullable=True)
    __table_args__ = (
        Index('idx_ai_task_user_feature', 'user_id', 'feature_key'),
        Index('idx_ai_task_user_status', 'user_id', 'status'),
    )

    def __repr__(self):
        return f"<AiTask(id={self.id}, user={self.user_id}, feature='{self.feature_key}', status='{self.status}')>"
