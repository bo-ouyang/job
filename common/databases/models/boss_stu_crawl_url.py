from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, BigInteger, Index
from sqlalchemy.sql import func
from .base import Base
from common.utils.snowflake import generate_id

class BossStuCrawlUrl(Base):
    __tablename__ = 'boss_stu_crawl_urls'
    __table_args__ = (
        Index("idx_boss_stu_major_status", "major_name", "status"),
        Index("idx_boss_stu_status_created", "status", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    url = Column(String(255), nullable=False, comment='完整的爬取URL')
    ka = Column(String(100), nullable=True, comment='埋点KA字符串')
    major_name = Column(String(100), nullable=True, index=True, comment='所属专业名称')
    status = Column(String(20), default='pending', index=True, comment='状态: pending, processing, done, error')
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_crawl_time = Column(DateTime(timezone=True), nullable=True)
    error_msg = Column(Text, nullable=True)

    def __repr__(self):
        return f"<BossStuCrawlUrl(url='{self.url}', status='{self.status}')>"
