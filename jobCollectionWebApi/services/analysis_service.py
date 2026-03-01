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
from core.logger import sys_logger as logger
from collections import Counter
from sqlalchemy import select
from common.databases.models.industry import Industry
from common.databases.models.major import Major, MajorIndustryRelation
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
        # 1. 关键词相关的文本匹配（命中任一条件即可）
        if keywords:
            for kw in keywords:
                should_clauses.append({
                    "multi_match": {
                        "query": kw,
                        "fields": ["title^2", "description",'major_name^2'] 
                    }
                })
        if industry_name:
            should_clauses.append({"multi_match": {"query": industry_name, "fields": ["title^2", "description",'major_name^2']}})

        if should_clauses:
            bool_query["must"] = [{"bool": {"should": should_clauses, "minimum_should_match": 1}}]

        # 2. 结构化过滤条件（必须满足）
        filter_clauses = []
        # if location:
        #     #filter_clauses.append({"prefix": {"location": location}})
        #     filter_clauses.append({"term": {"city_code": location}})

        # 行业过滤：优先按二级行业过滤；未提供二级行业时，使用一级行业。
        #target_industry_code = filters.get("industry_2") or filters.get("industry")
        target_industry_code = industry
        if target_industry_code:
            industry_codes = await self._fetch_industry_codes_with_cache(target_industry_code)
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


        try:
            resp = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
        except Exception as e:
            logger.error(f"ES 聚合查询失败: {e}", exc_info=True)
            return {"salary": [], "skills": [], "industries": [], "total_jobs": 0}

        # 5. 解析聚合结果
        aggs = resp.get("aggregations", {})
        salary_dist = [{"name": b["key"], "value": b["doc_count"]} for b in aggs.get("salary_ranges", {}).get("buckets", [])]

        # 行业编码映射为行业名称
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

        skill_dist = [{"name": k, "value": v} for k, v in skill_counter.most_common(10)]
        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist,
            "total_jobs": resp["hits"]["total"]["value"],
        }

    async def career_analysis(self, keywords: list[str], industry: int = None, industry_name: str = None, major_name: str = None) -> Dict[str, Any]:
        """获取职位统数据 (集成分布式锁防击穿与 ES/PG Fallback)"""
        cache_payload = {"keywords": keywords, "industry": industry, "industry_name": industry_name, "major_name": major_name}
        cache_key = f"analysis:stats:v3:{self._stable_digest(cache_payload)}"
        
        # 1. 直接查缓存
        cached_result = await redis_manager.get_cache(cache_key)
        if cached_result is not None: 
            logger.info(f"Analysis stats cache hit: {cache_key}")
            return cached_result
        logger.info(f"Analysis stats cache miss: {cache_key}")
            
        # 2. 缓存击穿防护：尝试获取分布式?(多等?5 秒，锁存?15 ?
        lock_key = f"lock:{cache_key}"
        async with redis_manager.cache_lock(lock_key, expire=15, timeout=5.0) as locked:
            if not locked:
                logger.warning(f"Failed to acquire cache lock for {cache_key}, returning empty set.")
                return {"salary": [], "skills": [], "industries": [], "total_jobs": 0}
            
            cached_result = await redis_manager.get_cache(cache_key)
            if cached_result is not None:
                logger.info(f"Analysis stats cache hit after lock: {cache_key}")
                return cached_result

            # 4. 执高时统查表
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
                        industry_name=industry_name,
                        major_name=major_name,
                    )
                     
            await redis_manager.set_cache(cache_key, result, expire=600, jitter=True)
            logger.debug(f"Analysis stats cache set: {cache_key}")
            return result

    async def _get_es_analyze_by_keywords(self, keywords: List[str], industry_codes: List[int] = None,location:str=None) -> Dict[str, Any]:
        """尝试?ES 聚合统多关锯（专业分析核心）"""
        es = await get_es()
        
        bool_query = {}
            
        should_clauses = []
        
        if industry_codes:
            should_clauses.append({"terms": {"industry_code": industry_codes}})
            
        if keywords:
            for kw in keywords:
                should_clauses.append({
                    "multi_match": {
                        "query": kw,
                        "fields": ["title^2", "description",'major_name^2'] 
                    }
                })
                
        if should_clauses:
            major_bool = {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1
                }
            }
            bool_query["must"] = [major_bool]
            
        if location:
            if "filter" not in bool_query:
                bool_query["filter"] = []
            bool_query["filter"].append({
                "prefix": {"location": location}
            })
            
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
        # ??????
        resp = await es.search(index=settings.ES_INDEX_JOB, body=dsl)
        # ??????
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
        
        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist,
            "total_jobs": resp["hits"]["total"]["value"]
        }

    async def analyze_by_keywords(self, keywords: List[str], industry_codes: List[int] = None,location:str=None) -> Dict[str, Any]:
        """多关锯对比分析"""
        if not keywords and not industry_codes: return {}
        cache_payload = {
            "keywords": sorted(keywords) if keywords else [],
            "industry_codes": sorted(industry_codes) if industry_codes else [],
            "location": location,
        }
        cache_key = f"analysis:major_skills:v1:{self._stable_digest(cache_payload)}"
        cached_result = await redis_manager.get_cache(cache_key)
        if cached_result is not None: 
            logger.debug(f"Analysis keywords cache hit: {cache_key}")
            return cached_result
        logger.debug(f"Analysis keywords cache miss: {cache_key}")

        lock_key = f"lock:{cache_key}"
        async with redis_manager.cache_lock(lock_key, expire=15, timeout=5.0) as locked:
            if not locked:
                return {}
            cached_result = await redis_manager.get_cache(cache_key)
            if cached_result is not None:
                logger.debug(f"Analysis keywords cache hit after lock: {cache_key}")
                return cached_result
            try:
                result = await self._get_es_analyze_by_keywords(keywords, industry_codes,location)
                logger.info("Generated keyword analysis via ES.")
            except Exception as e:
                logger.warning(f"ES Keyword Analysis failed: {e}. Falling back to PostgreSQL DB.")
                async with db_manager.async_session() as session:
                    result = await crud_job.analyze_by_keywords(
                        session,
                        keywords=keywords,
                        location=location,
                        industry_codes=industry_codes
                    )
                
            await redis_manager.set_cache(cache_key, result, expire=600, jitter=True)
            logger.debug(f"Analysis keywords cache set: {cache_key}")
            return result

    async def _fetch_industry_codes_with_cache(self, industry_code: int) -> List[int]:
        """根据行业 code 获取有相关的子业code列表 (利用 path 字极级?"""
        if not industry_code:
            return []
            
        cache_key = f"analysis:industry_codes_v5:code:{industry_code}"
        cached = await redis_manager.get_cache(cache_key)
        if cached is not None:
            return cached
            
        from sqlalchemy import text
        
        async with db_manager.async_session() as session:
            path_stmt = text("SELECT path FROM industries WHERE code = :code LIMIT 1")
            path_result = await session.execute(path_stmt, {"code": industry_code})
            target_path = path_result.scalar_one_or_none()
            
            codes = []
            if target_path:
                stmt = text("SELECT code FROM industries WHERE path LIKE :path_prefix")
                result = await session.execute(stmt, {"path_prefix": f"{target_path}%"})
                codes = [row[0] for row in result.all()]
            
        if codes:
            await redis_manager.set_cache(cache_key, codes, expire=86400)
            
        return codes

    async def get_skill_cloud_stats(self, keyword: str, industry: int = None, industry_name: str = None, limit: int = 20) -> List[Dict[str, Any]]:

        
        cache_key = f"analysis:skill_cloud:v3:{keyword}:{industry}:{limit}"
        cached_result = await redis_manager.get_cache(cache_key)
        if cached_result is not None:
            logger.debug(f"Skill cloud cache hit: {cache_key}")
            return cached_result
        logger.debug(f"Skill cloud cache miss: {cache_key}")
            
        try:
            es = await get_es()
            
            # 组过滤条件
            bool_query = {}
            should_clauses = []
            
            if keyword:
                should_clauses.append({"multi_match": {"query": keyword, "fields": ["title^3", "description","major_name^4"]}})
                #should_clauses.append({"multi_match": {"query": keyword}})
            if industry_name:
                should_clauses.append({"multi_match": {"query": industry_name, "fields": ["title^3", "description"]}})
            if should_clauses:
                bool_query["must"] = [{"bool": {"should": should_clauses, "minimum_should_match": 1}}]
                
            filter_clauses = []
            
            if industry:
                industry_codes = await self._fetch_industry_codes_with_cache(industry)
                if industry_codes:
                    filter_clauses.append({"terms": {"industry_code": industry_codes}})
                else:
                    filter_clauses.append({"term": {"industry_code": -1}}) # 无效行业阻断
            else:
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
            
            await redis_manager.set_cache(cache_key, result, expire=3600, jitter=True) 
            logger.debug(f"Skill cloud cache set: {cache_key}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to fetch skill cloud stats from ES: {e}", exc_info=True)
            return []

analysis_service = AnalysisService()



