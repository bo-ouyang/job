from typing import Dict, Any, List
from config import settings
from common.databases.RedisManager import redis_manager
from common.databases.PostgresManager import db_manager
from crud.job import job as crud_job
from crud.industry import industry as crud_industry
from common.search.conn import get_es
from core.logger import sys_logger as logger
from collections import Counter
from sqlalchemy import select
from common.databases.models.industry import Industry
from common.databases.models.major import Major, MajorIndustryRelation
class AnalysisService:
    """数据分析服务 (ES Aggregations + PostgreSQL Fallback)"""
    
    def __init__(self):
        pass

    async def _get_es_stats(self, **filters) -> Dict[str, Any]:
        """尝试从 ES 聚合统计"""
        es = await get_es()
        bool_query = {}
        should_clauses = []

        # 1. 纯净的文本大范围匹配条件组装 (SHOULD: 命中任何一个即可)
        if filters.get("keyword"):
            should_clauses.append({"multi_match": {"query": filters.get("keyword"), "fields": ["title^2", "description"]}})
        if filters.get("industry_name"):
            should_clauses.append({"multi_match": {"query": filters.get("industry_name"), "fields": ["title^2", "description"]}})
        if filters.get("industry_2_name"):
            should_clauses.append({"multi_match": {"query": filters.get("industry_2_name"), "fields": ["title^2", "description"]}})
            
        if should_clauses:
            bool_query["must"] = [{"bool": {"should": should_clauses, "minimum_should_match": 1}}]
            
        # 2. 严格的分类/级联过滤条件组装 (FILTER: 必须满足)
        filter_clauses = []
        
        # 修复 location 匹配字段
        location = filters.get("location")
        if location:
            filter_clauses.append({"prefix": {"location": location}})
            
        if filters.get("experience"):
            filter_clauses.append({"prefix": {"experience": filters["experience"]}})
        if filters.get("education"):
            filter_clauses.append({"prefix": {"education": filters["education"]}})
            
        # 修复行业逻辑: 必须严格在此行业范围内
        if filters.get("industry"):
            industry_codes = await self._fetch_industry_codes_with_cache(filters["industry"])
            if industry_codes:
                filter_clauses.append({"terms": {"industry_code": industry_codes}})
            else:
                filter_clauses.append({"term": {"industry_code": -1}})
                
        if filter_clauses:
            bool_query["filter"] = filter_clauses

        # 3. 组装 query
        query_dsl = {
            "query": {"bool": bool_query} if bool_query else {"match_all": {}},
            "size": 0,
            "aggs": {
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
                # 💡 优化 4：加上 .keyword 保平安 (如果你的映射已经定义死为 keyword 类型，可不加)
                "top_industries": {"terms": {"field": "industry_code", "size": 10}},
                "top_skills": {"terms": {"field": "skills", "size": 15}},
                "top_ai_skills": {"terms": {"field": "ai_skills", "size": 15}}
            }
        }
        
        #logger.info(f"ES Query DSL: {query_dsl}")

        # 3. 💡 优化 5：容错兜底
        try:
            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
        except Exception as e:
            logger.error(f"ES 聚合查询彻底失败: {e}", exc_info=True)
            # 返回空结果兜底，防止前端页面崩溃
            return {"salary": [], "skills": [], "industries": [], "total_jobs": 0}

        # 4. 数据解析与清洗
        aggs = resp.get("aggregations", {})
        
        salary_dist = [{"name": b["key"], "value": b["doc_count"]} for b in aggs.get("salary_ranges", {}).get("buckets", [])]
        # Map industry codes to names using PG
        industry_buckets = aggs.get("top_industries", {}).get("buckets", [])
        industry_dist = []
        if industry_buckets:
            industry_codes_to_fetch = [int(b["key"]) for b in industry_buckets if str(b["key"]).isdigit()]
            if industry_codes_to_fetch:

                async with db_manager.async_session() as session:
                    stmt = select(Industry.code, Industry.name).where(Industry.code.in_(industry_codes_to_fetch))
                    code_to_name = {row.code: row.name for row in await session.execute(stmt)}
                    
                for b in industry_buckets:
                    code = int(b["key"]) if str(b["key"]).isdigit() else -1
                    if code in code_to_name:
                        industry_dist.append({"name": code_to_name[code], "value": b["doc_count"]})
                        
        # 💡 优化 3：使用 Counter 优雅合并与排序
        skill_counter = Counter()
        
        # 直接累加
        for b in aggs.get("top_skills", {}).get("buckets", []):
            skill_counter[b["key"]] += b["doc_count"]
        for b in aggs.get("top_ai_skills", {}).get("buckets", []):
            skill_counter[b["key"]] += b["doc_count"]
            
        # Counter 内置的 most_common 直接输出排序后的 Top 10！
        skill_dist = [{"name": k, "value": v} for k, v in skill_counter.most_common(10)]
        
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

    async def _get_es_analyze_by_keywords(self, keywords: List[str], industry_codes: List[int] = None, **filters) -> Dict[str, Any]:
        """尝试从 ES 聚合统计多关键词（专业分析核心）"""
        es = await get_es()
        
        bool_query = {}
            
        # (1) 处理专业核心条件：【行业属于这些】 OR 【标题/描述包含这些词】
        should_clauses = []
        
        if industry_codes:
            should_clauses.append({"terms": {"industry_code": industry_codes}})
            
        if keywords:
            for kw in keywords:
                should_clauses.append({
                    "multi_match": {
                        "query": kw,
                        # 建议提升 title 权重，符合前面我们讨论的最佳实践
                        "fields": ["title^2", "description"] 
                    }
                })
                
        if should_clauses:
            # 将 OR 逻辑放入 bool.must 中
            major_bool = {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1
                }
            }
            bool_query["must"] = [major_bool]
            
        # (2) 处理城市硬性条件 (AND)：对应 SQL 里的 ilike 'location%'
        location = filters.get("location")
        if location:
            # 因为是 AND 关系，放到 filter 中性能最好（不参与打分，带缓存）
            if "filter" not in bool_query:
                bool_query["filter"] = []
            
            # 使用 prefix 匹配对应 SQL 的 location.ilike(f"{location}%")
            bool_query["filter"].append({
                "prefix": {"location": location}
            })
            
        # ==========================
        # 2. 构建聚合条件 (Aggregations)
        # ==========================
        aggs = {
            # (1) 薪资分布 (分段聚合)
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
            # (2) 行业分布
            "top_industries": {
                "terms": {
                    "field": "industry_code", 
                    "size": 5
                }
            },
            # (3) 技能标签分布
            "top_skills": {
                "terms": {
                    "field": "tags", 
                    "size": 15
                }
            },
            "top_ai_skills": {
                "terms": {
                    "field": "ai_skills",
                    "size": 15
                }
            }
        }

        # ==========================
        # 3. 组装最终 DSL
        # ==========================
        dsl = {
            "query": {"bool": bool_query} if bool_query else {"match_all": {}},
            "size": 0, 
            "aggs": aggs
        }
        #logger.info(f"ES Query DSL: {dsl}")
        resp = await es.search(index=settings.ES_INDEX_JOB, body=dsl)
        #logger.info(f"ES Query Response Aggs: {resp.get('aggregations')}")
        aggs_result = resp.get("aggregations", {})
        
        salary_dist = [{"name": b["key"], "value": b["doc_count"]} for b in aggs_result.get("salary_ranges", {}).get("buckets", [])]
        
        industry_buckets = aggs_result.get("top_industries", {}).get("buckets", [])
        industry_dist = []
        if industry_buckets:
            industry_codes_to_fetch = [int(b["key"]) for b in industry_buckets if str(b["key"]).isdigit()]
            if industry_codes_to_fetch:
                from sqlalchemy import select
                from common.databases.models.industry import Industry
                async with db_manager.async_session() as session:
                    stmt = select(Industry.code, Industry.name).where(Industry.code.in_(industry_codes_to_fetch))
                    code_to_name = {row.code: row.name for row in await session.execute(stmt)}
                    
                for b in industry_buckets:
                    code = int(b["key"]) if str(b["key"]).isdigit() else -1
                    if code in code_to_name:
                        industry_dist.append({"name": code_to_name[code], "value": b["doc_count"]})
        
        skill_counter = Counter()
        for b in aggs_result.get("top_skills", {}).get("buckets", []):
            if b["key"]: skill_counter[b["key"]] += b["doc_count"]
        for b in aggs_result.get("top_ai_skills", {}).get("buckets", []):
            if b["key"]: skill_counter[b["key"]] += b["doc_count"]
            
        skill_dist = [{"name": k, "value": v} for k, v in skill_counter.most_common(15)]
        
        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist,
            "total_jobs": resp["hits"]["total"]["value"]
        }

    async def analyze_by_keywords(self, keywords: List[str], industry_codes: List[int] = None, **filters) -> Dict[str, Any]:
        """多关键词对比分析"""
        if not keywords and not industry_codes: return {}
        
        cache_key = f"analysis:keywords:v5:{'-'.join(sorted(keywords))}:{hash(str(industry_codes))}:{hash(frozenset(filters.items()))}"
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
                
            try:
                # 优先尝试使用 ES (性能提升百倍)
                result = await self._get_es_analyze_by_keywords(keywords, industry_codes, **filters)
                logger.info("Generated keyword analysis via ES.")
            except Exception as e:
                # 降级：如果 ES 挂了，走原始的 PostgreSQL + ILIKE 查询
                logger.warning(f"ES Keyword Analysis failed: {e}. Falling back to PostgreSQL DB.")
                async with db_manager.async_session() as session:
                    result = await crud_job.analyze_by_keywords(
                        session,
                        keywords=keywords,
                        location=filters.get("location"),
                        industry_codes=industry_codes
                    )
                
            await redis_manager.set_cache(cache_key, result, expire=600, jitter=True)
            return result

    async def _fetch_industry_codes_with_cache(self, industry_code: int) -> List[int]:
        """根据行业 code 获取所有相关的子行业code列表 (利用 path 字段极速级联)"""
        if not industry_code:
            return []
            
        cache_key = f"analysis:industry_codes_v5:code:{industry_code}"
        cached = await redis_manager.get_cache(cache_key)
        if cached is not None:
            return cached
            
        from sqlalchemy import text
        
        async with db_manager.async_session() as session:
            # 1. 查找此行业 code 的 path
            path_stmt = text("SELECT path FROM industries WHERE code = :code LIMIT 1")
            path_result = await session.execute(path_stmt, {"code": industry_code})
            target_path = path_result.scalar_one_or_none()
            
            codes = []
            if target_path:
                # 2. 查询该 path 下面的所有子节点的 code (前缀匹配，走索引极快)
                stmt = text("SELECT code FROM industries WHERE path LIKE :path_prefix")
                result = await session.execute(stmt, {"path_prefix": f"{target_path}%"})
                codes = [row[0] for row in result.all()]
            
        if codes:
            await redis_manager.set_cache(cache_key, codes, expire=86400)
            
        return codes

    async def get_skill_cloud_stats(self, keyword: str, industry: int = None, industry_2: int = None, industry_name: str = None, industry_2_name: str = None, limit: int = 20) -> List[Dict[str, Any]]:

        
        cache_key = f"analysis:skill_cloud:v3:{keyword}:{industry}:{industry_2}:{limit}"
        cached_result = await redis_manager.get_cache(cache_key)
        if cached_result is not None:
            return cached_result
            
        try:
            es = await get_es()
            
            # 组装过滤条件
            bool_query = {}
            should_clauses = []
            
            # 条件 1: 专业关键字 / 行业关键字 (SHOULD: 命中任何一个)
            if keyword:
                should_clauses.append({"multi_match": {"query": keyword, "fields": ["title^3", "description"]}})
            if industry_name:
                should_clauses.append({"multi_match": {"query": industry_name, "fields": ["title^3", "description"]}})
            if industry_2_name:
                should_clauses.append({"multi_match": {"query": industry_2_name, "fields": ["title^3", "description"]}})
                
            if should_clauses:
                bool_query["must"] = [{"bool": {"should": should_clauses, "minimum_should_match": 1}}]
                
            filter_clauses = []
            
            # 条件 2: 目标行业 (FILTER: 严格限制范围)
            # if industry_2:
            #     industry_codes = await self._fetch_industry_codes_with_cache(industry_2)
            #     if industry_codes:
            #         filter_clauses.append({"terms": {"industry_code": industry_codes}})
            #     else:
            #         filter_clauses.append({"term": {"industry_code": -1}})
            if industry:
                industry_codes = await self._fetch_industry_codes_with_cache(industry)
                if industry_codes:
                    filter_clauses.append({"terms": {"industry_code": industry_codes}})
                else:
                    filter_clauses.append({"term": {"industry_code": -1}}) # 无效行业阻断
            else:
                # 若前端未传显式的 targetIndustry，尝试基于专业映射补全行业
                stmt = select(MajorIndustryRelation).where(MajorIndustryRelation.major_name == keyword)
                industry_data = None
                async with db_manager.async_session() as session:
                    ret = await session.execute(stmt)
                    industry_data = ret.scalar_one_or_none()
                
                if industry_data and industry_data.industry_codes:
                    filter_clauses.append({"terms": {"industry_code": industry_data.industry_codes}})

            if filter_clauses:
                bool_query["filter"] = filter_clauses

            exclude_list = list({
                keyword, 
                keyword.lower(), 
                keyword.upper(), 
                keyword.capitalize(), 
                ""
            }) if keyword else [""]
            
            query_dsl = {
                "query": {"bool": bool_query} if bool_query else {"match_all": {}},
                "size": 0,
                "aggs": {
                    "top_skills": {
                        "terms": {
                            "field": "skills",
                            "size": limit * 2,
                            "exclude": exclude_list 
                        }
                    },
                    "top_ai_skills": {
                        "terms": {
                            "field": "ai_skills",
                            "size": limit * 2,
                            "exclude": exclude_list
                        }
                    }
                }
            }
            
            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            aggs = resp.get("aggregations", {})
            
            skill_counter = Counter()
            
            for b in aggs.get("top_skills", {}).get("buckets", []):
                if b["key"].strip():
                    skill_counter[b["key"]] += b["doc_count"]
                    
            for b in aggs.get("top_ai_skills", {}).get("buckets", []):
                if b["key"].strip():
                    skill_counter[b["key"]] += b["doc_count"]
                    
            result = [{"name": k, "value": v} for k, v in skill_counter.most_common(limit)]
            
            await redis_manager.set_cache(cache_key, result, expire=3600, jitter=True) 
            return result
            
        except Exception as e:
            logger.error(f"Failed to fetch skill cloud stats from ES: {e}", exc_info=True)
            return []

analysis_service = AnalysisService()
