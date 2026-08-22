from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from config import settings
from common.databases.PostgresManager import db_manager
from common.databases.models.city import City
from common.databases.models.industry import Industry
from common.search.conn import get_es
from core.cache import cache
from core.logger import sys_logger as logger
from schemas.analysis_schema import (
    CompareAnalysisResponse,
    CompareBucketItem,
    CompareOverview,
    CompareSideResult,
    CompareSummary,
    CompareTrendItem,
)
from services.analysis_service import analysis_service
from services.market.skill_buckets import merge_skill_buckets
from services.market.skill_buckets import build_skill_aggregations
from services.market.skill_noise import get_skill_noise_rules


class ComparisonAnalysisService:
    """统一承载城市/行业对比分析查询。"""

    _SALARY_RANGES = [
        {"to": 10000.0, "key": "10k以下"},
        {"from": 10000.0, "to": 15000.0, "key": "10k-15k"},
        {"from": 15000.0, "to": 25000.0, "key": "15k-25k"},
        {"from": 25000.0, "to": 35000.0, "key": "25k-35k"},
        {"from": 35000.0, "key": "35k以上"},
    ]

    async def _build_common_query(
        self,
        keyword: Optional[str] = None,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        city_code: Optional[int] = None,
        industry_code: Optional[int] = None,
        industry_2_code: Optional[int] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        bool_query: Dict[str, Any] = {"filter": []}
        must_clauses: List[Dict[str, Any]] = []

        normalized_days = max(1, min(int(days or 30), 365))
        bool_query["filter"].append(
            {"range": {"created_at": {"gte": f"now-{normalized_days}d/d"}}}
        )

        if keyword:
            must_clauses.append(
                {
                    "multi_match": {
                        "query": keyword,
                        "fields": ["title^2", "description", "major_name"],
                    }
                }
            )

        if city_code:
            bool_query["filter"].append({"term": {"city_code": int(city_code)}})

        if experience and experience not in ("不限", "经验不限"):
            bool_query["filter"].append({"prefix": {"experience": str(experience)}})

        if education and education not in ("不限", "学历不限"):
            bool_query["filter"].append({"prefix": {"education": str(education)}})

        if industry_2_code:
            bool_query["filter"].append({"term": {"industry_code": int(industry_2_code)}})
        elif industry_code:
            industry_codes = await analysis_service._fetch_industry_codes_with_cache(  # noqa: SLF001
                int(industry_code)
            )
            if industry_codes:
                bool_query["filter"].append({"terms": {"industry_code": industry_codes}})
            else:
                bool_query["filter"].append({"term": {"industry_code": -1}})

        if must_clauses:
            bool_query["must"] = must_clauses

        return {"bool": bool_query}

    async def _build_subject_filter(
        self, dimension: str, value: int
    ) -> Dict[str, Any]:
        if dimension == "city":
            return {"term": {"city_code": int(value)}}

        industry_codes = await analysis_service._fetch_industry_codes_with_cache(int(value))  # noqa: SLF001
        if industry_codes:
            return {"terms": {"industry_code": industry_codes}}
        return {"term": {"industry_code": int(value)}}

    @classmethod
    def _side_aggs(cls) -> Dict[str, Any]:
        return {
            "salary_stats": {"stats": {"field": "salary_min"}},
            "salary_percentiles": {
                "percentiles": {"field": "salary_min", "percents": [25, 50, 75]}
            },
            "salary_ranges": {
                "range": {"field": "salary_min", "ranges": cls._SALARY_RANGES}
            },
            "high_salary_jobs": {
                "filter": {"range": {"salary_min": {"gte": 25000.0}}}
            },
            "trend_daily": {
                "date_histogram": {
                    "field": "created_at",
                    "calendar_interval": "day",
                    "min_doc_count": 0,
                }
            },
            "education_dist": {"terms": {"field": "education", "size": 10}},
            "experience_dist": {"terms": {"field": "experience", "size": 10}},
            **build_skill_aggregations(20),
        }

    async def _resolve_names(
        self, dimension: str, left_value: int, right_value: int
    ) -> Tuple[str, str]:
        model = City if dimension == "city" else Industry
        async with db_manager.async_session() as session:
            stmt = select(model.code, model.name).where(
                model.code.in_([int(left_value), int(right_value)])
            )
            result = await session.execute(stmt)
            code_to_name = {row.code: row.name for row in result}
        return (
            code_to_name.get(int(left_value), str(left_value)),
            code_to_name.get(int(right_value), str(right_value)),
        )

    @staticmethod
    def _parse_terms(buckets: List[Dict[str, Any]]) -> List[CompareBucketItem]:
        result: List[CompareBucketItem] = []
        for bucket in buckets or []:
            key = str(bucket.get("key", "")).strip() or "未知"
            result.append(CompareBucketItem(name=key, value=int(bucket.get("doc_count", 0))))
        return result

    @staticmethod
    def _parse_salary_ranges(buckets: List[Dict[str, Any]]) -> List[CompareBucketItem]:
        return [
            CompareBucketItem(name=str(bucket.get("key", "")), value=int(bucket.get("doc_count", 0)))
            for bucket in buckets or []
        ]

    @staticmethod
    def _parse_trend(buckets: List[Dict[str, Any]]) -> List[CompareTrendItem]:
        return [
            CompareTrendItem(
                date=str(bucket.get("key_as_string", ""))[:10],
                value=int(bucket.get("doc_count", 0)),
            )
            for bucket in buckets or []
        ]

    async def _parse_skills(self, aggs: Dict[str, Any], limit: int = 12) -> List[CompareBucketItem]:
        exact_rules, contains_rules = await get_skill_noise_rules()
        buckets = merge_skill_buckets(
            aggs,
            exact_noise=exact_rules,
            contains_noise=contains_rules,
            limit=limit,
        )
        return [CompareBucketItem(name=item["name"], value=item["value"]) for item in buckets]

    @staticmethod
    def _build_overview(aggs: Dict[str, Any], total_count: int) -> CompareOverview:
        stats = aggs.get("salary_stats", {}) or {}
        percentiles = (aggs.get("salary_percentiles", {}) or {}).get("values", {}) or {}
        high_salary_count = int(
            ((aggs.get("high_salary_jobs", {}) or {}).get("doc_count", 0)) or 0
        )

        def _num(value: Any) -> float:
            try:
                return round(float(value or 0), 2)
            except (TypeError, ValueError):
                return 0

        high_salary_ratio = round(high_salary_count / total_count, 4) if total_count else 0
        return CompareOverview(
            sample_size=total_count,
            salary_avg=_num(stats.get("avg")),
            salary_median=_num(percentiles.get("50.0")),
            salary_p25=_num(percentiles.get("25.0")),
            salary_p75=_num(percentiles.get("75.0")),
            high_salary_ratio=high_salary_ratio,
            job_count_30d=total_count,
        )

    async def _parse_side_result(
        self, side_id: int, side_name: str, aggs: Dict[str, Any]
    ) -> CompareSideResult:
        total_count = int(aggs.get("doc_count", 0) or 0)
        overview = self._build_overview(aggs, total_count)
        return CompareSideResult(
            id=int(side_id),
            name=side_name,
            overview=overview,
            salary_distribution=self._parse_salary_ranges(
                (aggs.get("salary_ranges", {}) or {}).get("buckets", [])
            ),
            trend=self._parse_trend((aggs.get("trend_daily", {}) or {}).get("buckets", [])),
            education_distribution=self._parse_terms(
                (aggs.get("education_dist", {}) or {}).get("buckets", [])
            ),
            experience_distribution=self._parse_terms(
                (aggs.get("experience_dist", {}) or {}).get("buckets", [])
            ),
            top_skills=await self._parse_skills(aggs),
        )

    @staticmethod
    def _build_summary(
        dimension: str, left: CompareSideResult, right: CompareSideResult
    ) -> CompareSummary:
        left_median = left.overview.salary_median
        right_median = right.overview.salary_median
        left_samples = left.overview.sample_size
        right_samples = right.overview.sample_size

        winner: Optional[str] = None
        if left_median > right_median:
            winner = "left"
        elif right_median > left_median:
            winner = "right"

        subject_label = "城市" if dimension == "city" else "行业"
        if left_samples < 20 or right_samples < 20:
            insight = f"当前{subject_label}样本量偏少，建议调整关键词或扩大时间范围后再比较。"
        elif winner == "left":
            insight = (
                f"{left.name} 的中位薪资更高，但也需要结合样本量和经验分布一起判断。"
            )
        elif winner == "right":
            insight = (
                f"{right.name} 的中位薪资更高，但也需要结合样本量和经验分布一起判断。"
            )
        else:
            insight = f"{left.name} 与 {right.name} 的中位薪资接近，建议重点看岗位量和技能要求差异。"

        return CompareSummary(
            winner_dimension=winner,
            salary_gap=round(right_median - left_median, 2),
            sample_gap=int(right_samples - left_samples),
            insight=insight,
        )

    async def compare_dimension(
        self,
        dimension: str,
        left_value: int,
        right_value: int,
        keyword: Optional[str] = None,
        city_code: Optional[int] = None,
        industry_code: Optional[int] = None,
        industry_2_code: Optional[int] = None,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        days: int = 30,
    ) -> CompareAnalysisResponse:
        common_query = await self._build_common_query(
            keyword=keyword,
            experience=experience,
            education=education,
            city_code=city_code,
            industry_code=industry_code,
            industry_2_code=industry_2_code,
            days=days,
        )
        left_filter = await self._build_subject_filter(dimension, left_value)
        right_filter = await self._build_subject_filter(dimension, right_value)

        dsl = {
            "size": 0,
            "track_total_hits": True,
            "query": common_query,
            "aggs": {
                "left": {"filter": left_filter, "aggs": self._side_aggs()},
                "right": {"filter": right_filter, "aggs": self._side_aggs()},
            },
        }

        es = await get_es()
        resp = await es.search(index=settings.ES_INDEX_JOB, body=dsl)
        aggs = resp.get("aggregations", {}) or {}
        left_name, right_name = await self._resolve_names(dimension, left_value, right_value)
        left_result = await self._parse_side_result(left_value, left_name, aggs.get("left", {}) or {})
        right_result = await self._parse_side_result(
            right_value, right_name, aggs.get("right", {}) or {}
        )
        summary = self._build_summary(dimension, left_result, right_result)
        return CompareAnalysisResponse(
            dimension=dimension,
            left=left_result,
            right=right_result,
            summary=summary,
        )

    @cache(expire=600, key_prefix="analysis:compare:cities:v1")
    async def compare_cities(
        self,
        left_city_code: int,
        right_city_code: int,
        keyword: Optional[str] = None,
        industry: Optional[int] = None,
        industry_2: Optional[int] = None,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        days: int = 30,
    ) -> CompareAnalysisResponse:
        if int(left_city_code) == int(right_city_code):
            raise ValueError("left_city_code and right_city_code must be different")
        return await self.compare_dimension(
            dimension="city",
            left_value=int(left_city_code),
            right_value=int(right_city_code),
            keyword=keyword,
            industry_code=industry,
            industry_2_code=industry_2,
            experience=experience,
            education=education,
            days=days,
        )

    @cache(expire=600, key_prefix="analysis:compare:industries:v1")
    async def compare_industries(
        self,
        left_industry_code: int,
        right_industry_code: int,
        keyword: Optional[str] = None,
        city_code: Optional[int] = None,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        days: int = 30,
    ) -> CompareAnalysisResponse:
        if int(left_industry_code) == int(right_industry_code):
            raise ValueError("left_industry_code and right_industry_code must be different")
        return await self.compare_dimension(
            dimension="industry",
            left_value=int(left_industry_code),
            right_value=int(right_industry_code),
            keyword=keyword,
            city_code=city_code,
            experience=experience,
            education=education,
            days=days,
        )


comparison_analysis_service = ComparisonAnalysisService()

