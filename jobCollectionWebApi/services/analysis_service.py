from typing import Dict, Any, List, Tuple
import hashlib
import json
import re
from config import settings
from common.databases.RedisManager import redis_manager
from common.databases.PostgresManager import db_manager
from crud.job import job as crud_job
from crud.industry import industry as crud_industry
from common.search.conn import get_es
from core.cache import cache
from core.logger import sys_logger as logger
from collections import Counter
from sqlalchemy import select
from common.databases.models.industry import Industry
from common.databases.models.system_config import SystemConfig
class AnalysisService:
    """数据分析服务（ES 聚合 + PostgreSQL 降级）。"""

    _CONFIG_KEY_SKILL_NOISE_EXACT = "analysis_skill_noise_exact"
    _CONFIG_KEY_SKILL_NOISE_CONTAINS = "analysis_skill_noise_contains"
    _SKILL_NOISE_CACHE_KEY = "analysis:config:skill_noise:v1"
    _SKILL_NOISE_CACHE_EXPIRE_SECONDS = 300
    _DEFAULT_SKILL_NOISE_EXACT = {
        "\u5176\u4ed6",
        "\u5176\u5b83",
        "\u4e0d\u9650",
        "\u65e0",
        "\u6682\u65e0",
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "others",
        "other",
    }
    _DEFAULT_SKILL_NOISE_CONTAINS = (
        "\u4e0d\u63a5\u53d7\u5c45\u5bb6\u529e\u516c",
        "\u5c45\u5bb6\u529e\u516c",
        "\u8fdc\u7a0b\u529e\u516c",
        "\u53cc\u4f11",
        "\u4e94\u9669",
        "\u793e\u4fdd",
        "\u516c\u79ef\u91d1",
        "\u5305\u5403",
        "\u5305\u4f4f",
        "\u5e74\u7ec8\u5956",
        "\u7ecf\u9a8c\u4e0d\u9650",
        "\u5b66\u5386\u4e0d\u9650",
        "\u63a5\u53d7\u5c0f\u767d",
    )

    def __init__(self):
        pass

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
    def _normalize_skill_tag(tag: Any) -> str:
        text = str(tag or "").strip()
        if not text:
            return ""
        return re.sub(r"\s+", " ", text)

    @classmethod
    def _parse_noise_tokens(cls, raw_value: Any) -> List[str]:
        if raw_value is None:
            return []

        if isinstance(raw_value, list):
            return [
                cls._normalize_skill_tag(item)
                for item in raw_value
                if cls._normalize_skill_tag(item)
            ]

        raw_text = str(raw_value).strip()
        if not raw_text:
            return []

        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, list):
                return [
                    cls._normalize_skill_tag(item)
                    for item in parsed
                    if cls._normalize_skill_tag(item)
                ]
        except json.JSONDecodeError:
            pass

        parts = re.split(r"[\r\n,;\uff0c\uff1b]+", raw_text)
        return [cls._normalize_skill_tag(item) for item in parts if cls._normalize_skill_tag(item)]

    async def _get_skill_noise_rules(self) -> Tuple[set[str], Tuple[str, ...]]:
        default_exact = {token.lower() for token in self._DEFAULT_SKILL_NOISE_EXACT}
        default_contains = tuple(self._DEFAULT_SKILL_NOISE_CONTAINS)

        cached_rules = await redis_manager.get_cache(self._SKILL_NOISE_CACHE_KEY)
        if isinstance(cached_rules, dict):
            exact_values = cached_rules.get("exact", [])
            contains_values = cached_rules.get("contains", [])
            exact_set = {
                self._normalize_skill_tag(v).lower()
                for v in exact_values
                if self._normalize_skill_tag(v)
            }
            contains_tuple = tuple(
                self._normalize_skill_tag(v)
                for v in contains_values
                if self._normalize_skill_tag(v)
            )
            if exact_set or contains_tuple:
                return exact_set or default_exact, contains_tuple or default_contains

        try:
            async with db_manager.async_session() as session:
                stmt = select(SystemConfig.key, SystemConfig.value).where(
                    SystemConfig.is_active == True,
                    SystemConfig.key.in_(
                        [self._CONFIG_KEY_SKILL_NOISE_EXACT, self._CONFIG_KEY_SKILL_NOISE_CONTAINS]
                    ),
                )
                rows = await session.execute(stmt)
                row_map = {row.key: row.value for row in rows}
        except Exception as exc:
            logger.warning(f"从数据库加载技能噪声配置失败: {exc}")
            return default_exact, default_contains

        exact_tokens = set(default_exact)
        exact_tokens.update(self._parse_noise_tokens(row_map.get(self._CONFIG_KEY_SKILL_NOISE_EXACT)))

        contains_tokens = list(default_contains)
        contains_tokens.extend(self._parse_noise_tokens(row_map.get(self._CONFIG_KEY_SKILL_NOISE_CONTAINS)))

        normalized_exact = {
            self._normalize_skill_tag(token).lower()
            for token in exact_tokens
            if self._normalize_skill_tag(token)
        }
        normalized_contains = tuple(
            self._normalize_skill_tag(token)
            for token in contains_tokens
            if self._normalize_skill_tag(token)
        )

        await redis_manager.set_cache(
            self._SKILL_NOISE_CACHE_KEY,
            {"exact": sorted(normalized_exact), "contains": list(normalized_contains)},
            expire=self._SKILL_NOISE_CACHE_EXPIRE_SECONDS,
            jitter=False,
        )

        return normalized_exact or default_exact, normalized_contains or default_contains

    @classmethod
    def _is_noise_skill_tag(
        cls,
        tag: str,
        exact_rules: set[str],
        contains_rules: Tuple[str, ...],
    ) -> bool:
        normalized = cls._normalize_skill_tag(tag)
        if not normalized:
            return True

        lowered = normalized.lower()
        if lowered in exact_rules:
            return True

        if any(token in normalized for token in contains_rules):
            return True

        # 过滤仅由数字/符号组成、无语义价值的标签。
        if re.fullmatch(r"[0-9\W_]+", normalized):
            return True

        return False

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
                            {"from": 35000.0, "key": "35k以上"},
                        ],
                    }
                },
                "top_industries": {"terms": {"field": "industry_code", "size": 10}},
                "top_skills": {"terms": {"field": "skills", "size": 15}},
                "top_ai_skills": {"terms": {"field": "ai_skills", "size": 15}},
            },
        }


        try:
            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
        except Exception as e:
            logger.error(f"ES 聚合查询失败: {e}", exc_info=True)
            return {"salary": [], "skills": [], "industries": [], "total_jobs": 0}

        # 5. 解析聚合结果
        aggs = resp.get("aggregations", {})
        salary_dist, industry_dist, skill_dist = await self.resove_agg_bucket(aggs)
        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist[:5],
            "total_jobs": resp["hits"]["total"]["value"],
        }

    @cache(expire=3600, key_prefix="analysis:home_stats_v2")
    async def get_home_stats(self) -> Dict[str, Any]:
        """专门为前端首页量身定制的无参数全局统查询。缓存时间长。"""
        try:
            es = await get_es()
            query_dsl = {
                "query": {"match_all": {}},
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
                                {"from": 35000.0, "key": "35k以上"},
                            ],
                        }
                    },
                    "top_industries": {"terms": {"field": "industry_code", "size": 10}},
                    "top_skills": {"terms": {"field": "skills", "size": 15}},
                    "top_ai_skills": {"terms": {"field": "ai_skills", "size": 15}},
                },
            }

            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            aggs = resp.get("aggregations", {})
            salary_dist, industry_dist, skill_dist = await self.resove_agg_bucket(aggs)
            
            return {
                "salary": salary_dist,
                "skills": skill_dist,
                "industries": industry_dist[:5],
                "total_jobs": resp["hits"]["total"]["value"],
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
        industry: int = None,
        industry_2: int = None,
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
                                {"from": 35000.0, "key": "35k以上"},
                            ],
                        }
                    },
                    "top_industries": {"terms": {"field": "industry_code", "size": 10}},
                    "top_skills": {"terms": {"field": "skills", "size": 15}},
                    "top_ai_skills": {"terms": {"field": "ai_skills", "size": 15}},
                },
            }

            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            aggs = resp.get("aggregations", {})
            salary_dist, industry_dist, skill_dist = await self.resove_agg_bucket(aggs)
            
            return {
                "salary": salary_dist,
                "skills": skill_dist,
                "industries": industry_dist[:5],
                "total_jobs": resp["hits"]["total"]["value"],
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
            "total_jobs": resp["hits"]["total"]["value"]
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
        """根据行业 code 获取有相关的子业code列表 (利用 path 字极级?"""
        if not industry_code:
            return []
        async with db_manager.async_session() as session:
            stmt = select(Industry.code).where(Industry.path.like(f"{industry_code}%"))
            result = await session.execute(stmt)
            codes = [row[0] for row in result.all()]
        return codes

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
            
            exact_rules, contains_rules = await self._get_skill_noise_rules()
            skill_counter = Counter()
            
            for b in aggs.get("top_skills", {}).get("buckets", []):
                label = self._normalize_skill_tag(b.get("key"))
                if self._is_noise_skill_tag(label, exact_rules, contains_rules):
                    continue
                skill_counter[label] += b["doc_count"]
                    
            for b in aggs.get("top_ai_skills", {}).get("buckets", []):
                label = self._normalize_skill_tag(b.get("key"))
                if self._is_noise_skill_tag(label, exact_rules, contains_rules):
                    continue
                skill_counter[label] += b["doc_count"]
                    
            result = [{"name": k, "value": v} for k, v in skill_counter.most_common(limit)]
            return result
            
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
        
        exact_rules, contains_rules = await self._get_skill_noise_rules()
        skill_counter = Counter()
        for b in aggs_result.get("top_skills", {}).get("buckets", []):
            label = self._normalize_skill_tag(b.get("key"))
            if self._is_noise_skill_tag(label, exact_rules, contains_rules):
                continue
            skill_counter[label] += b["doc_count"]
        for b in aggs_result.get("top_ai_skills", {}).get("buckets", []):
            label = self._normalize_skill_tag(b.get("key"))
            if self._is_noise_skill_tag(label, exact_rules, contains_rules):
                continue
            skill_counter[label] += b["doc_count"]
            
        skill_dist = [{"name": k, "value": v} for k, v in skill_counter.most_common(15)]
        return salary_dist,industry_dist,skill_dist
analysis_service = AnalysisService()



