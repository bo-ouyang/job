from sqlalchemy import Column, Integer, String, DateTime, Boolean, func,SmallInteger, BigInteger, Index
from common.databases.models.base import Base
from common.utils.snowflake import generate_id

class BossSpiderFilter(Base):
    """
    Boss爬虫筛选配置表
    用于生成爬取任务的配置模板
    """
    __tablename__ = 'boss_spider_filter'
    __table_args__ = (
        Index("idx_boss_filter_active_name", "is_active", "filter_name"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    filter_name = Column(String(255), nullable=True, comment='筛选条件 (e.g. city)')
    is_active = Column(SmallInteger, default=1, comment='是否启用')
    note = Column(String(255), nullable=True, comment='备注')
    filter_value = Column(String(255), nullable=True, comment='筛选条件值 (e.g. 101020100)')

    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    def __repr__(self):
        return f"<BossSpiderFilter(name='{self.filter_name}', active={self.is_active})>"
