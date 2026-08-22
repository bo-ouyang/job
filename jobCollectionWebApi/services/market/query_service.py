"""Market-owned dimension resolution shared by product and Agent adapters."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from elasticsearch import ApiError, TransportError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.city import City
from common.databases.models.industry import Industry
from common.search.conn import ElasticsearchDisabledError
from config import settings
from core.logger import sys_logger as logger
from crud import job as crud_job
from services.market.errors import MarketResolutionError
from services.market.es_availability import classify_es_fallback
from services.analysis_service import analysis_service
from services.search_service import search_service


@dataclass(frozen=True)
class ResolvedDimension:
    """Canonical market dimension used by query adapters."""

    code: int
    name: str
    level: int


@dataclass(frozen=True)
class MarketStatisticsSnapshot:
    """Raw statistics plus source metadata, before any consumer projection."""

    data: Dict[str, Any]
    source: str
    warnings: List[str]
    warning_codes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class JobSearchSnapshot:
    """Raw job samples plus source metadata, before Agent normalization."""

    jobs: List[dict]
    total: int
    source: str
    warnings: List[str]
    warning_codes: List[str] = field(default_factory=list)


async def resolve_city(db: AsyncSession, value: str) -> ResolvedDimension:
    normalized = str(value or "").strip()
    if not normalized:
        raise MarketResolutionError("city is required")
    if normalized.isdigit():
        condition = City.code == int(normalized)
    else:
        condition = or_(
            func.lower(City.name) == normalized.lower(),
            func.lower(City.pinyin) == normalized.lower(),
        )
    result = await db.execute(select(City).where(condition).limit(2))
    matches = list(result.scalars().all())
    if not matches:
        raise MarketResolutionError(f"unknown or ambiguous city: {normalized}")

    if len(matches) == 1:
        city = matches[0]
    else:
        city_level_matches = [item for item in matches if int(item.level or 0) == 1]
        if len(city_level_matches) != 1:
            raise MarketResolutionError(f"unknown or ambiguous city: {normalized}")
        city = city_level_matches[0]
    return ResolvedDimension(code=int(city.code), name=city.name, level=int(city.level or 0))


async def resolve_industry(db: AsyncSession, value: str) -> ResolvedDimension:
    normalized = str(value or "").strip()
    if not normalized:
        raise MarketResolutionError("industry is required")
    if normalized.isdigit():
        condition = Industry.code == int(normalized)
    else:
        condition = or_(
            func.lower(Industry.name) == normalized.lower(),
            func.lower(Industry.pinyin) == normalized.lower(),
        )
    result = await db.execute(select(Industry).where(condition).limit(2))
    matches = list(result.scalars().all())
    if len(matches) != 1:
        raise MarketResolutionError(f"unknown or ambiguous industry: {normalized}")
    industry = matches[0]
    return ResolvedDimension(
        code=int(industry.code),
        name=industry.name,
        level=int(industry.level or 0),
    )


async def resolve_industry_codes(db: AsyncSession, industry_code: int) -> List[int]:
    path_fragment = f"%/{int(industry_code)}/%"
    result = await db.execute(
        select(Industry.code).where(
            or_(
                Industry.code == int(industry_code),
                Industry.parent_id == int(industry_code),
                Industry.path.like(path_fragment),
            )
        )
    )
    return sorted({int(code) for code in result.scalars().all()})


class MarketQueryService:
    """Owns market resolution, source selection, and PostgreSQL fallback."""

    def __init__(self, statistics_service=analysis_service, job_search_service=search_service):
        self._statistics_service = statistics_service
        self._job_search_service = job_search_service

    async def resolve_city(self, db: AsyncSession, value: str) -> ResolvedDimension:
        return await resolve_city(db, value)

    async def resolve_industry(self, db: AsyncSession, value: str) -> ResolvedDimension:
        return await resolve_industry(db, value)

    async def resolve_industry_codes(self, db: AsyncSession, industry_code: int) -> List[int]:
        return await resolve_industry_codes(db, industry_code)

    async def get_faceted_stats(
        self,
        db: AsyncSession,
        *,
        keyword: Optional[str] = None,
        location: Optional[int] = None,
        experience: Optional[str] = None,
        es_education: Optional[str] = None,
        pg_education: Optional[str] = None,
        industry: Optional[int] = None,
        industry_2: Optional[int] = None,
        published_after=None,
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
    ) -> MarketStatisticsSnapshot:
        fallback = None
        if settings.ES_ENABLED:
            try:
                data = await self._statistics_service.get_faceted_job_stats(
                    keyword=keyword,
                    location=location,
                    experience=experience,
                    education=es_education,
                    industry=industry,
                    industry_2=industry_2,
                    published_after=published_after,
                )
                return MarketStatisticsSnapshot(
                    data=data,
                    source="elasticsearch",
                    warnings=[],
                )
            except (ElasticsearchDisabledError, TransportError, ApiError) as exc:
                fallback = classify_es_fallback(exc)
                if fallback is None:
                    raise
                logger.bind(
                    component="market_query",
                    operation="faceted_stats",
                    source="elasticsearch",
                    fallback="postgresql",
                    reason=fallback.reason,
                ).opt(exception=exc).warning(
                    "Market statistics Elasticsearch query failed; using PostgreSQL fallback"
                )

        data = await crud_job.get_statistics_from_db(
            db,
            keyword=keyword,
            location=location,
            experience=experience,
            education=pg_education,
            industry=industry_2 or industry,
            published_after=published_after,
            salary_min=salary_min,
            salary_max=salary_max,
        )
        warnings = ["Elasticsearch 查询暂时不可用，已降级到 PostgreSQL"] if fallback else []
        warning_codes = [fallback.warning_code("market.stats")] if fallback else []
        return MarketStatisticsSnapshot(
            data=data,
            source="postgresql",
            warnings=warnings,
            warning_codes=warning_codes,
        )

    async def search_job_samples(
        self,
        db: AsyncSession,
        **filters,
    ) -> JobSearchSnapshot:
        jobs, total, source, warnings = await self._job_search_service.search_jobs_with_meta(
            **filters
        )
        return JobSearchSnapshot(
            jobs=jobs,
            total=total,
            source=source,
            warnings=warnings,
            warning_codes=[
                warning for warning in warnings if warning.startswith("search.es_fallback:")
            ],
        )


market_query_service = MarketQueryService()
