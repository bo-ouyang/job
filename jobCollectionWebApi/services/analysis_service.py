from typing import Dict, Any, List
from config import settings
from common.databases.RedisManager import redis_manager
from common.databases.PostgresManager import db_manager
from crud.job import job as crud_job
from common.search.conn import get_es
import logging

logger = logging.getLogger(__name__)

class AnalysisService:
    """数据分析服务 (ES Aggregations + PostgreSQL Fallback)"""
    
    def __init__(self):
        pass

    async def _get_es_stats(self, **filters) -> Dict[str, Any]:
        """尝试从 ES 聚合统计"""
        es = await get_es()
        
        # 1. 构造过滤条件
        filter_clauses = []
        if filters.get("keyword"):
            filter_clauses.append({"multi_match": {"query": filters["keyword"], "fields": ["title", "description"]}})
        if filters.get("location"):
             filter_clauses.append({"term": {"city_code": filters["location"]}})
        if filters.get("experience"):
             filter_clauses.append({"prefix": {"experience": filters["experience"]}})
        if filters.get("education"):
             filter_clauses.append({"prefix": {"education": filters["education"]}})
        if filters.get("industry_2"):
             filter_clauses.append({"term": {"industry_code": filters["industry_2"]}})
        elif filters.get("industry"):
             from sqlalchemy import select, or_
             from common.databases.models.industry import Industry
             async with db_manager.async_session() as session:
                 stmt = select(Industry.code).where(
                     or_(Industry.code == filters["industry"], Industry.parent_id == filters["industry"])
                 )
                 res = await session.execute(stmt)
                 industry_codes = res.scalars().all()
                 if industry_codes:
                     filter_clauses.append({"terms": {"industry_code": industry_codes}})
                 else:
                     logger.warning(f"No industry codes found for industry: {filters['industry']}")
        logger.info(f"filter_clauses: {filter_clauses}")
        # 组装 query
        query_dsl = {
             "query": {"bool": {"filter": filter_clauses}} if filter_clauses else {"match_all": {}},
             "size": 0, # 不需要返回具体文档，只看聚合
             "aggs": {
                  # 薪资聚合 (利用 range 根据实际人民币元)
                  "salary_ranges": {
                      "range": {
                          "field": "salary_min",
                          "ranges": [
                              {"to": 10000.0, "key": "10k以下"},
                              {"from": 10000.0, "to": 15000.0, "key": "10k-15k"},
                              {"from": 15000.0, "to": 25000.0, "key": "15k-25k"},
                              {"from": 25000.0, "to": 35000.0, "key": "25k-35k"},
                              {"from": 35000.0, "key": "35k以上"}
                          ]
                      }
                  },
                  # 行业分布
                  "top_industries": {
                      "terms": {"field": "industry", "size": 10}
                  },
                  # 技能需求
                  "top_skills": {
                      "terms": {"field": "skills", "size": 10}
                  }
             }
        }
        logger.info(f"query_dsl: {query_dsl}")
        resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
        aggs = resp.get("aggregations", {})
        
        salary_dist = [{"name": bucket["key"], "value": bucket["doc_count"]} for bucket in aggs.get("salary_ranges", {}).get("buckets", [])]
        industry_dist = [{"name": bucket["key"], "value": bucket["doc_count"]} for bucket in aggs.get("top_industries", {}).get("buckets", [])]
        skill_dist = [{"name": bucket["key"], "value": bucket["doc_count"]} for bucket in aggs.get("top_skills", {}).get("buckets", [])]
        
        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist,
            "total_jobs": resp["hits"]["total"]["value"]
        }

    async def get_job_stats(self, **filters) -> Dict[str, Any]:
        """获取职位统计数据 (集成分布式锁防击穿与 ES/PG Fallback)"""
        cache_key = f"analysis:stats:v2:{hash(frozenset(filters.items()))}"
        
        # 1. 直接查询缓存
        cached_result = await redis_manager.get_cache(cache_key)
        if cached_result is not None: 
            return cached_result
            
        # 2. 缓存击穿防护：尝试获取分布式锁 (最多等待 5 秒，锁存活 15 秒)
        lock_key = f"lock:{cache_key}"
        async with redis_manager.cache_lock(lock_key, expire=15, timeout=5.0) as locked:
            if not locked:
                # 若没拿到锁，并且等待超时了，直接抛出或者返回空/降级数据，保护 DB
                logger.warning(f"Failed to acquire cache lock for {cache_key}, returning empty set.")
                return {"salary": [], "skills": [], "industries": [], "total_jobs": 0}
            
            # 3. 拿到锁后，Double Check (DCL)
            cached_result = await redis_manager.get_cache(cache_key)
            if cached_result is not None:
                return cached_result

            # 4. 执行高耗时统计查表
            try:
                 result = await self._get_es_stats(**filters)
                 logger.info("Generated job stats using Elasticsearch Aggregations.")
            except Exception as e:
                 logger.warning(f"ES Stats Aggregation failed: {e}. Falling back to PostgreSQL.")
                 async with db_manager.async_session() as session:
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
                     
            # 5. 写入缓存 (启用防雪崩的 TTL 抖动机制)
            await redis_manager.set_cache(cache_key, result, expire=600, jitter=True)
            return result

    async def analyze_by_keywords(self, keywords: List[str], industry_codes: List[int] = None, **filters) -> Dict[str, Any]:
        """多关键词对比分析"""
        if not keywords and not industry_codes: return {}
        
        cache_key = f"analysis:keywords:{'-'.join(sorted(keywords))}:{hash(str(industry_codes))}:{hash(frozenset(filters.items()))}"
        cached_result = await redis_manager.get_cache(cache_key)
        if cached_result is not None: 
            return cached_result

        lock_key = f"lock:{cache_key}"
        async with redis_manager.cache_lock(lock_key, expire=15, timeout=5.0) as locked:
            if not locked:
                return {}
                
            cached_result = await redis_manager.get_cache(cache_key)
            if cached_result is not None:
                return cached_result
                
            logger.info("Using PostgreSQL for complex Keyword Grouping Analysis Fallback.")
            async with db_manager.async_session() as session:
                result = await crud_job.analyze_by_keywords(
                    session,
                    keywords=keywords,
                    location=filters.get("location"),
                    industry_codes=industry_codes
                )
                
            await redis_manager.set_cache(cache_key, result, expire=600, jitter=True)
            return result

analysis_service = AnalysisService()
