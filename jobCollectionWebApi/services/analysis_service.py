from typing import Dict, Any, List
import hashlib
import json
from config import settings
from common.databases.PostgresManager import db_manager
from crud.job import job as crud_job
from crud.industry import industry as crud_industry
from common.search.conn import get_es
from core.cache import cache
from core.logger import sys_logger as logger
from sqlalchemy import or_, select
from common.databases.models.industry import Industry
from services.market.skill_buckets import build_skill_aggregations, merge_skill_buckets
from services.market.skill_noise import get_skill_noise_rules
class AnalysisService:
    """数据分析服务（ES 聚合 + PostgreSQL 降级）。"""

    def __init__(self):
        pass

    @staticmethod
    def _extract_total_hits(resp: Dict[str, Any]) -> int:
        hits = (resp or {}).get("hits") or {}
        total = hits.get("total", 0)
        if isinstance(total, dict):
            return int(total.get("value", 0) or 0)
        return int(total or 0)

    @staticmethod
    def _stable_digest(payload: Dict[str, Any]) -> str:
        """生成稳定的缓存摘要，避免进程重启后缓存键变化。"""
        serialized = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_market_aggregation_dsl(bool_query: Dict[str, Any] = None) -> Dict[str, Any]:
        """Build the shared ES aggregation used by career, home, and faceted stats."""
        return {
            "query": {"bool": bool_query} if bool_query else {"match_all": {}},
            "size": 0,
            "track_total_hits": True,
            "aggs": {
                "salary_ranges": {
                    "range": {
                        "field": "salary_min",
                        "ranges": [
                            {"to": 10000.0, "key": "10k以下"},
                            {"from": 10000.0, "to": 15000.0, "key": "10k-15k"},
                            {"from": 15000.0, "to": 25000.0, "key": "15k-25k"},
                            {"from": 25000.0, "to": 35000.0, "key": "25k-35k"},
                            {"from": 35000.0, "key": "35k以上"},
                        ],
                    }
                },
                "top_industries": {"terms": {"field": "industry_code", "size": 10}},
                **build_skill_aggregations(15),
            },
        }

    async def _project_skill_buckets(
        self,
        aggs_result: Dict[str, Any],
        *,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Merge ES skill buckets after applying the shared noise policy."""
        exact_rules, contains_rules = await get_skill_noise_rules()
        return merge_skill_buckets(
            aggs_result,
            exact_noise=exact_rules,
            contains_noise=contains_rules,
            limit=limit,
        )

    async def _project_market_aggregations(self, aggs_result: Dict[str, Any]) -> Dict[str, Any]:
        """Project shared market aggregation buckets without choosing caller DTOs."""
        salary_dist, industry_dist, skill_dist = await self.resove_agg_bucket(aggs_result)
        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist[:5],
        }

    async def _get_es_career_analysis(self, keywords: List[str],industry: int, industry_name: str, major_name: str) -> Dict[str, Any]:
        """优先使用 ES 聚合获取岗位统计。"""
        es = await get_es()
        bool_query = {}
        should_clauses = []
        filter_clauses = []
        # if industry_name:
        #     should_clauses.append({"multi_match": {"query": industry_name, "fields": ["title^2", "description",'major_name^2']}})

        # if should_clauses:
        #     bool_query["must"] = [{"bool": {"should": should_clauses, "minimum_should_match": 1}}]

        # 2. 结构化过滤条件（必须满足）
        
        if major_name:
            filter_clauses.append({"term": {"major_name": major_name}})
       
        # 行业过滤：优先按二级行业过滤；未提供二级行业时，使用一级行业。
        # target_industry_code = industry
        # if target_industry_code:
        #     industry_codes = await self._fetch_industry_codes_with_cache(target_industry_code)
        #     if industry_codes:
        #         filter_clauses.append({"terms": {"industry_code": industry_codes}})
        #     else:
        #         filter_clauses.append({"term": {"industry_code": -1}})

        if filter_clauses:
            bool_query["filter"] = filter_clauses

        query_dsl = self._build_market_aggregation_dsl(bool_query)


        try:
            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
        except Exception as e:
            logger.error(f"ES 聚合查询失败: {e}", exc_info=True)
            return {"salary": [], "skills": [], "industries": [], "total_jobs": 0}

        # 5. 解析聚合结果
        aggs = resp.get("aggregations", {})
        return {
            **await self._project_market_aggregations(aggs),
            "total_jobs": self._extract_total_hits(resp),
        }

    @cache(expire=3600, key_prefix="analysis:home_stats_v4")
    async def get_home_stats(self) -> Dict[str, Any]:
        """专门为前端首页量身定制的无参数全局统查询。缓存时间长。"""
        try:
            es = await get_es()
            query_dsl = self._build_market_aggregation_dsl()

            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            aggs = resp.get("aggregations", {})
            return {
                **await self._project_market_aggregations(aggs),
                "total_jobs": self._extract_total_hits(resp),
            }
        except Exception as e:
            logger.error(f"Home stats ES aggregation failed: {e}", exc_info=True)
            return {"salary": [], "skills": [], "industries": [], "total_jobs": 0}

    #@cache(expire=600, key_prefix="analysis:faceted_stats_v1")
    async def get_faceted_job_stats(
        self,
        keyword: str = None,
        location: str = None,
        experience: str = None,
        education: str = None,
        industry: int = None,
        industry_2: int = None,
        published_after=None,
    ) -> Dict[str, Any]:
        """专门用于带维度筛选的 ES 岗位统计分析查询"""
        try:
            es = await get_es()
            bool_query = {}
            filter_clauses = []
            should_clauses = []

            # 关键字处理
            search_kw = keyword
            if search_kw:
                should_clauses.append({
                    "multi_match": {
                        "query": search_kw,
                        "fields": ["title^2", "description", "major_name^2"]
                    }
                })
                bool_query["must"] = [{"bool": {"should": should_clauses, "minimum_should_match": 1}}]

            if location:
                filter_clauses.append({"term": {"city_code": location}})
                
            if experience and experience not in ("经验不限", "不限"):
                filter_clauses.append({"term": {"experience": experience}})

            if education:
                filter_clauses.append({"prefix": {"education": education}})

            if published_after:
                filter_clauses.append(
                    {"range": {"publish_date": {"gte": published_after.isoformat()}}}
                )
            
            # 行业筛选：如果传了 industry_2，则进行精准筛选 (term)
            if industry_2:
                filter_clauses.append({"term": {"industry_code": industry_2}})
            elif industry:
                # 如果只传了 industry，则获取其所有子行业进行范围筛选 (terms)
                industry_codes = await self._fetch_industry_codes_with_cache(industry)
                if industry_codes:
                    filter_clauses.append({"terms": {"industry_code": industry_codes}})
                else:
                    filter_clauses.append({"term": {"industry_code": -1}})
            
            if filter_clauses:
                bool_query["filter"] = filter_clauses

            query_dsl = self._build_market_aggregation_dsl(bool_query)

            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            aggs = resp.get("aggregations", {})
            return {
                **await self._project_market_aggregations(aggs),
                "total_jobs": self._extract_total_hits(resp),
            }
        except Exception as e:
            logger.error(f"Faceted ES aggregation failed: {e}", exc_info=True)
            raise e




    async def get_job_stats(
        self,
        keyword: str = None,
        location: int = None,
        experience: str = None,
        education: str = None,
        industry: int = None,
        industry_2: int = None,
        industry_name: str = None,
        industry_2_name: str = None,
        salary_min: float = None,
        salary_max: float = None,
        major_name: str = None,
    ) -> Dict[str, Any]:
        """
        Compatibility wrapper for /analysis/stats.
        Keeps old controller contract while reusing career_analysis implementation.
        """
        _ = (location, experience, education, salary_min, salary_max)  # reserved params

        keywords = []
        if keyword:
            keywords.append(keyword)
        if major_name and major_name not in keywords:
            keywords.append(major_name)
        if not keywords and major_name:
            keywords = [major_name]

        return await self.career_analysis(
            keywords=keywords,
            industry=industry_2 or industry,
            industry_name=industry_2_name or industry_name,
            major_name=major_name or keyword,
        )

    @cache(expire=600, key_prefix="analysis:career_analysis:v4")
    async def career_analysis(self, keywords: list[str], industry: int = None, industry_name: str = None, major_name: str = None) -> Dict[str, Any]:
        """获取职位统数据 (集成分布式锁防击穿与 ES/PG Fallback)"""
        try:
            result = await self._get_es_career_analysis(keywords, industry, industry_name, major_name)
            logger.info("Generated job stats using Elasticsearch Aggregations.")
        except Exception as e:
            logger.warning(f"ES Stats Aggregation failed: {e}. Falling back to PostgreSQL.")
            async with db_manager.async_session() as session:
                # Fallback logic: Use the first keyword for database search
                primary_keyword = keywords[0] if keywords else None
                result = await crud_job.get_statistics_from_db(
                    session,
                    keyword=primary_keyword,
                    industry=industry,
                )
        return result

    async def _get_es_analyze_by_keywords(
        self, 
        keywords: List[str], 
        industry_codes: List[int] = None,
        location:str=None,
        major_name:str=None
        ) -> Dict[str, Any]:
        """尝试?ES 聚合统多关锯（专业分析核心）"""
        es = await get_es()
        
        # 核心逻辑：
        # 共同条件： industry_code, major_name, location 作为全局精准过滤 (filter)
        # 关键字： keywords 作为泛查打分条件 (must -> should)
        bool_query = {}
        shoule_clauses = []
        must_clauses = []
        # 1. 精准过滤 (filter) 分支 - 这些条件必须同时满足，且不参与打分
        filter_clauses = []
        # if industry_codes:
        #     exact_filter_clauses.append({"terms": {"industry_code": industry_codes}})
        if major_name:
            filter_clauses.append({"term": {"major_name": major_name}})
        if location:
            filter_clauses.append({"prefix": {"location": location}})
            
        
        # 2. 关键字泛查 (must) 分支 - 必须包含关键字之一
        # if keywords:
        #     for kw in keywords:
        #         shoule_clauses.append({
        #             "multi_match": {
        #                 "query": kw,
        #                 "fields": ["title^2", "description", "major_name^5"] 
        #             }
        #         })
        #     if shoule_clauses:
        #         must_clauses.append({
        #             "bool": {
        #                 "should": shoule_clauses,
        #                 "minimum_should_match": 1
        #             }
        #         })
        if filter_clauses:
            bool_query['filter'] = filter_clauses
        # if must_clauses:
        #     bool_query['must'] = must_clauses

        # ==========================
        # ==========================
        aggs = {
            # (1) 薵分布 (分聚合)
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
            # (3) 能标签分?
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
        # ==========================
        dsl = {
            "query": {"bool": bool_query} if bool_query else {"match_all": {}},
            "size": 0,
            "track_total_hits": True,
            "aggs": aggs
        }
        print(dsl) 
        resp = await es.search(index=settings.ES_INDEX_JOB, body=dsl)
        # ??????
        aggs_result = resp.get("aggregations", {})
        
        salary_dist, industry_dist, skill_dist = await self.resove_agg_bucket(aggs_result)
        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist,
            "total_jobs": self._extract_total_hits(resp)
        }

    @cache(expire=600, key_prefix="analysis:major_skills:v2")
    async def analyze_by_keywords(self, keywords: List[str], industry_codes: List[int] = None,location:str=None,major_name:str=None) -> Dict[str, Any]:
        """多关锯对比分析"""
        if not keywords and not industry_codes: return {}
        try:
            result = await self._get_es_analyze_by_keywords(keywords, industry_codes,location,major_name)
            logger.info("Generated keyword analysis via ES.")
        except Exception as e:
            logger.warning(f"ES Keyword Analysis failed: {e}. Falling back to PostgreSQL DB.")
            async with db_manager.async_session() as session:
                result = await crud_job.analyze_by_keywords(
                    session,
                    keywords=keywords,
                    location=location,
                    industry_codes=industry_codes,
                    major_name=major_name
                )
        return result

    #@cache(expire=86400, key_prefix="analysis:industry_codes_v6")
    async def _fetch_industry_codes_with_cache(self, industry_code: int) -> List[int]:
        """Return the selected industry and all descendants by code/path."""
        if not industry_code:
            return []
        async with db_manager.async_session() as session:
            stmt = select(Industry.code).where(
                or_(
                    Industry.code == int(industry_code),
                    Industry.parent_id == int(industry_code),
                    Industry.path.like(f"%/{int(industry_code)}/%"),
                )
            )
            result = await session.execute(stmt)
            codes = {int(row[0]) for row in result.all()}
        return sorted(codes)

    @cache(expire=3600, key_prefix="analysis:skill_cloud:v4")
    async def get_skill_cloud_stats(self, keyword: str, industry: int = None, industry_name: str = None, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            es = await get_es()
            
            # 组过滤条件
            bool_query = {}
            should_clauses = []
            filter_clauses = []
            if keyword:
                filter_clauses.append({"term": {"major_name": keyword}})
            # if keyword:
            #     should_clauses.append({"multi_match": {"query": keyword, "fields": ["title^3", "description","major_name^4"]}})
            #     #should_clauses.append({"multi_match": {"query": keyword}})
            # if industry_name:
            #     should_clauses.append({"multi_match": {"query": industry_name, "fields": ["title^3", "description"]}})
            # if should_clauses:
            #     bool_query["must"] = [{"bool": {"should": should_clauses, "minimum_should_match": 1}}]
                
            
            
            # if industry:
            #     industry_codes = await self._fetch_industry_codes_with_cache(industry)
            #     if industry_codes:
            #         filter_clauses.append({"terms": {"industry_code": industry_codes}})
            #     else:
            #         filter_clauses.append({"term": {"industry_code": -1}}) # 无效行业阻断
            # else:
            #     stmt = select(MajorIndustryRelation).where(MajorIndustryRelation.major_name == keyword)
            #     industry_data = None
            #     async with db_manager.async_session() as session:
            #         ret = await session.execute(stmt)
            #         industry_data = ret.scalar_one_or_none()
                
            #     if industry_data and industry_data.industry_codes:
            #         filter_clauses.append({"terms": {"industry_code": industry_data.industry_codes}})

            if filter_clauses:
                bool_query["filter"] = filter_clauses

            exclude_list = list({
                keyword, 
                keyword.lower(), 
                keyword.upper(), 
                keyword.capitalize(), 
                ""
            }) if keyword else [""]
            
            skill_aggregations = build_skill_aggregations(limit * 2)
            for aggregation in skill_aggregations.values():
                aggregation["terms"]["exclude"] = exclude_list

            query_dsl = {
                "query": {"bool": bool_query} if bool_query else {"match_all": {}},
                "size": 0,
                "aggs": skill_aggregations,
            }
            
            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            aggs = resp.get("aggregations", {})
            
            return await self._project_skill_buckets(aggs, limit=limit)
            
        except Exception as e:
            logger.error(f"Failed to fetch skill cloud stats from ES: {e}", exc_info=True)
            return []



    async def resove_agg_bucket(self, aggs_result):
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
        
        skill_dist = await self._project_skill_buckets(aggs_result, limit=15)
        return salary_dist,industry_dist,skill_dist
analysis_service = AnalysisService()



