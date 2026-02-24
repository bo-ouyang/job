from sqlalchemy import Column, Integer, String, DateTime, Text, func, BigInteger
from common.databases.models.base import Base
from common.utils.snowflake import generate_id

class SpiderBossCrawlUrl(Base):
    """
    Boss直聘爬虫URL管理表
    """
    __tablename__ = 'spider_boss_crawl_url'

    id = Column(BigInteger, primary_key=True, default=generate_id)
    url = Column(String(255), unique=True, nullable=False, index=True, comment='爬取URL')
    city_code = Column(String(20), nullable=True, comment='城市编码')
    industry_code = Column(String(20), nullable=True, comment='行业编码')
    page = Column(Integer, default=1, comment='当前页码')
    status = Column(String(50), default='pending', index=True, comment='状态: pending, processing, done, error')
    last_crawl_time = Column(DateTime, nullable=True, comment='最后爬取时间')
    error_msg = Column(Text, nullable=True, comment='错误信息')
    
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    def __repr__(self):
        return f"<SpiderBossCrawlUrl(id={self.id}, url='{self.url}', status='{self.status}')>"
