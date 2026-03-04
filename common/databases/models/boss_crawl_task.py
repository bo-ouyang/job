from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func, BigInteger
from common.databases.models.base import Base
from common.utils.snowflake import generate_id

class BossCrawlTask(Base):
    """
    Boss直聘爬虫任务表 (执行队列)
    """
    __tablename__ = 'boss_crawl_task'

    id = Column(BigInteger, primary_key=True, default=generate_id)
    url = Column(String(250), unique=True, nullable=False, index=True, comment='爬取URL')
    
    # 关联配置 (可选，如果是手动添加的则为空)
    filter_id = Column(BigInteger, ForeignKey('boss_spider_filter.id'), nullable=True, comment='关联的筛选配置ID')
    
    # 任务状态
    status = Column(String(50), default='pending', index=True, comment='状态: pending, processing, done, error')
    priority = Column(Integer, default=0, comment='优先级 (越大越优先)')
    pid = Column(Integer, nullable=True, comment='爬虫进程ID')
    
    # 执行结果
    last_crawl_time = Column(DateTime, nullable=True, comment='最后爬取时间')
    error_msg = Column(Text, nullable=True, comment='错误信息')
    
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    def __repr__(self):
        return f"<BossCrawlTask(id={self.id}, status='{self.status}', url='{self.url}')>"
