from sqlalchemy import Column, Integer, String, DateTime, JSON, Index, Text, Float, BigInteger
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from .base import Base
from common.utils.snowflake import generate_id

class AnalysisResult(Base):
    """分析结果表"""
    __tablename__ = 'analysis_results'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    analysis_type = Column(String(50), nullable=False, index=True)  # 分析类型
    parameters = Column(JSONB)  # 分析参数
    result_data = Column(JSONB)  # 分析结果
    created_at = Column(DateTime, default=func.now())
    
    # 索引
    __table_args__ = (
        Index('idx_analysis_type_created', 'analysis_type', 'created_at'),
    )
    
    def __repr__(self):
        return f"<AnalysisResult(id={self.id}, type='{self.analysis_type}')>"

class UserQuery(Base):
    """用户查询记录表 (专门记录搜索行为)"""
    __tablename__ = 'user_query'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    query_type = Column(String(50), nullable=False, index=True) # e.g. "job_search"
    parameters = Column(JSONB) # 搜索参数详情
    result_count = Column(Integer, default=0)
    user_id = Column(BigInteger, nullable=True, index=True)
    user_ip = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f"<UserQuery(id={self.id}, type='{self.query_type}')>"

class APILog(Base):
    """全局接口日志表 (记录 QPS, 耗时, 访问量)"""
    __tablename__ = 'api_logs'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    path = Column(String(255), index=True)
    method = Column(String(20))
    status_code = Column(Integer)
    process_time = Column(Float)  # 耗时 (秒)
    user_id = Column(BigInteger, nullable=True, index=True)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=func.now(), index=True)

    def __repr__(self):
        return f"<APILog(id={self.id}, path='{self.path}', time={self.process_time}s)>"

class TaskLog(Base):
    """Celery 任务日志表"""
    __tablename__ = 'task_logs'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    task_id = Column(String(50), nullable=False, index=True)
    task_name = Column(String(100), index=True)
    status = Column(String(20), index=True) # PENDING, STARTED, SUCCESS, FAILURE
    args = Column(JSON)      # 任务参数
    kwargs = Column(JSON)
    result = Column(Text)    # 结果或错误信息
    worker = Column(String(100))
    execution_time = Column(Float) # 执行耗时(秒)
    created_at = Column(DateTime, default=func.now(), index=True)
    
    def __repr__(self):
        return f"<TaskLog(id={self.id}, task='{self.task_name}', status='{self.status}')>"
