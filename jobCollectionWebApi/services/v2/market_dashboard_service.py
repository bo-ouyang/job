from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, Optional, Tuple

from config import settings
from crud import job as crud_job
from common.databases.PostgresManager import db_manager
from schemas.v2.common import DataStatus
from schemas.v2.market import (
    DistributionItem,
    FilterOption,
    KpiItem,
    MarketDashboardQuery,
    MarketDashboardResponse,
    MarketFilters,
    NamedValue,
    SalarySummary,
    TalentStructure,
    TrendData,
)
from services.analysis_service import analysis_service
from services.v2.market_test_data import MARKET_TEST_DATA


StatsLoader = Callable[[MarketDashboardQuery], Awaitable[Tuple[Dict, str]]]

MISSING_MARKET_DIMENSIONS = [
    "market.monthly_job_trend",
    "market.salary_percentiles",
    "market.normalized_skill_frequency",
    "market.city_competition",
    "market.talent_shortage_index",
    "market.source_coverage",
    "market.talent_structure",
    "market.filter_taxonomy",
]


class MarketDashboardService:
    def __init__(
        self,
        stats_loader: Optional[StatsLoader] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self._stats_loader = stats_loader or self._load_stats
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _numeric_code(value: Optional[str]) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def _load_stats(self, query: MarketDashboardQuery) -> Tuple[Dict, str]:
        city_code = self._numeric_code(query.city)
        industry_code = self._numeric_code(query.industry)
        if settings.ES_ENABLED:
            try:
                data = await analysis_service.get_faceted_job_stats(
                    location=city_code,
                    experience=query.experience,
                    industry=industry_code,
                )
                return data, "elasticsearch"
            except Exception:
                pass

        async with db_manager.async_session() as session:
            data = await crud_job.get_statistics_from_db(
                session,
                location=city_code,
                experience=query.experience,
                education=query.education,
                industry=industry_code,
            )
        return data, "postgresql"

    @staticmethod
    def _distribution(items: list) -> list[DistributionItem]:
        total = sum(max(0, float(item.get("value") or 0)) for item in items)
        if total <= 0:
            return []
        peak = max(float(item.get("value") or 0) for item in items)
        return [
            DistributionItem(
                label=str(item.get("name") or "未知"),
                value=round(float(item.get("value") or 0) / total * 100, 1),
                featured=float(item.get("value") or 0) == peak,
            )
            for item in items
        ]

    @staticmethod
    def _named_values(items: list) -> list[NamedValue]:
        return [
            NamedValue(name=str(item.get("name") or "未知"), value=float(item.get("value") or 0))
            for item in items
            if item.get("name")
        ]

    async def get_dashboard(self, query: MarketDashboardQuery) -> MarketDashboardResponse:
        raw, source = await self._stats_loader(query)
        total_jobs = int(raw.get("total_jobs") or 0)
        industries = self._named_values(raw.get("industries") or [])
        skills = self._named_values(raw.get("skills") or [])
        salary_distribution = self._distribution(raw.get("salary") or [])
        updated_at = self._now()

        synthetic_dimensions = [
            "market.monthly_job_trend",
            "market.salary_percentiles",
            "market.city_competition",
            "market.talent_shortage_index",
            "market.talent_structure",
            "market.filter_taxonomy",
        ]
        available_dimensions = ["market.total_jobs"]
        if salary_distribution:
            available_dimensions.append("market.salary_distribution")
        else:
            salary_distribution = [
                DistributionItem.model_validate(item)
                for item in MARKET_TEST_DATA["salary_distribution"]
            ]
            synthetic_dimensions.append("market.salary_distribution")
        if skills:
            available_dimensions.append("market.skill_frequency_raw")
        else:
            skills = [NamedValue.model_validate(item) for item in MARKET_TEST_DATA["skills"]]
            synthetic_dimensions.append("market.skill_frequency_raw")
        if industries:
            available_dimensions.append("market.industry_distribution")
            popular_industry = industries[0].name
        else:
            popular_industry = "人工智能 / 大模型"
            synthetic_dimensions.append("market.industry_distribution")

        synthetic_dimensions = list(dict.fromkeys(synthetic_dimensions))
        missing_dimensions = list(
            dict.fromkeys(MISSING_MARKET_DIMENSIONS + synthetic_dimensions)
        )
        has_real_display_data = bool(
            total_jobs or raw.get("salary") or raw.get("skills") or raw.get("industries")
        )
        display_source = "mixed" if has_real_display_data else "synthetic"

        return MarketDashboardResponse(
            updated_at=updated_at.isoformat(),
            data_status=DataStatus(
                source=display_source,
                degraded=True,
                updated_at=updated_at,
                available_dimensions=available_dimensions,
                missing_dimensions=missing_dimensions,
                synthetic_dimensions=synthetic_dimensions,
            ),
            filters=MarketFilters(
                ranges=[FilterOption(label="近 12 个月", value="12m"), FilterOption(label="近 6 个月", value="6m"), FilterOption(label="近 30 天", value="30d")],
                cities=[FilterOption(label=label, value=value) for label, value in (("全国", ""), ("北京", "北京"), ("上海", "上海"), ("深圳", "深圳"), ("杭州", "杭州"), ("成都", "成都"))],
                industries=[FilterOption(label=label, value=value) for label, value in (("全部行业", ""), ("互联网 / AI", "互联网/AI"), ("先进制造", "先进制造"), ("新能源", "新能源"), ("生物医药", "生物医药"))],
                educations=[FilterOption(label="不限学历", value=""), FilterOption(label="本科", value="本科"), FilterOption(label="硕士及以上", value="硕士")],
                experiences=[FilterOption(label="不限经验", value=""), FilterOption(label="应届 / 在校", value="应届生"), FilterOption(label="1–3 年", value="1-3年")],
            ),
            kpis=[
                KpiItem(label="在招岗位", value=total_jobs, note="当前有效样本", icon="▦", tone="blue"),
                KpiItem(label="全国月薪中位数", value="¥12,680", note="测试数据 · 待薪资快照", icon="¥", tone="mint"),
                KpiItem(label="热门行业", value=popular_industry, note="按岗位样本量", icon="↗", tone="violet"),
                KpiItem(label="技能需求热点", value=skills[0].name if skills else None, note="未标准化频次", icon="⌁", tone="orange"),
            ],
            hero_signals=MARKET_TEST_DATA["hero_signals"],
            trend=TrendData.model_validate(MARKET_TEST_DATA["trend"]),
            city_salaries=[NamedValue.model_validate(item) for item in MARKET_TEST_DATA["city_salaries"]],
            skills=skills,
            salary_distribution=salary_distribution,
            salary_summary=SalarySummary.model_validate(MARKET_TEST_DATA["salary_summary"]),
            talent_structure=TalentStructure.model_validate(MARKET_TEST_DATA["talent_structure"]),
            city_matrix=MARKET_TEST_DATA["city_matrix"],
            signals=MARKET_TEST_DATA["signals"],
            rankings=MARKET_TEST_DATA["rankings"],
        )


market_dashboard_service = MarketDashboardService()
