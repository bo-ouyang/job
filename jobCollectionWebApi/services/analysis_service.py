from typing import Dict, Any
from config import settings
from common.databases.RedisManager import redis_manager
from common.databases.PostgresManager import db_manager
from crud.job import job as crud_job
import logging

logger = logging.getLogger(__name__)

class AnalysisService:
    """数据分析服务 (PostgreSQL Implementation)"""
    
    def __init__(self):
        pass

    async def get_job_stats(self, **filters) -> Dict[str, Any]:
        """
        获取职位统计数据
        带有 Redis 缓存
        """
        # 1. 尝试从 Redis 获取缓存
        cache_key = f"analysis:stats:{hash(frozenset(filters.items()))}"
        cached = await redis_manager.get_cache(cache_key)
        if cached:
            return cached

        # 2. 从数据库获取统计 (使用 PostgreSQL 优化的查询)
        async with db_manager.async_session() as session:
            # 复用 crud.job.get_statistics_from_db
            # 注意: 该方法目前基于 Python 内存聚合，后续应优化为 PG 原生聚合查询
            result = await crud_job.get_statistics_from_db(
                session,
                keyword=filters.get("keyword"),
                location=filters.get("location"),
                experience=filters.get("experience"),
                education=filters.get("education"),
                industry=filters.get("industry"),
                industry_2=filters.get("industry_2"),
                salary_min=filters.get("salary_min"),
                salary_max=filters.get("salary_max")
            )

        # 3. 写入缓存 (10分钟)
        await redis_manager.set_cache(cache_key, result, expire=600)
        return result

    async def analyze_by_keywords(self, keywords: list[str], industry_codes: list[int] = None, **filters) -> Dict[str, Any]:
        """根据多个关键词进行聚合分析"""
        if not keywords and not industry_codes:
            return {}

        # 1. Cache
        # Include industry_codes in cache key
        cache_key = f"analysis:keywords:{'-'.join(sorted(keywords))}:{hash(str(industry_codes))}:{hash(frozenset(filters.items()))}"
        cached = await redis_manager.get_cache(cache_key)
        if cached:
            return cached

        # 2. DB Analysis
        async with db_manager.async_session() as session:
             # 复用 crud.job.analyze_by_keywords
            result = await crud_job.analyze_by_keywords(
                session,
                keywords=keywords,
                location=filters.get("location"),
                industry_codes=industry_codes
            )
            
        # 3. 写入缓存
        await redis_manager.set_cache(cache_key, result, expire=600)
        
        return result

analysis_service = AnalysisService()
